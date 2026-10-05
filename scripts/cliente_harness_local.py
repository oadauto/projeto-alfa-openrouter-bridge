"""Cliente local do adaptador harness — Projeto ALFA, Fase 4B.

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
código de saída, sem reinterpretar nem filtrar o conteúdo.

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


def invocar_adaptador(entrada: dict, timeout: float = 30.0) -> tuple[dict, int]:
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
    reinterpretação.

    Se o processo do adaptador não puder nem ser iniciado, ou devolver uma
    saída que não é JSON válido, este cliente devolve um erro estruturado
    no mesmo formato (`{"erro": ..., "tipo_erro": ...}`) em vez de deixar
    uma exceção vazar - nunca propaga um traceback bruto.
    """
    try:
        processo = subprocess.run(
            [sys.executable, str(ADAPTADOR)],
            input=json.dumps(entrada),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            {"erro": f"falha ao invocar o adaptador: {exc}", "tipo_erro": type(exc).__name__},
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

    saida, codigo_saida = invocar_adaptador(entrada)
    print(json.dumps(saida, ensure_ascii=False))
    return codigo_saida


if __name__ == "__main__":
    raise SystemExit(main())
