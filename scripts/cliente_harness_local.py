"""Cliente local do adaptador harness — Projeto ALFA, Fases 4B, 4E e 5.

Ponte técnica, não decisória: este script existe exclusivamente para que
Claude (o agente principal e orquestrador do sistema) tenha uma forma
programática de invocar `scripts/adaptador_harness.py` como subprocesso,
sem precisar montar a chamada de subprocesso manualmente a cada vez. Ele
não decide tarefas, não seleciona modelos, não autoriza execução real e
não substitui o julgamento de Claude ou do usuário - toda seleção,
autorização e execução continuam inteiramente sob as regras já aplicadas
em `harness_contrato.py` e `orquestrador.py` (Fases 1-3) e repassadas sem
alteração por `adaptador_harness.py` (Fase 4A).

Este cliente é deliberadamente burro: recebe um objeto JSON, repassa
exatamente esse objeto (sem adicionar, remover ou alterar nenhuma chave -
em especial, NUNCA insere `aprovado_por_humano` ou `confirmo_modo_real`
por conta própria) ao adaptador via stdin, lê o stdout do adaptador, e
devolve o mesmo resultado (sanitizado ou erro estruturado) e o mesmo
código de saída, sem reinterpretar nem filtrar o conteúdo. Nenhuma
chamada automática é repetida em caso de falha - não há retry nem
fallback implícito nesta camada.

## Fase 4E — robustez de borda (hardening)

Sem alterar o comportamento funcional de dry-run/modo real da Fase 4B,
a Fase 4E garante que, qualquer que seja a falha (timeout do subprocesso,
erro ao iniciar o processo, entrada não serializável, saída que não é
JSON válido, ou qualquer outra exceção inesperada), o resultado seja
SEMPRE um objeto JSON estruturado `{"erro": ..., "tipo_erro": ...}` em
stdout, nunca um traceback Python bruto e nunca stdout vazio. O timeout
do subprocesso é controlado e explícito (`TIMEOUT_PADRAO_SEGUNDOS`,
sobrescrevível por chamador programático via o parâmetro `timeout` de
`invocar_adaptador`); não há escrita implícita de timeout maior em caso
de falha, e nenhuma tentativa é repetida automaticamente.

## Fase 5 — observabilidade segura (opt-in)

`invocar_adaptador_observado()` e a opção `--log CAMINHO` do script
acrescentam um registro de observabilidade (uma linha JSON por chamada) com
código de saída, duração, modelo, status HTTP, sucesso/falha e um trecho
saneado de stderr - por lista branca, sem a resposta do modelo e sem
qualquer segredo (ver `observabilidade.py`). Sem `--log`/`log_path`, nada é
gravado e o comportamento é idêntico ao da Fase 4E. O stdout do script
continua contendo somente o resultado do harness.

## Continuidade controlada OpenRouter: confirmação humana interativa

`--continuidade-interativa` é o ÚNICO caminho que executa a continuidade
Claude/ChatGPT -> OpenRouter. O JSON (stdin) só descreve a situação
(`sinal_servico`, `modelo_continuidade`, `modelos_brutos`, `prompt_ficticio`);
aprovações e respostas contidas nele são ignoradas. As confirmações (serviço,
modelo, `AUTORIZO` e, para modelo não comprovadamente gratuito,
`ACEITO O CUSTO`) são lidas do TERMINAL (CONIN$ / /dev/tty), digitadas por uma
pessoa. Sem terminal real: recusa, sem chamada. Uma única chamada, com
`allow_fallbacks: false`, sem retry. O adaptador por JSON nunca executa.

## Uso como script (stdin/stdout, espelha o adaptador)

    py scripts\\cliente_harness_local.py < entrada.json

## Uso programático (o que Claude chamaria)

    from cliente_harness_local import invocar_adaptador
    saida, codigo_saida = invocar_adaptador({"tarefa": "...", ...})
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from observabilidade import LogPathInvalido, construir_registro, gravar_registro, validar_caminho_log

ADAPTADOR = Path(__file__).resolve().parent / "adaptador_harness.py"

# Timeout padrão e único ponto de controle desta camada - Fase 4E.
# Não há fallback para um timeout maior nem retry automático: ao expirar,
# a chamada falha de forma estruturada e para (ver invocar_adaptador).
TIMEOUT_PADRAO_SEGUNDOS = 30.0


def _bytes_para_texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (bytes, bytearray)):
        return bytes(valor).decode("utf-8", errors="replace")
    return str(valor)


def _invocar_com_detalhes(entrada: dict, timeout: float = TIMEOUT_PADRAO_SEGUNDOS) -> tuple[dict, int, dict]:
    """Núcleo de `invocar_adaptador` (comportamento funcional idêntico ao da
    Fase 4E) que também devolve detalhes brutos para a observabilidade da
    Fase 5: `{"stdout": str, "stderr": str, "duracao": float}`.

    Os detalhes são só informação adicional: nunca alteram `saida` nem o
    código de saída, e os textos brutos aqui contidos NÃO devem ser
    impressos nem gravados sem passar por `observabilidade.construir_registro`
    (que aplica lista branca, saneamento e truncamento).
    """
    inicio = time.monotonic()
    detalhes = {"stdout": "", "stderr": "", "duracao": 0.0}

    def _fim(saida: dict, codigo: int) -> tuple[dict, int, dict]:
        detalhes["duracao"] = time.monotonic() - inicio
        return saida, codigo, detalhes

    try:
        entrada_serializada = json.dumps(entrada)
        processo = subprocess.run(
            [sys.executable, str(ADAPTADOR)],
            input=entrada_serializada,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        detalhes["stdout"] = _bytes_para_texto(exc.stdout)
        detalhes["stderr"] = _bytes_para_texto(exc.stderr)
        return _fim(
            {
                "erro": f"o adaptador não respondeu dentro do timeout de {timeout}s.",
                "tipo_erro": "TimeoutExpired",
            },
            1,
        )
    except OSError as exc:
        return _fim(
            {"erro": f"falha ao invocar o adaptador: {type(exc).__name__}.", "tipo_erro": type(exc).__name__},
            1,
        )
    except (TypeError, ValueError) as exc:
        # json.dumps(entrada) falhou - entrada contém algo não serializável.
        # Nunca repassamos o conteúdo de `entrada` na mensagem de erro.
        return _fim(
            {"erro": "entrada não é serializável em JSON.", "tipo_erro": type(exc).__name__},
            2,
        )
    except Exception as exc:  # noqa: BLE001 - último guarda-chuva; nunca deixar vazar.
        return _fim(
            {"erro": "falha inesperada ao invocar o adaptador.", "tipo_erro": type(exc).__name__},
            1,
        )

    detalhes["stdout"] = _bytes_para_texto(processo.stdout)
    detalhes["stderr"] = _bytes_para_texto(processo.stderr)

    try:
        saida = json.loads(processo.stdout)
    except json.JSONDecodeError as exc:
        return _fim(
            {
                "erro": f"o adaptador devolveu uma saída que não é JSON válido: {exc}",
                "tipo_erro": "JSONDecodeError",
            },
            processo.returncode if processo.returncode != 0 else 1,
        )

    return _fim(saida, processo.returncode)


def invocar_adaptador(entrada: dict, timeout: float = TIMEOUT_PADRAO_SEGUNDOS) -> tuple[dict, int]:
    """Invoca `adaptador_harness.py` como subprocesso, enviando `entrada`
    exatamente como recebida (nenhuma chave é adicionada, removida ou
    alterada aqui - em especial, este cliente nunca insere
    `aprovado_por_humano` nem `confirmo_modo_real`: se não estiverem em
    `entrada`, o adaptador simplesmente não as verá, e o portão de
    aprovação em `harness_contrato.py` continua bloqueando o modo real
    normalmente).

    Devolve `(saida, codigo_saida)`: `saida` é o objeto JSON decodificado
    da resposta do adaptador (resultado sanitizado em sucesso, ou
    `{"erro": ..., "tipo_erro": ...}` em falha); `codigo_saida` é
    exatamente o código de saída do processo do adaptador, preservado sem
    reinterpretação em caso de sucesso ou de erro já estruturado pelo
    próprio adaptador.

    Garantia da Fase 4E: esta função NUNCA deixa uma exceção vazar e
    NUNCA repete a chamada por conta própria. Todo caminho de falha -
    `entrada` não serializável em JSON, timeout do subprocesso, falha ao
    iniciar o processo, ou saída do adaptador que não é JSON válido -
    devolve o mesmo formato estruturado `{"erro": ..., "tipo_erro": ...}`
    com um código de saída diferente de zero, sem traceback e sem
    qualquer chave, token, segredo ou credencial no texto do erro (as
    mensagens aqui descrevem apenas o tipo de falha técnica, nunca o
    conteúdo de `entrada`).
    """
    saida, codigo_saida, _detalhes = _invocar_com_detalhes(entrada, timeout)
    return saida, codigo_saida


def invocar_adaptador_observado(
    entrada: dict,
    timeout: float = TIMEOUT_PADRAO_SEGUNDOS,
    log_path=None,
) -> tuple[dict, int, dict]:
    """Fase 5 - igual a `invocar_adaptador`, mais um registro de
    observabilidade seguro.

    Devolve `(saida, codigo_saida, registro)`. `saida` e `codigo_saida` são
    exatamente os de `invocar_adaptador`. `registro` é construído por lista
    branca (ver `observabilidade.py`): código de saída, duração, modelo,
    status HTTP, sucesso/falha, tipo de erro, comprimentos de stdout/stderr e
    um trecho saneado e truncado de stderr. A resposta do modelo nunca entra
    no registro.

    Só grava em disco se `log_path` for informado (opt-in explícito); a
    gravação acrescenta uma linha JSON e uma falha ao gravar nunca altera
    `saida`, `codigo_saida` nem levanta exceção.
    """
    saida, codigo_saida, detalhes = _invocar_com_detalhes(entrada, timeout)
    registro = construir_registro(
        saida,
        codigo_saida,
        detalhes["duracao"],
        stdout=detalhes["stdout"],
        stderr=detalhes["stderr"],
    )
    if log_path is not None:
        registro = gravar_registro(registro, log_path)
    return saida, codigo_saida, registro


RAIZ_LOGS = Path(__file__).resolve().parent.parent / "logs"
RAIZ_SRC = Path(__file__).resolve().parent.parent / "src"


def executar_continuidade_interativa(entrada, leitor=None, log_path=None) -> tuple[dict, int]:
    """Executa a continuidade com confirmação digitada por uma pessoa.

    `leitor` (injetável só em testes) deve ser um leitor interativo marcado
    por `continuidade.leitor_interativo`; sem ele, abre o terminal real. As
    chaves `aprovado_por_humano`, `confirmo_modo_real` e `respostas_humanas`
    da entrada são ignoradas. Códigos: 0 executada; 2 entrada inválida ou sem
    oferta; 3 recusada (confirmação ausente/divergente ou sem terminal).
    """
    inicio = time.monotonic()
    if str(RAIZ_SRC) not in sys.path:
        sys.path.insert(0, str(RAIZ_SRC))
    from ponte_openrouter import continuidade as c

    def _fim(saida: dict, codigo: int) -> tuple[dict, int]:
        if log_path is not None:
            registro = construir_registro(
                saida, codigo, time.monotonic() - inicio, stdout=json.dumps(saida, ensure_ascii=False), stderr=""
            )
            gravar_registro(registro, log_path)
        return saida, codigo

    try:
        oferta = c.montar_oferta_de_json(entrada)
    except ValueError as exc:
        return _fim({"erro": str(exc), "tipo_erro": "EntradaInvalidaError"}, 2)
    if oferta is None:
        return _fim({"erro": "não há oferta de continuidade para este sinal.", "tipo_erro": "SemOferta"}, 2)
    prompt = entrada.get("prompt_ficticio") if isinstance(entrada.get("prompt_ficticio"), str) else ""
    try:
        registro = c.executar_oferta_confirmada(oferta, prompt, leitor)
    except ValueError:
        return _fim({"erro": "prompt inválido para o contexto mínimo.", "tipo_erro": "ContextoInvalido"}, 2)
    saida = {"continuidade": dict(registro, etapa="execucao")}
    return _fim(saida, 0 if registro["autorizado"] else 3)


def _ler_log_path(argv: list[str]):
    """Fase 5.2: lê e valida `--log CAMINHO` (opt-in).

    Sem `--log`, devolve None (nada é gravado). Com `--log`, o valor é
    obrigatório, não pode começar com `--` e deve passar por
    `validar_caminho_log` (dentro de `logs/`, sufixo `.jsonl`). Qualquer falha
    levanta `LogPathInvalido`, sem expor o caminho informado.
    """
    if "--log" not in argv:
        return None
    indice = argv.index("--log")
    if indice + 1 >= len(argv) or argv[indice + 1].startswith("--"):
        raise LogPathInvalido("valor ausente")
    return validar_caminho_log(argv[indice + 1], RAIZ_LOGS)


def main() -> int:
    # Fase 5.2: argumento --log inválido ou ausente é erro explícito, antes de
    # ler a entrada e sem executar o harness. A mensagem é fixa (não ecoa o
    # caminho informado).
    try:
        log_path = _ler_log_path(sys.argv[1:])
    except LogPathInvalido:
        print(
            json.dumps(
                {
                    "erro": "argumento --log invalido ou ausente (use um caminho .jsonl dentro de logs/).",
                    "tipo_erro": "LogPathInvalido",
                }
            )
        )
        return 2

    interativo = "--continuidade-interativa" in sys.argv[1:]
    bruto = sys.stdin.read()

    try:
        entrada = json.loads(bruto)
    except json.JSONDecodeError as exc:
        print(json.dumps({"erro": f"JSON de entrada inválido: {exc}", "tipo_erro": "JSONDecodeError"}))
        return 2

    if interativo:
        try:
            saida, codigo_saida = executar_continuidade_interativa(entrada, log_path=log_path)
            print(json.dumps(saida, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"erro": "falha inesperada no cliente local.", "tipo_erro": type(exc).__name__}))
            return 1
        return codigo_saida

    # Fase 4E: guarda-chuva final - mesmo uma falha totalmente inesperada
    # aqui (fora do que invocar_adaptador já trata) produz JSON estruturado
    # em stdout, nunca um traceback bruto e nunca stdout vazio.
    try:
        if log_path is None:
            saida, codigo_saida = invocar_adaptador(entrada)
        else:
            # Fase 5: o stdout continua sendo SOMENTE o resultado do harness;
            # o registro de observabilidade vai apenas para o arquivo.
            saida, codigo_saida, _registro = invocar_adaptador_observado(entrada, log_path=log_path)
        print(json.dumps(saida, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"erro": "falha inesperada no cliente local.", "tipo_erro": type(exc).__name__}))
        return 1

    return codigo_saida


if __name__ == "__main__":
    raise SystemExit(main())
