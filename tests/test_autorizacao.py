"""Testes de ponte_openrouter.autorizacao.confirmar().

`obter_escolha_humana` é sempre injetado nestes testes — nunca usa `input()`
real, conforme a própria docstring do módulo pede.
"""
from __future__ import annotations

from ponte_openrouter.catalogo import ModeloCatalogo
from ponte_openrouter.seletor import Candidato
from ponte_openrouter.autorizacao import confirmar


def _candidatos():
    return [
        Candidato(
            modelo=ModeloCatalogo(id="a/modelo-1:free", nome="Modelo 1", contexto=128000, descricao=""),
            pontuacao=3,
            justificativa=["preferido"],
        ),
        Candidato(
            modelo=ModeloCatalogo(id="b/modelo-2:free", nome="Modelo 2", contexto=64000, descricao=""),
            pontuacao=1,
            justificativa=["alternativa"],
        ),
    ]


def test_confirmacao_explicita_autoriza_e_escolhe_candidato_correto():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "1")

    assert decisao.autorizado is True
    assert decisao.candidato_escolhido.modelo.id == "a/modelo-1:free"


def test_recusa_explicita_nao_autoriza():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "n")

    assert decisao.autorizado is False
    assert decisao.candidato_escolhido is None
    assert "não autorizou" in decisao.motivo


def test_escolha_do_segundo_candidato():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "2")

    assert decisao.autorizado is True
    assert decisao.candidato_escolhido.modelo.id == "b/modelo-2:free"


def test_resposta_vazia_e_tratada_como_recusa_nao_como_aprovacao_implicita():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "")

    assert decisao.autorizado is False, (
        "resposta vazia nunca pode ser tratada como aprovação implícita"
    )


def test_resposta_invalida_nao_autoriza_e_nao_quebra():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "texto-invalido")

    assert decisao.autorizado is False
    assert "resposta inválida" in decisao.motivo


def test_indice_fora_do_intervalo_nao_autoriza():
    decisao = confirmar(_candidatos(), obter_escolha_humana=lambda _: "99")

    assert decisao.autorizado is False


def test_lista_vazia_de_candidatos_nunca_autoriza():
    decisao = confirmar([], obter_escolha_humana=lambda _: "1")

    assert decisao.autorizado is False
    assert decisao.candidato_escolhido is None
