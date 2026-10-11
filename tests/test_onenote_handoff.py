"""Testes minimos do hash e da idempotencia do handoff S-22 (texto FICTICIO)."""
from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import onenote_handoff as oh  # noqa: E402

PID = "0-pagina-ficticia"
MOD = "2026-10-11T12:00:00Z"
TEXTO = "Pagina ficticia de teste.\nSegunda linha com acentuacao: coracao."


def _h(texto):
    return oh.calcular_hash(texto)


def test_sha256_hex_minusculo_de_vetor_conhecido():
    assert _h("abc")["hash"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_formas_equivalentes_geram_o_mesmo_hash():
    base = "café\nlinha dois"
    variantes = [base, base.replace("\n", "\r\n"), "café  \nlinha dois   \n\n",
                 unicodedata.normalize("NFD", base), "﻿" + base]
    assert len({_h(v)["hash"] for v in variantes}) == 1


def test_limite_gera_hash_parcial_e_nunca_igual_ao_completo():
    longo = "a" * (oh.LIMITE_CARACTERES + 5)
    r = _h(longo)
    assert r["truncado"] and r["tipo_hash"] == oh.HASH_PARCIAL
    assert r["caracteres_lidos"] == oh.LIMITE_CARACTERES and r["caracteres_totais"] == len(longo)
    assert _h("a" * oh.LIMITE_CARACTERES)["tipo_hash"] == oh.HASH_COMPLETO


def test_mesmo_hash_atualiza_verificacao_sem_nova_versao():
    h1, a1 = oh.registrar(None, PID, MOD, _h(TEXTO), classificacao="ficticia", agora="2026-10-11T12:01:00Z")
    h2, a2 = oh.registrar(h1, PID, "2026-10-11T13:00:00Z", _h(TEXTO), classificacao="ficticia",
                          agora="2026-10-11T13:01:00Z")
    assert (a1, a2) == ("criado", "verificacao_atualizada")
    assert len(h2["versoes"]) == 1 and h2["ultima_verificacao"] == "2026-10-11T13:01:00Z"
    assert len(h1["versoes"]) == 1 and h1["ultima_verificacao"] == "2026-10-11T12:01:00Z"  # nao muta


def test_hash_diferente_acrescenta_versao_no_mesmo_handoff():
    h1, _ = oh.registrar(None, PID, MOD, _h(TEXTO), classificacao="ficticia")
    h2, acao = oh.registrar(h1, PID, "2026-10-12T09:00:00Z", _h(TEXTO + "\nnova linha"), classificacao="ficticia")
    assert acao == "nova_versao" and h2["identidade"] == h1["identidade"]
    assert [v["hash"] for v in h2["versoes"]][0] == h1["versoes"][0]["hash"] and len(h2["versoes"]) == 2


def test_nao_duplica_e_ambiguidade_para():
    h1, _ = oh.registrar(None, PID, MOD, _h(TEXTO), classificacao="ficticia")
    assert oh.encontrar_handoff([h1], PID) is h1
    assert oh.encontrar_handoff([h1], "outra") is None
    with pytest.raises(oh.HandoffAmbiguo):
        oh.encontrar_handoff([h1, dict(h1)], PID)


def test_datas_sem_fuso_ou_page_id_vazio_sao_recusados():
    with pytest.raises(ValueError):
        oh.normalizar_modificacao("2026-10-11T12:00:00")
    with pytest.raises(ValueError):
        oh.chave_identidade("  ")
    assert oh.normalizar_modificacao("2026-10-11T09:00:00-03:00") == MOD


def test_handoff_e_renderizacao_nunca_contem_o_texto():
    segredo = "TEXTO_BRUTO_UNICO_QUE_NAO_PODE_APARECER"
    h, _ = oh.registrar(None, PID, MOD, _h(segredo + " sk-or-v1-FICTICIA0123456789"), classificacao="ficticia")
    saida = json.dumps(h) + oh.renderizar_handoff(h)
    assert segredo not in saida and "sk-or-v1" not in saida


def test_cli_imprime_so_metadados_e_nao_ecoa_o_texto():
    script = Path(oh.__file__).resolve()
    p = subprocess.run([sys.executable, str(script), "--page-id", PID, "--modified-at", MOD],
                       input=TEXTO.encode("utf-8"), capture_output=True, timeout=30)
    saida = json.loads(p.stdout)
    assert p.returncode == 0 and saida["identidade"] == f"onenote|{PID}" and len(saida["hash"]) == 64
    assert "Pagina ficticia" not in p.stdout.decode("utf-8")
    ruim = subprocess.run([sys.executable, str(script)], input=b"x", capture_output=True, timeout=30)
    assert ruim.returncode == 2
