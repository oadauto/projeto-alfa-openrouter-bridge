"""Guarda de governança dos workflows do GitHub Actions (.github/workflows).

Só lê os arquivos YAML (pyyaml já é dependência do projeto): nenhuma rede,
nenhuma credencial. Garante que os workflows continuam sem segredos, com
permissão mínima e sem comandos que imprimam ambiente, prompts, respostas ou
conteúdo de logs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parent.parent
WORKFLOWS = RAIZ / ".github" / "workflows"
ARQUIVOS = sorted(WORKFLOWS.glob("*.yml"))

PROIBIDO_EM_COMANDOS = re.compile(
    r"(\bset\s+-x\b|\becho\b|\bprintenv\b|\bGet-ChildItem\s+env\b|\bcat\b|\btype\b|\bGet-Content\b"
    r"|\blogs[\\/]|\.jsonl\b|catalogo|executar_orquestrador|openrouter\.ai)",
    re.IGNORECASE,
)


def _carregar(caminho: Path) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def _gatilhos(doc: dict) -> dict:
    return doc.get("on", doc.get(True)) or {}


def _passos(doc: dict):
    for job in doc["jobs"].values():
        yield from job.get("steps", [])


def test_existem_os_dois_workflows_esperados():
    assert {a.name for a in ARQUIVOS} >= {"ci.yml", "seguranca.yml"}


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_permissao_minima_e_sem_gatilhos_perigosos(arquivo):
    doc = _carregar(arquivo)
    assert doc["permissions"] == {"contents": "read"}
    gatilhos = _gatilhos(doc)
    assert "pull_request_target" not in gatilhos and "workflow_run" not in gatilhos
    for job in doc["jobs"].values():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}
        assert job.get("timeout-minutes")


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_nao_usa_segredos_nem_publica_artefatos(arquivo):
    doc = _carregar(arquivo)
    texto = json.dumps(doc)  # sem comentários: só o que o GitHub executa
    assert "secrets." not in texto and "secrets[" not in texto
    assert "upload-artifact" not in texto and "OPENROUTER" not in texto.upper()
    for passo in _passos(doc):
        if "uses" in passo and passo["uses"].startswith("actions/checkout"):
            assert passo["with"]["persist-credentials"] is False


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_comandos_nao_imprimem_ambiente_prompts_respostas_ou_logs(arquivo):
    for passo in _passos(_carregar(arquivo)):
        comando = passo.get("run", "")
        assert not PROIBIDO_EM_COMANDOS.search(comando), comando


def test_ci_roda_pytest_sem_flags_que_vazam_saida():
    doc = _carregar(WORKFLOWS / "ci.yml")
    comandos = [p["run"] for p in _passos(doc) if "pytest" in p.get("run", "")]
    assert len(comandos) == 1
    cmd = comandos[0]
    assert "--show-capture=no" in cmd and "--tb=short" in cmd
    assert not re.search(r"(\s-s\b|\s-v+\b|--showlocals|--log-cli)", cmd)
    assert "tests" in cmd


def test_seguranca_roda_o_verificador_e_o_historico_do_pr():
    doc = _carregar(WORKFLOWS / "seguranca.yml")
    comandos = [p["run"] for p in _passos(doc) if "run" in p]
    assert any("scripts/verificar_segredos.py" in c and "--historico" not in c for c in comandos)
    assert any("--historico" in c for c in comandos)
    # base_ref passa por variável de ambiente (não interpolado direto no shell)
    assert all("github.base_ref" not in c for c in comandos)
