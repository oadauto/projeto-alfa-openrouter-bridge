"""Cliente local do adaptador harness — Projeto ALFA, Fases 4B e 4E.

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
from pathlib import Path

ADAPTADOR = Path(__file__).resolve().parent / "adaptador_harness.py"

# Timeout padrão e único ponto de controle desta camada - Fase 4E.
# Não há fallback para um timeout maior nem retry automático: ao expirar,
# a chamada falha de forma estruturada e para (ver invocar_adaptador).
TIMEOUT_PADRAO_SEGUNDOS = 30.0


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
    try:
        entrada_serializada = json.dumps(entrada)
        processo = subprocess.run(
            [sys.executable, str(ADAPTADOR)],
            input=entrada_serializada,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            {
                "erro": f"o adaptador não respondeu dentro do timeout de {timeout}s.",
                "tipo_erro": "TimeoutExpired",
            },
            1,
        )
    except OSError as exc:
        return (
            {"erro": f"falha ao invocar o adaptador: {type(exc).__name__}.", "tipo_erro": type(exc).__name__},
            1,
        )
    except (TypeError, ValueError) as exc:
        # json.dumps(entrada) falhou - entrada contém algo não serializável.
        # Nunca repassamos o conteúdo de `entrada` na mensagem de erro.
        return (
            {"erro": "entrada não é serializável em JSON.", "tipo_erro": type(exc).__name__},
            2,
        )
    except Exception as exc:  # noqa: BLE001 - último guarda-chuva; nunca deixar vazar.
        return (
            {"erro": "falha inesperada ao invocar o adaptador.", "tipo_erro": type(exc).__name__},
            1,
        )

    try:
        saida = json.loads(processo.stdout)
    except json.JSONDecodeError as exc:
        return (
            {
                "erro": f"o adaptador devolveu uma saída que não é JSON válido: {exc}",
                "tipo_erro": "JSONDecodeError",
            },
            processo.returncode if processo.returncode != 0 else 1,
        )

    return saida, processo.returncode


def main() -> int:
    bruto = sys.stdin.read()

    try:
        entrada = json.loads(bruto)
    except json.JSONDecodeError as exc:
        print(json.dumps({"erro": f"JSON de entrada inválido: {exc}", "tipo_erro": "JSONDecodeError"}))
        return 2

    # Fase 4E: guarda-chuva final - mesmo uma falha totalmente inesperada
    # aqui (fora do que invocar_adaptador já trata) produz JSON estruturado
    # em stdout, nunca um traceback bruto e nunca stdout vazio.
    try:
        saida, codigo_saida = invocar_adaptador(entrada)
        print(json.dumps(saida, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"erro": "falha inesperada no cliente local.", "tipo_erro": type(exc).__name__}))
        return 1

    return codigo_saida


if __name__ == "__main__":
    raise SystemExit(main())
