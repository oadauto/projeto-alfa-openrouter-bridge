"""Testes de ponte_openrouter.seletor.selecionar().

Sem rede, sem chave, sem YAML real: cada teste injeta seu próprio `config`
em memória, para não depender do conteúdo (nem da existência) do arquivo
config/selecao_por_tarefa.yaml.
"""
from __future__ import annotations

import pytest

from ponte_openrouter.catalogo import ModeloCatalogo
from ponte_openrouter.seletor import selecionar


def _config_basica() -> dict:
    return {
        "tarefas": {
            "continuidade_critica": {
                "criterios": [
                    {"preferir_confirmados": True},
                    {"multimodal": False},
                    {"contexto_minimo": 100000},
                ]
            },
            "multimodal": {
                "criterios": [
                    {"multimodal": True},
                    {"contexto_minimo": 200000},
                ]
            },
            "com_provedor_evitado": {
                "criterios": [
                    {"evitar_provedores": ["provedor-ruim"]},
                ]
            },
        },
        "modelos_confirmados": [
            {"id": "nvidia/nemotron-3.5-lightning:free"},
        ],
    }


def _modelo(id_, contexto=128000, multimodal=False, provedor=None):
    return ModeloCatalogo(
        id=id_,
        nome=id_,
        contexto=contexto,
        descricao="",
        multimodal=multimodal,
        provedor=provedor or "",
    )


def test_ordenacao_e_deterministica_para_a_mesma_entrada():
    catalogo = [
        _modelo("a/modelo-1:free", contexto=150000),
        _modelo("nvidia/nemotron-3.5-lightning:free", contexto=150000),
        _modelo("b/modelo-3:free", contexto=50000),
    ]
    config = _config_basica()

    resultado_1 = selecionar("continuidade_critica", catalogo, config=config)
    resultado_2 = selecionar("continuidade_critica", catalogo, config=config)

    ids_1 = [c.modelo.id for c in resultado_1]
    ids_2 = [c.modelo.id for c in resultado_2]
    assert ids_1 == ids_2, "a mesma entrada deve sempre produzir a mesma ordem"


def test_preferencia_por_modelo_confirmado_fica_em_primeiro():
    catalogo = [
        _modelo("outro/modelo:free", contexto=150000),
        _modelo("nvidia/nemotron-3.5-lightning:free", contexto=150000),
    ]
    config = _config_basica()

    resultado = selecionar("continuidade_critica", catalogo, config=config)

    assert resultado[0].modelo.id == "nvidia/nemotron-3.5-lightning:free"
    assert resultado[0].pontuacao > resultado[1].pontuacao


def test_filtro_por_tarefa_aplica_criterios_diferentes_por_tarefa():
    catalogo = [
        _modelo("x/multimodal-alto-contexto:free", contexto=250000, multimodal=True),
        _modelo("y/texto-apenas:free", contexto=250000, multimodal=False),
    ]
    config = _config_basica()

    resultado_multimodal = selecionar("multimodal", catalogo, config=config)
    vencedor = resultado_multimodal[0]

    assert vencedor.modelo.id == "x/multimodal-alto-contexto:free"


def test_tarefa_inexistente_levanta_valueerror():
    catalogo = [_modelo("a/modelo:free")]
    config = _config_basica()

    with pytest.raises(ValueError):
        selecionar("tarefa_que_nao_existe", catalogo, config=config)


def test_provedor_a_evitar_reduz_pontuacao_mas_nao_exclui_candidato():
    catalogo = [
        _modelo("provedor-ruim/modelo:free", provedor="provedor-ruim"),
        _modelo("provedor-ok/modelo:free", provedor="provedor-ok"),
    ]
    config = _config_basica()

    resultado = selecionar("com_provedor_evitado", catalogo, config=config)

    ids = [c.modelo.id for c in resultado]
    assert "provedor-ruim/modelo:free" in ids, "candidato não deve ser excluído, apenas penalizado"
    penalizado = next(c for c in resultado if c.modelo.id == "provedor-ruim/modelo:free")
    normal = next(c for c in resultado if c.modelo.id == "provedor-ok/modelo:free")
    assert penalizado.pontuacao < normal.pontuacao
