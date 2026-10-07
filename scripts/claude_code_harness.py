"""Ponto de entrada canônico do Claude Code para o harness local.

Recebe o contrato JSON em stdin e delega integralmente ao cliente local.
Claude continua responsável por preparar a tarefa e o contexto; este ponto
de entrada não seleciona modelos, não autoriza modo real e não faz rede.

Uso:
    $entrada | py scripts\\claude_code_harness.py
"""

from __future__ import annotations

import sys

from cliente_harness_local import main


if __name__ == "__main__":
    raise SystemExit(main())
