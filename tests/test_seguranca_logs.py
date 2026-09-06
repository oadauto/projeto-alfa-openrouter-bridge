"""Teste de segurança transversal: varre o código-fonte do pacote e as
saídas que os outros testes produzem, procurando por padrões que possam
indicar vazamento de chave/segredo.

Este teste NUNCA lida com uma chave real - ele apenas garante que nenhum
padrão suspeito aparece no código-fonte do pacote (uma chave real jamais
deveria estar hardcoded em lugar nenhum) e que o módulo de credencial não
escreve em arquivo.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from ponte_openrouter import catalogo, seletor, autorizacao, contexto, executor, credencial


MODULOS = [catalogo, seletor, autorizacao, contexto, executor, credencial]

PADROES_SUSPEITOS = [
    re.compile(r"sk-or-[a-zA-Z0-9]{10,}"),  # formato típico de chave OpenRouter
    re.compile(r"OPENROUTER_API_KEY\s*=\s*['\"][^'\"]+['\"]"),  # chave hardcoded
]


def test_nenhum_padrao_de_chave_no_codigo_fonte():
    for modulo in MODULOS:
        codigo_fonte = inspect.getsource(modulo)
        for padrao in PADROES_SUSPEITOS:
            assert not padrao.search(codigo_fonte), (
                f"Padrão suspeito de chave encontrado em {modulo.__name__}"
            )


def test_credencial_nao_escreve_em_arquivo():
    """O módulo credencial.py não deve conter nenhuma chamada de escrita em
    arquivo (open(..., 'w'), Path.write_text, etc.) - a chave só pode
    existir em memória, no retorno da função."""
    codigo_fonte = inspect.getsource(credencial)
    padroes_escrita = ["open(", "write_text", "write(", "json.dump"]
    for padrao in padroes_escrita:
        assert padrao not in codigo_fonte, f"credencial.py contém possível escrita em arquivo: '{padrao}'"


def test_pasta_logs_nao_contem_arquivos_de_segredo():
    """Verifica a pasta logs/ do projeto (se existir) em busca de qualquer
    arquivo cujo nome sugira segredo - reforço do .gitignore."""
    pasta_logs = Path(__file__).resolve().parent.parent / "logs"
    if not pasta_logs.exists():
        return
    for arquivo in pasta_logs.rglob("*"):
        nome = arquivo.name.lower()
        for termo in ("secret", "credential", "token", "key"):
            assert termo not in nome, f"Arquivo suspeito encontrado em logs/: {arquivo}"
