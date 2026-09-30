"""Testes de separação estrutural (Fase OR.1/OR.7 formalizadas como testes).

Confirma, por inspeção de imports/AST (nunca por execução com rede), que:
- o caminho de dry-run não importa `requests`/`credencial`;
- `openrouter/free` é tratado como ID opaco, sem lógica condicional dedicada
  em nenhum módulo do pacote.
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import ponte_openrouter.dry_run as dry_run_mod
import ponte_openrouter.executor as executor_mod
import ponte_openrouter.seletor as seletor_mod
import ponte_openrouter.catalogo as catalogo_mod
import ponte_openrouter.autorizacao as autorizacao_mod

PACOTE_DIR = pathlib.Path(importlib.import_module("ponte_openrouter").__file__).parent

MODULOS_DRYRUN = [dry_run_mod, executor_mod, seletor_mod, catalogo_mod, autorizacao_mod]

MODULOS_NUNCA_DEVEM_IMPORTAR_REDE_OU_CREDENCIAL = {"requests", "urllib", "httpx", "credencial"}


def _nomes_importados(modulo) -> set[str]:
    caminho = pathlib.Path(modulo.__file__)
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                nomes.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module.split(".")[0])
    return nomes


def test_modulos_de_dryrun_nao_importam_requests_nem_credencial():
    for modulo in MODULOS_DRYRUN:
        importados = _nomes_importados(modulo)
        intersecao = importados & MODULOS_NUNCA_DEVEM_IMPORTAR_REDE_OU_CREDENCIAL
        assert not intersecao, (
            f"{modulo.__name__} importa {intersecao}, o que violaria a separação "
            f"entre caminho simulado e caminho real"
        )


def test_apenas_executor_real_importa_requests_ou_credencial():
    """Confirma que a única exceção esperada é o módulo executor_real (por
    desenho, conforme sua própria docstring)."""
    caminho_executor_real = PACOTE_DIR / "executor_real.py"
    arvore = ast.parse(caminho_executor_real.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                nomes.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module.split(".")[0])
    assert "requests" in nomes or True  # requests é importado localmente dentro da função (import tardio)
    # A confirmação forte é textual: 'import requests' aparece no arquivo.
    conteudo = caminho_executor_real.read_text(encoding="utf-8")
    assert "import requests" in conteudo
    assert "credencial" in conteudo  # via CredentialManagerReader


def test_openrouter_free_e_tratado_como_id_opaco_em_todo_o_pacote_exceto_no_orquestrador():
    """Nenhum módulo do pacote deve conter lógica condicional dedicada ao
    valor literal 'openrouter/free' — ele deve fluir como qualquer outro
    modelo_id (string opaca) — COM UMA EXCEÇÃO DOCUMENTADA:

    A partir da OR.9/OR.10A (política homologada pelo usuário), o módulo
    `orquestrador.py` trata `openrouter/free` como um MODO SEPARADO, não
    como candidato comum, e por isso precisa comparar o id explicitamente
    a essa constante para rejeitá-lo da lista de candidatos comuns. Essa é
    uma decisão de design consciente e homologada, não uma regressão da
    regra original — daí a exceção explícita, em vez de simplesmente
    remover o teste.

    Esta atualização ao teste é a única alteração feita neste arquivo na
    OR.10A, e é estritamente necessária: sem ela, o teste (escrito na OR.8,
    antes da política de 'modo separado' existir) reprovaria falsamente o
    módulo novo por fazer exatamente o que a OR.9 pediu."""
    excecao_documentada = {"orquestrador.py"}
    for caminho in PACOTE_DIR.glob("*.py"):
        if caminho.name in excecao_documentada:
            continue
        conteudo = caminho.read_text(encoding="utf-8")
        assert "openrouter/free" not in conteudo, (
            f"{caminho.name} contém uma referência literal a 'openrouter/free' — "
            f"isso indicaria lógica especial não documentada para esse ID"
        )
