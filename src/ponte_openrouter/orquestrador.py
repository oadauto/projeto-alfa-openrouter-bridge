"""Orquestrador de fallback ordenado.

OR.10A implementou o caminho `modo="dryrun"`. OR.10B (mínima) conecta o
`modo="real"` a `executor_real.executar_chamada_real()`, sob a mesma
política de autorização humana individual por candidato (Modelo B,
homologada na OR.9): confirmação humana explícita antes de CADA tentativa,
recusa em qualquer ponto encerra toda a sequência, sem fallback automático.

Escopo estrito da OR.10B: apenas a conexão mínima com `executor_real.py`,
tratando exclusivamente estas classificações de resultado (vocabulário de
`executor.classificar_http()`):
- "sucesso" (HTTP 200): encerra a sequência com sucesso;
- "indisponibilidade" (HTTP 429 ou 5xx): registra a falha, avança para o
  próximo candidato (com novo aviso e nova confirmação humana individual -
  nunca fallback silencioso);
- "problema_de_credencial" (HTTP 401) ou "restricao_de_acesso" (HTTP 403):
  interrompe IMEDIATAMENTE a sequência inteira, sem tentar outro candidato
  (essas categorias indicam um problema que trocar de modelo não resolve -
  ver relatório OR.9, item 5, "matriz de erros");
- qualquer outra categoria ("nao_classificado"): tratada com a mesma
  cautela de 401/403 - interrompe e exige decisão humana, nunca avança por
  inferência sobre um código não mapeado.

Fora de escopo desta OR.10B (não implementado): Gemini, MCP do ChatGPT,
gravação no Notion, novos provedores, novas políticas de retry, e qualquer
mecanismo de logging além dos campos já estruturados em
`TentativaCandidato`/`ResultadoOrquestrado`.

Regras de origem de erro (ver relatório OR.9, item 9): todo resultado
produzido por este módulo tem origem_erro="openrouter" (quando uma
tentativa real de fato ocorreu) ou "nao_aplicavel" (dry-run nunca falha
por rede, e a recusa humana não chega a tentar nada) - NUNCA
"chatgpt_openai" nem "claude_sessao", que são atribuídos por outras
camadas fora deste módulo.

`openrouter/free` é tratado como um MODO SEPARADO, não como candidato
comum dentro da lista ordenada (decisão homologada na OR.9): este módulo
rejeita explicitamente qualquer candidato cujo id seja literalmente
"openrouter/free" antes de incluí-lo na sequência de tentativas.

Nota de separação (atualizada na OR.10B): este módulo agora importa
`executor_real` (necessidade estrita para o modo="real" existir) - a
importação é local, dentro do bloco que só executa quando modo="real",
espelhando o mesmo padrão de import tardio já usado dentro do próprio
`executor_real.py` para `requests`. O caminho `modo="dryrun"` continua
NUNCA tocando `executor_real`, `requests`, `urllib`, `httpx` ou
`credencial` - isso é verificado por teste (ver test_orquestrador.py).
Este módulo nunca importa Notion nem nenhum cliente MCP, em nenhum modo.

Fase 2 (integração mínima ao contrato do harness): adiciona
`sanitizar_resultado()` e `executar_via_contrato()`, que adaptam um
`ResultadoOrquestrado` para o `ResultadoSanitizado` definido em
`harness_contrato.py`, sem introduzir nenhuma chamada de rede nova e sem
alterar em nada o comportamento de `orquestrar()` acima (que continua
podendo ser chamado diretamente, como antes). `executar_via_contrato()`
apenas reaproveita, por composição, o portão de aprovação humana já
existente em `harness_contrato.aprovar_modo_real()` - nenhuma nova
abstração de autorização foi criada aqui; é o mesmo portão, chamado antes
de `orquestrar()` ser invocado. `harness_contrato` é puro stdlib (não
importa rede/credencial/Notion/MCP), então importá-lo aqui não viola a
regra de separação testada em `test_separacao.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import autorizacao as autorizacao_mod
from . import catalogo as catalogo_mod
from . import contexto as contexto_mod
from . import executor as executor_mod
from . import seletor as seletor_mod
from . import harness_contrato as harness_contrato_mod
from .seletor import Candidato
from .harness_contrato import EntradaTarefa, ResultadoSanitizado


ID_MODO_SEPARADO_ROTEADOR = "openrouter/free"

# Categorias de executor.classificar_http() que, ao ocorrer em modo="real",
# permitem avançar para o próximo candidato (falha atribuível ao modelo
# específico, não ao ambiente/credencial).
CATEGORIAS_QUE_PERMITEM_PROXIMO_CANDIDATO = {"indisponibilidade"}

# Categorias que interrompem a sequência inteira imediatamente - trocar de
# modelo não resolveria um problema de credencial, de acesso, ou um código
# não mapeado (ver relatório OR.9, item 5).
CATEGORIAS_QUE_INTERROMPEM_TUDO = {"problema_de_credencial", "restricao_de_acesso", "nao_classificado"}


@dataclass
class TentativaCandidato:
    """Registro de uma única tentativa (aprovada ou recusada) dentro de uma
    execução do orquestrador."""

    modelo_id: str
    origem_erro: str  # "openrouter" | "nao_aplicavel"
    categoria: str  # vocabulário de executor.classificar_http(), ou "sucesso_simulado", ou "recusado_pelo_humano"
    aprovado_por_humano: bool
    mensagem: str
    resposta_sanitizada: str | None = None
    # Espelha executor_real.ResultadoReal.resposta_paráfrase (OR.12): já vem
    # truncada a no máximo 300 caracteres pelo próprio executor_real.py, que
    # nunca inclui chave, token ou cabeçalho de autorização nesse campo -
    # este orquestrador apenas transporta o valor, sem reprocessá-lo.
    # None em modo dry-run e em qualquer tentativa sem sucesso HTTP 200.


@dataclass
class ResultadoOrquestrado:
    """Resultado agregado de uma execução completa do orquestrador."""

    tentativas: list[TentativaCandidato] = field(default_factory=list)
    candidato_final: Candidato | None = None
    encerrado_por: str = "nao_iniciado"
    # "sucesso" | "recusa_humana" | "candidatos_esgotados" | "sem_candidatos" | "interrompido_erro_critico"
    modo: str = "dryrun"


def _rejeitar_roteador_como_candidato_comum(candidatos: list[Candidato]) -> list[Candidato]:
    """Remove `openrouter/free` da lista de candidatos comuns, se presente.

    Decisão homologada na OR.9: o roteador openrouter/free não é um
    candidato como os demais - ele seleciona internamente, de forma
    variável, entre modelos gratuitos disponíveis. Por isso ele nunca
    entra na sequência A -> B -> C.
    """
    return [c for c in candidatos if c.modelo.id != ID_MODO_SEPARADO_ROTEADOR]


def orquestrar(
    tarefa: str,
    modelos_brutos: list[dict],
    resumo_curado: str,
    modo: str = "dryrun",
    obter_escolha_humana: Callable[[str], str] | None = None,
    prompt_ficticio: str | None = None,
) -> ResultadoOrquestrado:
    """Executa a sequência ordenada de candidatos, com confirmação humana
    individual antes de cada tentativa (política Modelo B, homologada na
    OR.9).

    `modo="dryrun"` (padrão): usa `executor.executar_dryrun()` - nunca
    falha por rede, sempre encerra em sucesso no primeiro candidato
    aprovado.

    `modo="real"` (OR.10B): usa `executor_real.executar_chamada_real()`.
    Exige `prompt_ficticio` não vazio. Cada tentativa real ainda exige
    confirmação humana explícita ANTES de ocorrer (a chamada a
    `executor_real` só acontece após `autorizacao.confirmar()` retornar
    autorizado) - a política de "nenhuma migração automática" se aplica
    igualmente aqui.
    """
    if modo not in ("dryrun", "real"):
        raise NotImplementedError(
            f"orquestrar(modo={modo!r}) não é suportado - apenas 'dryrun' e 'real' existem."
        )

    if modo == "real" and not (prompt_ficticio and prompt_ficticio.strip()):
        raise ValueError("modo='real' exige um 'prompt_ficticio' não vazio.")

    resultado = ResultadoOrquestrado(modo=modo)

    catalogo_filtrado = catalogo_mod.filtrar_gratuitos(modelos_brutos)
    if not catalogo_filtrado:
        resultado.encerrado_por = "sem_candidatos"
        return resultado

    candidatos_brutos = seletor_mod.selecionar(tarefa, catalogo_filtrado)
    candidatos = _rejeitar_roteador_como_candidato_comum(candidatos_brutos)

    if not candidatos:
        resultado.encerrado_por = "sem_candidatos"
        return resultado

    contexto_min = contexto_mod.montar_contexto_minimo(resumo_curado)

    descartados: list[Candidato] = []

    for candidato in candidatos:
        texto_apresentacao = autorizacao_mod.apresentar_candidatos([candidato])
        if descartados:
            texto_descartados = "\n".join(
                f"  - {d.modelo.id} (descartado nesta execução)" for d in descartados
            )
            texto_apresentacao = (
                f"Candidatos já descartados nesta execução:\n{texto_descartados}\n\n"
                f"Próximo candidato a avaliar:\n{texto_apresentacao}"
            )

        decisao = autorizacao_mod.confirmar(
            [candidato],
            obter_escolha_humana=obter_escolha_humana,
        )

        if not decisao.autorizado:
            resultado.tentativas.append(
                TentativaCandidato(
                    modelo_id=candidato.modelo.id,
                    origem_erro="nao_aplicavel",
                    categoria="recusado_pelo_humano",
                    aprovado_por_humano=False,
                    mensagem=f"Recusa humana: {decisao.motivo}. Sequência encerrada - nenhum outro candidato será proposto.",
                )
            )
            resultado.encerrado_por = "recusa_humana"
            return resultado

        if modo == "dryrun":
            resultado_dryrun = executor_mod.executar_dryrun(candidato.modelo.id, contexto_min)
            resultado.tentativas.append(
                TentativaCandidato(
                    modelo_id=candidato.modelo.id,
                    origem_erro="nao_aplicavel",
                    categoria="sucesso_simulado",
                    aprovado_por_humano=True,
                    mensagem=resultado_dryrun.mensagem,
                )
            )
            resultado.candidato_final = candidato
            resultado.encerrado_por = "sucesso"
            return resultado

        # modo == "real": import local, só acontece neste ramo (nunca no
        # caminho dry-run) - mesma disciplina de import tardio já usada em
        # executor_real.py para `requests`.
        from . import executor_real as executor_real_mod

        resultado_real = executor_real_mod.executar_chamada_real(
            candidato.modelo.id,
            prompt_ficticio,
            confirmar_execucao=True,
        )

        # OR.12: transporta a resposta já sanitizada/truncada de
        # executor_real (nunca a resposta bruta, nunca chave/token/cabeçalho -
        # esses nunca chegam a ResultadoReal.resposta_paráfrase). Limite de
        # 300 caracteres reforçado aqui também, defensivamente, mesmo que
        # executor_real já trunque - nunca confiar em uma única camada para
        # um limite de segurança.
        LIMITE_RESPOSTA_SANITIZADA = 300
        resposta_sanitizada = None
        if resultado_real.resposta_paráfrase is not None:
            resposta_sanitizada = resultado_real.resposta_paráfrase[:LIMITE_RESPOSTA_SANITIZADA]

        tentativa = TentativaCandidato(
            modelo_id=candidato.modelo.id,
            origem_erro="openrouter",
            categoria=resultado_real.categoria,
            aprovado_por_humano=True,
            mensagem=resultado_real.mensagem,
            resposta_sanitizada=resposta_sanitizada,
        )
        resultado.tentativas.append(tentativa)

        if resultado_real.categoria == "sucesso":
            resultado.candidato_final = candidato
            resultado.encerrado_por = "sucesso"
            return resultado

        if resultado_real.categoria in CATEGORIAS_QUE_INTERROMPEM_TUDO:
            resultado.encerrado_por = "interrompido_erro_critico"
            return resultado

        # Categoria em CATEGORIAS_QUE_PERMITEM_PROXIMO_CANDIDATO (ou
        # qualquer categoria de indisponibilidade equivalente): descarta
        # este candidato e avança para o próximo, com novo aviso e nova
        # confirmação humana no próximo laço.
        descartados.append(candidato)

    resultado.encerrado_por = "candidatos_esgotados"
    return resultado


def sanitizar_resultado(resultado: ResultadoOrquestrado) -> ResultadoSanitizado:
    """Fase 2: converte um `ResultadoOrquestrado` (formato interno deste
    módulo) em um `ResultadoSanitizado` (formato do contrato do harness),
    preservando exatamente os campos exigidos: modelo selecionado,
    categoria, origem do erro, número de tentativas, indicação explícita
    de fallback, resposta (já limitada a 300 caracteres por
    `ResultadoSanitizado.__post_init__`, que também rejeita categorias e
    origens fora do vocabulário fechado do contrato).

    Não inventa dados: quando não há nenhuma tentativa (`sem_candidatos`),
    a categoria é "nao_executado" e a origem "nao_aplicavel" - nunca um
    valor de sucesso implícito.
    """
    numero_tentativas = len(resultado.tentativas)

    if not resultado.tentativas:
        return ResultadoSanitizado(
            modelo=None,
            status_http=None,
            categoria="nao_executado",
            duracao_segundos=None,
            numero_tentativas=0,
            fallback_utilizado=False,
            resposta=None,
            origem_erro="nao_aplicavel",
        )

    ultima_tentativa = resultado.tentativas[-1]
    modelo = resultado.candidato_final.modelo.id if resultado.candidato_final else ultima_tentativa.modelo_id

    return ResultadoSanitizado(
        modelo=modelo,
        status_http=None,  # não rastreado em TentativaCandidato nesta fase
        categoria=ultima_tentativa.categoria,
        duracao_segundos=None,  # não rastreado em TentativaCandidato nesta fase
        numero_tentativas=numero_tentativas,
        fallback_utilizado=numero_tentativas >= 2,
        resposta=ultima_tentativa.resposta_sanitizada,
        origem_erro=ultima_tentativa.origem_erro,
    )


def executar_via_contrato(
    tarefa: str,
    modelos_brutos: list[dict],
    resumo_curado: str,
    *,
    modo: str = "dryrun",
    obter_escolha_humana: Callable[[str], str] | None = None,
    prompt_ficticio: str | None = None,
    papel_executor: str = "alfa",
    aprovado_por_humano: bool = False,
) -> ResultadoSanitizado:
    """Fase 2: ponto de entrada que passa primeiro pelo portão de
    aprovação e pelo portão de papel definidos em `harness_contrato.py`
    (reaproveitados por composição, não duplicados aqui) antes de delegar
    a `orquestrar()`. Em modo="real" sem `aprovado_por_humano=True`, isto
    levanta `AprovacaoAusenteError` e `orquestrar()` nunca chega a ser
    chamado - nenhuma tentativa, nenhuma chamada real, nenhum acesso a
    `executor_real`/`credencial`/rede ocorre nesse caso.
    """
    entrada = EntradaTarefa(
        tarefa=tarefa,
        modelos_brutos=tuple(modelos_brutos),
        resumo_curado=resumo_curado,
        modo=modo,
    )

    def _executor(_entrada: EntradaTarefa, _obter_escolha_humana):
        resultado = orquestrar(
            tarefa=_entrada.tarefa,
            modelos_brutos=list(_entrada.modelos_brutos),
            resumo_curado=_entrada.resumo_curado,
            modo=_entrada.modo,
            obter_escolha_humana=_obter_escolha_humana,
            prompt_ficticio=prompt_ficticio,
        )
        return sanitizar_resultado(resultado)

    return harness_contrato_mod.executar_contrato(
        entrada,
        _executor,
        papel_executor=papel_executor,
        obter_escolha_humana=obter_escolha_humana,
        aprovado_por_humano=aprovado_por_humano,
    )
