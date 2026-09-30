"""Testes de ponte_openrouter.executor.classificar_http() e executar_dryrun().

Sem rede: executar_dryrun() nunca chama a rede por definição do próprio
módulo; este teste apenas confirma esse contrato.
"""
from __future__ import annotations

import pytest

from ponte_openrouter.executor import classificar_http, executar_dryrun


@pytest.mark.parametrize(
    "codigo,categoria_esperada",
    [
        (200, "sucesso"),
        (401, "problema_de_credencial"),
        (403, "restricao_de_acesso"),
        (429, "indisponibilidade"),
        (500, "indisponibilidade"),
        (503, "indisponibilidade"),
        (599, "indisponibilidade"),
    ],
)
def test_classificar_http_codigos_mapeados(codigo, categoria_esperada):
    assert classificar_http(codigo) == categoria_esperada


@pytest.mark.parametrize("codigo", [418, 999, 0, -1, 302])
def test_classificar_http_codigo_desconhecido_nao_e_inventado(codigo):
    """Um código fora do mapa e fora da faixa 5xx deve virar 'nao_classificado',
    nunca uma categoria inventada por inferência."""
    assert classificar_http(codigo) == "nao_classificado"


def test_executar_dryrun_nunca_faz_chamada_real_e_retorna_mensagem_simulada():
    resultado = executar_dryrun("qualquer/modelo:free", "contexto de teste")
    assert resultado.modo == "dry-run"
    assert "SIMULAÇÃO" in resultado.mensagem
    assert "Nenhuma chamada real foi feita" in resultado.mensagem


def test_executar_dryrun_rejeita_contexto_minimo_vazio():
    with pytest.raises(ValueError):
        executar_dryrun("qualquer/modelo:free", "")

    with pytest.raises(ValueError):
        executar_dryrun("qualquer/modelo:free", "   ")
