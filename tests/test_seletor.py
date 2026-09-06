import pytest

from ponte_openrouter.catalogo import ModeloCatalogo
from ponte_openrouter import seletor


CONFIG_FICTICIA = {
    "tarefas": {
        "analise_geral": {
            "criterios": [{"contexto_minimo": 100000}, {"multimodal": False}],
        },
        "continuidade_critica": {
            "criterios": [{"preferir_confirmados": True}, {"multimodal": False}],
        },
        "com_evitar": {
            "criterios": [{"evitar_provedores": ["provedor-ruim"]}],
        },
    },
    "modelos_confirmados": [{"id": "bom/modelo:free"}],
}


def _catalogo_ficticio():
    return [
        ModeloCatalogo(id="bom/modelo:free", nome="Bom", contexto=200000, descricao="", multimodal=False, provedor="bom"),
        ModeloCatalogo(id="provedor-ruim/modelo:free", nome="Ruim", contexto=50000, descricao="", multimodal=False, provedor="provedor-ruim"),
        ModeloCatalogo(id="neutro/modelo:free", nome="Neutro", contexto=150000, descricao="", multimodal=True, provedor="neutro"),
    ]


def test_tarefa_inexistente_gera_erro_claro():
    with pytest.raises(ValueError, match="não definida"):
        seletor.selecionar("tarefa-que-nao-existe", _catalogo_ficticio(), config=CONFIG_FICTICIA)


def test_prioriza_confirmados():
    candidatos = seletor.selecionar("continuidade_critica", _catalogo_ficticio(), config=CONFIG_FICTICIA)
    assert candidatos[0].modelo.id == "bom/modelo:free"
    assert any("confirmado" in j for j in candidatos[0].justificativa)


def test_penaliza_provedor_a_evitar():
    candidatos = seletor.selecionar("com_evitar", _catalogo_ficticio(), config=CONFIG_FICTICIA)
    por_id = {c.modelo.id: c for c in candidatos}
    assert por_id["provedor-ruim/modelo:free"].pontuacao < 0


def test_justificativa_sempre_presente():
    candidatos = seletor.selecionar("analise_geral", _catalogo_ficticio(), config=CONFIG_FICTICIA)
    assert all(isinstance(c.justificativa, list) for c in candidatos)
