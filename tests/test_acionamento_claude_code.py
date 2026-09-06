"""Confirma, por inspeção do código-fonte, que o script de acionamento pelo
Claude Code não pode tocar a chave real, fazer chamadas de rede, nem
acessar o Notion — e que o fluxo dry-run subjacente também respeita isso.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path


CAMINHO_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "acionamento_claude_code.py"

IMPORTS_PROIBIDOS = [
    "import requests",
    "import urllib",
    "import httpx",
    "from ponte_openrouter import credencial",
    "from ponte_openrouter.credencial",
    "from ponte_openrouter import executor_real",
    "from ponte_openrouter.executor_real",
    "import notion",
    "notion_client",
]


def _carregar_codigo_fonte_do_script() -> str:
    return CAMINHO_SCRIPT.read_text(encoding="utf-8")


def test_arquivo_existe():
    assert CAMINHO_SCRIPT.exists(), "scripts/acionamento_claude_code.py não encontrado"


def test_nenhum_import_proibido_no_script():
    codigo_fonte = _carregar_codigo_fonte_do_script()
    for proibido in IMPORTS_PROIBIDOS:
        assert proibido not in codigo_fonte, f"Import proibido encontrado: '{proibido}'"


def test_nao_referencia_credential_manager_nem_chave():
    codigo_fonte = _carregar_codigo_fonte_do_script()
    termos_proibidos = ["OPENROUTER_API_KEY", "CredentialManagerReader", "Get-StoredCredential"]
    for termo in termos_proibidos:
        assert termo not in codigo_fonte, f"Referência proibida encontrada: '{termo}'"


def test_nao_escreve_arquivo_de_log():
    codigo_fonte = _carregar_codigo_fonte_do_script()
    padroes_escrita = ["open(", "write_text", "logging.FileHandler", "json.dump"]
    for padrao in padroes_escrita:
        assert padrao not in codigo_fonte, f"Possível escrita em arquivo encontrada: '{padrao}'"


def test_usa_catalogo_ficticio_embutido():
    codigo_fonte = _carregar_codigo_fonte_do_script()
    assert "CATALOGO_FICTICIO" in codigo_fonte
    assert "openrouter.ai" not in codigo_fonte.lower()


def test_exige_confirmacao_humana():
    codigo_fonte = _carregar_codigo_fonte_do_script()
    assert "obter_escolha_humana" in codigo_fonte
    assert "input(" in codigo_fonte


def test_fluxo_dry_run_subjacente_tambem_nao_faz_chamada_real():
    """Reforço: o próprio dry_run.py (já usado por este script) não importa
    bibliotecas de rede nem credencial - isso já é coberto por
    test_seguranca_logs.py, mas repetido aqui no contexto específico do
    acionamento pelo Claude Code."""
    from ponte_openrouter import dry_run

    codigo_fonte = inspect.getsource(dry_run)
    for proibido in ("import requests", "import urllib", "import httpx", "credencial", "executor_real"):
        assert proibido not in codigo_fonte
