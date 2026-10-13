"""Continuidade controlada Claude/ChatGPT -> OpenRouter (ticket provisório:
"Continuidade controlada — oferta explícita OpenRouter"; sem número oficial).

Objetivo: quando o Claude ou o ChatGPT estiverem no limite, sem cota ou
indisponíveis, OFERECER o OpenRouter como alternativa - nunca trocar
silenciosamente.

Princípios (todos verificados em tests/test_continuidade.py):

1. O módulo NÃO detecta nem calcula cota. Quem informa o estado é uma FONTE
   AUTORIZADA (`FONTES_AUTORIZADAS`), por meio de um `SinalServico`. Sinal
   com serviço, estado ou fonte fora dos conjuntos fechados vira
   `desconhecido`. Nada é inferido nem inventado.
2. Somente `limite_atingido` e `indisponivel` geram oferta. `disponivel`,
   `limite_proximo` e `desconhecido` nunca geram oferta nem chamada.
3. Um sinal recebido do Claude/ChatGPT (entrada) é coisa diferente de um
   HTTP 429/5xx devolvido pelo OpenRouter (resultado de uma chamada). O
   registro mantém os dois separados (`fonte_sinal` x `origem_resultado`).
4. Execução exige TRÊS confirmações separadas e exatas (serviço, modelo,
   autorização), mais uma QUARTA (`ACEITO O CUSTO`) quando o modelo não é
   comprovadamente gratuito. Ausente, divergente ou inválida em qualquer
   uma: cancela tudo, sem chamada.
   As respostas só valem se vierem de um leitor INTERATIVO (`leitor_interativo`:
   terminal real, digitação direta). Respostas vindas de JSON, arquivo,
   pipe ou qualquer callable não marcado como interativo são recusadas
   antes de qualquer pergunta (`confirmacao_nao_interativa`).
5. Exatamente UMA chamada, direto em `executor_real.executar_chamada_real`
   (que envia `provider.allow_fallbacks=false`). Sem retry, sem outro
   modelo, e SEM passar por `orquestrador.orquestrar()` (cujo laço pode
   avançar para outros candidatos após 429/5xx). 200, 429, 5xx e códigos
   desconhecidos são resultado final.
6. O registro devolvido é montado por lista branca: nunca contém token,
   credencial, prompt, resposta (só o comprimento), nem mensagem livre de
   erro (só texto fixo por categoria e o NOME da classe de exceção).

Este módulo não importa `requests`, `credencial`, `executor_real`,
`orquestrador` nem rede no topo; `executor_real` só é importado dentro de
`executar_oferta_confirmada`, depois das três confirmações.

Integração ao harness: `scripts/adaptador_harness.py` usa `montar_oferta_de_json`
e `registro_oferta` (somente OFERTA, sem rede) e `registro_recusa_json` quando o
JSON traz aprovações/respostas; ele NUNCA executa. A execução real acontece só
em `scripts/cliente_harness_local.py --continuidade-interativa`, que lê as
confirmações do terminal (`leitor_interativo`) e chama
`executar_oferta_confirmada`. O registro em `logs/` é feito pela
observabilidade existente (`scripts/observabilidade.py`), por lista branca.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Callable

from . import contexto as contexto_mod

SCHEMA_VERSAO = 1

ESTADO_DISPONIVEL = "disponivel"
ESTADO_LIMITE_PROXIMO = "limite_proximo"
ESTADO_LIMITE_ATINGIDO = "limite_atingido"
ESTADO_INDISPONIVEL = "indisponivel"
ESTADO_DESCONHECIDO = "desconhecido"

ESTADOS = (
    ESTADO_DISPONIVEL,
    ESTADO_LIMITE_PROXIMO,
    ESTADO_LIMITE_ATINGIDO,
    ESTADO_INDISPONIVEL,
    ESTADO_DESCONHECIDO,
)

# Único conjunto de estados que podem gerar oferta.
ESTADOS_QUE_PERMITEM_OFERTA = frozenset({ESTADO_LIMITE_ATINGIDO, ESTADO_INDISPONIVEL})

# Serviços principais que o OpenRouter pode substituir como continuidade.
SERVICOS_AFETADOS = frozenset({"claude", "chatgpt"})

# Fontes autorizadas a informar o estado de um serviço. Conjunto fechado e
# editável apenas por alteração de código revisada (Codex) e autorizada por
# Adauto. Qualquer outra origem -> estado `desconhecido`.
FONTES_AUTORIZADAS = frozenset(
    {"adauto", "sessao_claude", "sessao_chatgpt", "api_claude", "api_chatgpt"}
)

# Vocabulário fechado de motivos (nunca texto livre).
MOTIVOS = {
    "cota_atingida": "cota ou limite de uso atingido",
    "limite_proximo": "limite de uso próximo",
    "servico_indisponivel": "serviço indisponível",
    "falha_servico": "falha do serviço",
    "nao_informado": "motivo não informado pela fonte",
}

CUSTO_INDISPONIVEL = "indisponível"

RESPOSTA_AUTORIZACAO = "AUTORIZO"
RESPOSTA_CUSTO = "ACEITO O CUSTO"
CUSTO_GRATUITO = "gratuito"

# Categorias do resultado (mesmo vocabulário de executor.classificar_http /
# harness_contrato) + categorias próprias deste módulo.
CATEGORIAS_RESULTADO = frozenset(
    {
        "sucesso",
        "problema_de_credencial",
        "restricao_de_acesso",
        "indisponibilidade",
        "nao_classificado",
        "nao_executado",
    }
)
CATEGORIA_RECUSADO = "recusado_pelo_humano"
CATEGORIA_FALHA_EXECUCAO = "falha_execucao"

# Texto fixo por categoria: o registro nunca repassa mensagem livre.
MENSAGENS_FIXAS = {
    "sucesso": "Chamada ao OpenRouter concluída com sucesso. Nenhuma outra chamada foi feita.",
    "problema_de_credencial": "OpenRouter recusou a credencial. Nenhuma nova tentativa foi feita.",
    "restricao_de_acesso": "OpenRouter restringiu o acesso. Nenhuma nova tentativa foi feita.",
    "indisponibilidade": "OpenRouter indisponível ou com limite (HTTP 429/5xx). Nenhuma nova tentativa nem outro modelo foi tentado.",
    "nao_classificado": "OpenRouter devolveu um código não mapeado. Decisão humana necessária; nenhuma nova tentativa foi feita.",
    "nao_executado": "A chamada não foi executada.",
    CATEGORIA_RECUSADO: "Confirmação ausente, divergente ou recusada. Nenhuma chamada foi feita.",
    CATEGORIA_FALHA_EXECUCAO: "Falha técnica ao executar a chamada. Nenhuma nova tentativa foi feita.",
}


@dataclass(frozen=True)
class SinalServico:
    """Estado de um serviço, informado EXPLICITAMENTE por uma fonte.

    O módulo não calcula percentuais nem deduz estado: apenas valida o que
    a fonte informou.
    """

    servico: str
    estado: str
    fonte: str
    motivo: str = "nao_informado"


def _em(valor: Any, conjunto) -> bool:
    return isinstance(valor, str) and valor in conjunto


def estado_efetivo(sinal: Any) -> str:
    """Estado confiável do sinal. Qualquer coisa fora dos conjuntos fechados
    (objeto inválido, serviço desconhecido, fonte não autorizada, estado
    inválido) devolve `desconhecido` - nunca um valor deduzido."""
    if not isinstance(sinal, SinalServico):
        return ESTADO_DESCONHECIDO
    if not _em(sinal.servico, SERVICOS_AFETADOS):
        return ESTADO_DESCONHECIDO
    if not _em(sinal.fonte, FONTES_AUTORIZADAS):
        return ESTADO_DESCONHECIDO
    if not _em(sinal.estado, ESTADOS):
        return ESTADO_DESCONHECIDO
    return sinal.estado


def sinal_de_json(dado: Any) -> SinalServico:
    """Converte o objeto JSON `sinal_servico` do adaptador em `SinalServico`.

    Só lê as chaves `servico`, `estado`, `fonte` e `motivo`, e só aceita
    strings: qualquer outra coisa vira vazio e, portanto, `desconhecido` em
    `estado_efetivo`. Nunca levanta exceção e nunca ecoa o conteúdo recebido.
    """
    if not isinstance(dado, dict):
        return SinalServico(servico="", estado="", fonte="")

    def _texto(chave: str) -> str:
        valor = dado.get(chave)
        return valor if isinstance(valor, str) else ""

    return SinalServico(
        servico=_texto("servico"),
        estado=_texto("estado"),
        fonte=_texto("fonte"),
        motivo=_texto("motivo") or "nao_informado",
    )


def estimar_custo(modelo_bruto: Any) -> str:
    """Custo estimado a partir do `pricing` do catálogo do OpenRouter.

    `gratuito` só se prompt e completion forem numericamente zero. Se o
    preço faltar ou for ilegível, devolve `indisponível` (nunca inventa).
    """
    if not isinstance(modelo_bruto, dict):
        return CUSTO_INDISPONIVEL
    pricing = modelo_bruto.get("pricing")
    if not isinstance(pricing, dict):
        return CUSTO_INDISPONIVEL
    try:
        entrada = float(pricing["prompt"])
        saida = float(pricing["completion"])
    except (KeyError, TypeError, ValueError):
        return CUSTO_INDISPONIVEL
    if not (math.isfinite(entrada) and math.isfinite(saida)) or entrada < 0 or saida < 0:
        return CUSTO_INDISPONIVEL
    if entrada == 0.0 and saida == 0.0:
        return "gratuito"
    return f"pago (entrada {entrada:g} USD/token, saída {saida:g} USD/token)"


@dataclass(frozen=True)
class Oferta:
    servico: str
    estado: str
    motivo: str
    fonte: str
    modelo_id: str
    custo_estimado: str
    texto: str


def _validar_modelo_id(modelo_id: Any) -> str:
    if (
        not isinstance(modelo_id, str)
        or not modelo_id
        or len(modelo_id) > 200
        or any(ch.isspace() or ord(ch) < 32 for ch in modelo_id)
    ):
        raise ValueError("modelo_id inválido: informe um identificador de modelo sem espaços.")
    return modelo_id


def _texto_oferta(servico: str, estado: str, motivo: str, fonte: str, modelo: str, custo: str) -> str:
    return (
        f"Continuidade: o serviço '{servico}' está em '{estado}' "
        f"(motivo: {MOTIVOS[motivo]}; fonte do sinal: {fonte}). "
        f"Alternativa disponível: OpenRouter, modelo '{modelo}', "
        f"custo estimado: {custo}. "
        "Nada será executado sem a sua confirmação separada de serviço, modelo e execução."
    )


def _validar_oferta(oferta: Any) -> None:
    """Defesa em profundidade: `Oferta` é um dataclass e pode ser construída
    à mão. Antes de qualquer confirmação ou chamada, exige que ela seja
    idêntica ao que `montar_oferta` produziria (estado ofertável, serviço,
    fonte e motivo dentro dos conjuntos fechados, modelo válido, custo em
    formato conhecido e texto determinístico). Mensagem fixa: nunca ecoa
    campos da oferta."""
    erro = ValueError("oferta inválida: use montar_oferta() com um sinal de fonte autorizada.")
    if not isinstance(oferta, Oferta):
        raise erro
    custo = oferta.custo_estimado
    custo_ok = isinstance(custo, str) and (
        custo in ("gratuito", CUSTO_INDISPONIVEL) or custo.startswith("pago (")
    )
    if not (
        _em(oferta.estado, ESTADOS_QUE_PERMITEM_OFERTA)
        and _em(oferta.servico, SERVICOS_AFETADOS)
        and _em(oferta.fonte, FONTES_AUTORIZADAS)
        and _em(oferta.motivo, MOTIVOS)
        and custo_ok
    ):
        raise erro
    try:
        _validar_modelo_id(oferta.modelo_id)
    except ValueError:
        raise erro from None
    esperado = _texto_oferta(
        oferta.servico, oferta.estado, oferta.motivo, oferta.fonte, oferta.modelo_id, custo
    )
    if oferta.texto != esperado:
        raise erro


def montar_oferta(sinal: Any, modelo_id: str, modelo_bruto: Any = None) -> Oferta | None:
    """Monta a oferta de continuidade, ou devolve None se o estado efetivo
    não permitir oferta (`disponivel`, `limite_proximo`, `desconhecido`).

    Só monta texto: não executa nada, não pede confirmação, não chama rede.
    """
    estado = estado_efetivo(sinal)
    if estado not in ESTADOS_QUE_PERMITEM_OFERTA:
        return None

    modelo = _validar_modelo_id(modelo_id)
    motivo = sinal.motivo if _em(sinal.motivo, MOTIVOS) else "nao_informado"
    custo = estimar_custo(modelo_bruto)

    return Oferta(
        servico=sinal.servico,
        estado=estado,
        motivo=motivo,
        fonte=sinal.fonte,
        modelo_id=modelo,
        custo_estimado=custo,
        texto=_texto_oferta(sinal.servico, estado, motivo, sinal.fonte, modelo, custo),
    )


@dataclass(frozen=True)
class DecisaoContinuidade:
    autorizado: bool
    motivo: str  # vocabulário fixo; nunca ecoa a resposta digitada


def confirmar_tripla(
    oferta: Oferta,
    obter_resposta: Callable[[str], str] | None = None,
) -> DecisaoContinuidade:
    """Três confirmações separadas e exatas, nesta ordem (quatro se o modelo
    não for comprovadamente gratuito):

    1. nome do serviço afetado;
    2. identificador do modelo OpenRouter;
    3. a palavra `AUTORIZO` (autorização da execução);
    4. somente se `custo_estimado != "gratuito"` (pago ou indisponível):
       `ACEITO O CUSTO` (autorização de custo, separada da execução).

    A primeira resposta ausente, divergente ou inválida cancela tudo; as
    perguntas seguintes nem chegam a ser feitas. Não existe confirmação
    única implícita. `obter_resposta` é injetável (testes); o padrão é
    `input`.
    """
    pedir = obter_resposta or input
    total = 3 if oferta.custo_estimado == CUSTO_GRATUITO else 4
    etapas = [
        (
            "servico",
            f"{oferta.texto}\n\n[1/{total}] Digite o nome do serviço afetado ('{oferta.servico}'): ",
            lambda r: r.strip().lower() == oferta.servico.lower(),
        ),
        (
            "modelo",
            f"[2/{total}] Digite exatamente o modelo OpenRouter ('{oferta.modelo_id}'): ",
            lambda r: r.strip() == oferta.modelo_id,
        ),
        (
            "execucao",
            f"[3/{total}] Para autorizar UMA única chamada real, digite {RESPOSTA_AUTORIZACAO}: ",
            lambda r: r.strip() == RESPOSTA_AUTORIZACAO,
        ),
    ]
    if total == 4:
        etapas.append(
            (
                "custo",
                f"[4/4] Custo estimado: {oferta.custo_estimado}. Para aceitar esse custo, digite {RESPOSTA_CUSTO}: ",
                lambda r: r.strip() == RESPOSTA_CUSTO,
            )
        )
    for nome, pergunta, confere in etapas:
        try:
            resposta = pedir(pergunta)
        except Exception:  # noqa: BLE001 - EOF, interrupção etc.: sem resposta = sem autorização
            return DecisaoContinuidade(False, f"resposta_ausente_{nome}")
        if not isinstance(resposta, str):
            return DecisaoContinuidade(False, f"resposta_invalida_{nome}")
        if not confere(resposta):
            return DecisaoContinuidade(False, f"confirmacao_divergente_{nome}")
    return DecisaoContinuidade(True, "autorizado_nas_tres_confirmacoes" if total == 3 else "autorizado_nas_quatro_confirmacoes")


def _registro(
    oferta: Oferta,
    *,
    autorizado: bool,
    motivo_decisao: str,
    categoria: str,
    chamada_realizada: bool,
    status_http: Any = None,
    resposta_caracteres: int = 0,
    tipo_erro: str | None = None,
) -> dict:
    """Registro seguro por LISTA BRANCA. Todo valor é fixo, vem de um
    vocabulário fechado, é numérico ou é o nome de uma classe de exceção."""
    if not isinstance(status_http, int) or isinstance(status_http, bool):
        status_http = None
    return {
        "schema_versao": SCHEMA_VERSAO,
        "servico_afetado": oferta.servico,
        "estado_servico": oferta.estado,
        "fonte_sinal": oferta.fonte,
        "motivo": oferta.motivo,
        "modelo": oferta.modelo_id,
        "custo_estimado": oferta.custo_estimado,
        "autorizado": autorizado,
        "motivo_decisao": motivo_decisao,
        "chamada_realizada": chamada_realizada,
        "numero_chamadas": 1 if chamada_realizada else 0,
        "retry": False,
        "troca_de_modelo": False,
        "fallback_utilizado": False,
        # HTTP 429/5xx só existe quando a chamada ao OpenRouter ocorreu; o
        # sinal do Claude/ChatGPT (`fonte_sinal`) nunca vira status_http.
        "origem_resultado": "openrouter" if chamada_realizada else "nao_aplicavel",
        "categoria": categoria,
        "status_http": status_http,
        "resposta_caracteres": resposta_caracteres,
        "tipo_erro": tipo_erro,
        "mensagem": MENSAGENS_FIXAS[categoria],
    }


def registro_oferta(oferta: Oferta) -> dict:
    """Registro seguro da etapa de OFERTA (nada executado, nenhuma confirmação
    pedida, nenhuma rede). Mesmos campos do registro de execução, mais o
    texto da oferta, que só contém valores validados e texto fixo."""
    _validar_oferta(oferta)
    registro = _registro(
        oferta,
        autorizado=False,
        motivo_decisao="aguardando_confirmacao",
        categoria="nao_executado",
        chamada_realizada=False,
    )
    registro["oferta_texto"] = oferta.texto
    return registro


class SemTerminalInterativoError(RuntimeError):
    """Não há terminal real para digitação direta. Mensagem fixa."""


def _abrir_terminal():
    if os.name == "nt":
        return open("CONIN$", "r"), open("CONOUT$", "w")
    return open("/dev/tty", "r"), open("/dev/tty", "w")


def leitor_interativo(abrir: Callable[[], Any] | None = None) -> Callable[[str], str]:
    """Leitor de confirmações digitadas por uma PESSOA no terminal.

    Lê do dispositivo de console (CONIN$ no Windows, /dev/tty no Unix), e não
    de stdin: stdin pode ser um pipe/JSON controlado por script. Se não houver
    terminal real (`isatty` falso nas duas pontas), levanta
    `SemTerminalInterativoError`. O callable devolvido carrega a marca
    `origem_interativa=True`, exigida por `executar_oferta_confirmada`.
    `abrir` é injetável apenas para testes.
    """
    try:
        entrada, saida = (abrir or _abrir_terminal)()
        if not (entrada.isatty() and saida.isatty()):
            raise SemTerminalInterativoError()
    except Exception:  # noqa: BLE001 - nunca ecoar detalhes do sistema
        raise SemTerminalInterativoError("Nenhum terminal interativo disponível.") from None

    def _ler(pergunta: str) -> str:
        saida.write(pergunta)
        saida.flush()
        linha = entrada.readline()
        if linha == "":
            raise EOFError
        return linha.rstrip("\r\n")

    _ler.origem_interativa = True  # type: ignore[attr-defined]
    return _ler


def montar_oferta_de_json(entrada_json: Any) -> Oferta | None:
    """Oferta a partir do JSON do harness (`sinal_servico`,
    `modelo_continuidade`, `modelos_brutos`). None se o sinal não permitir
    oferta. ValueError (mensagem fixa) se faltar `modelo_continuidade`."""
    if not isinstance(entrada_json, dict):
        return None
    sinal = sinal_de_json(entrada_json.get("sinal_servico"))
    if estado_efetivo(sinal) not in ESTADOS_QUE_PERMITEM_OFERTA:
        return None
    modelo_id = entrada_json.get("modelo_continuidade")
    if not isinstance(modelo_id, str) or not modelo_id.strip():
        raise ValueError("'modelo_continuidade' é obrigatório quando há sinal de indisponibilidade.")
    brutos = entrada_json.get("modelos_brutos")
    modelo_bruto = next(
        (m for m in (brutos if isinstance(brutos, list) else []) if isinstance(m, dict) and m.get("id") == modelo_id),
        None,
    )
    return montar_oferta(sinal, modelo_id, modelo_bruto)


def registro_recusa_json(oferta: Oferta) -> dict:
    """Registro de recusa: o JSON trouxe aprovações/respostas, que não provam
    confirmação humana. Nenhuma pergunta, nenhuma rede."""
    _validar_oferta(oferta)
    return _registro(
        oferta,
        autorizado=False,
        motivo_decisao="confirmacao_apenas_por_json",
        categoria=CATEGORIA_RECUSADO,
        chamada_realizada=False,
    )


def executar_oferta_confirmada(
    oferta: Oferta,
    prompt: str,
    obter_resposta: Callable[[str], str] | None = None,
) -> dict:
    """Fluxo real da continuidade: confirmação interativa (3 ou 4 respostas) -> UMA chamada direta
    a `executor_real` -> registro seguro.

    Não chama `orquestrar()`, não tenta outro modelo, não faz retry. O
    prompt é validado como contexto mínimo (`contexto.montar_contexto_minimo`,
    máx. 2000 caracteres) e só é entregue ao executor; nunca entra no
    registro.
    """
    _validar_oferta(oferta)
    # Valida antes de pedir qualquer confirmação (ValueError com mensagem fixa).
    contexto = contexto_mod.montar_contexto_minimo(prompt if isinstance(prompt, str) else "")

    if obter_resposta is None:
        try:
            obter_resposta = leitor_interativo()
        except SemTerminalInterativoError:
            return _registro(
                oferta, autorizado=False, motivo_decisao="sem_terminal_interativo",
                categoria=CATEGORIA_RECUSADO, chamada_realizada=False,
            )
    if getattr(obter_resposta, "origem_interativa", False) is not True:
        # Respostas pré-gravadas (JSON, arquivo, pipe, lista) não provam
        # confirmação humana: recusa antes de qualquer pergunta.
        return _registro(
            oferta, autorizado=False, motivo_decisao="confirmacao_nao_interativa",
            categoria=CATEGORIA_RECUSADO, chamada_realizada=False,
        )

    decisao = confirmar_tripla(oferta, obter_resposta)
    if not decisao.autorizado:
        return _registro(
            oferta,
            autorizado=False,
            motivo_decisao=decisao.motivo,
            categoria=CATEGORIA_RECUSADO,
            chamada_realizada=False,
        )

    # Import tardio: só depois das três confirmações.
    from . import executor_real as executor_real_mod

    try:
        resultado = executor_real_mod.executar_chamada_real(
            oferta.modelo_id,
            contexto,
            confirmar_execucao=True,
        )
    except Exception as exc:  # noqa: BLE001 - nunca propagar mensagem de erro (pode conter segredo)
        return _registro(
            oferta,
            autorizado=True,
            motivo_decisao=decisao.motivo,
            categoria=CATEGORIA_FALHA_EXECUCAO,
            chamada_realizada=True,
            tipo_erro=type(exc).__name__,
        )

    categoria = getattr(resultado, "categoria", None)
    if not _em(categoria, CATEGORIAS_RESULTADO):
        categoria = "nao_classificado"
    texto_resposta = getattr(resultado, "resposta_paráfrase", None)
    return _registro(
        oferta,
        autorizado=True,
        motivo_decisao=decisao.motivo,
        categoria=categoria,
        chamada_realizada=True,
        status_http=getattr(resultado, "codigo_http", None),
        resposta_caracteres=len(texto_resposta) if isinstance(texto_resposta, str) else 0,
    )
