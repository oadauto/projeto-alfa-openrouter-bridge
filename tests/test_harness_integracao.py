"""Testes da integração mínima entre orquestrador.py e harness_contrato.py
— Fase 2.

Exatamente os 6 testes essenciais exigidos, somente estes:
1. integração dry-run com resultado sanitizado
2. bloqueio de modo real sem aprovação humana
3. preservação de categoria e origem de erro
4. fallback explicitamente registrado
5. resposta limitada a 300 caracteres
6. confirmação de que nenhum segredo aparece no resultado

Somente mocks; nenhuma chamada de rede real e nenhuma credencial real.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from ponte_openrouter.orquestrador import (
    executar_via_contrato,
    sanitizar_resultado,
    ResultadoOrquestrado,
    TentativaCandidato,
)
from ponte_openrouter.harness_contrato import ResultadoSanitizado, AprovacaoAusenteError
from ponte_openrouter.seletor import Candidato


def _config_basica() -> dict:
    return {
        "tarefas": {
            "continuidade_critica": {
                "criterios": [
                    {"preferir_confirmados": True},
                    {"multimodal": False},
                    {"contexto_minimo": 100000},
                ]
            }
        },
        "modelos_confirmados": [{"id": "nvidia/nemotron-3.5-lightning:free"}],
    }


def _modelo_bruto(id_, contexto=128000):
    return {
        "id": id_,
        "name": id_,
        "context_length": contexto,
        "description": "",
        "pricing": {"prompt": "0", "completion": "0"},
    }


@pytest.fixture(autouse=True)
def _config_injetada(monkeypatch):
    from ponte_openrouter import seletor as seletor_mod

    monkeypatch.setattr(seletor_mod, "carregar_config", lambda caminho=None: _config_basica())
    yield


# 1. integração dry-run com resultado sanitizado
def test_dryrun_via_contrato_retorna_resultado_sanitizado():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = executar_via_contrato(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert isinstance(resultado, ResultadoSanitizado)
    assert resultado.categoria == "sucesso_simulado"
    assert resultado.modelo == "a/modelo:free"
    assert resultado.numero_tentativas == 1


# 2. bloqueio de modo real sem aprovação humana
def test_modo_real_sem_aprovacao_humana_e_bloqueado_antes_de_orquestrar():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with patch("ponte_openrouter.orquestrador.orquestrar") as mock_orquestrar:
        with pytest.raises(AprovacaoAusenteError):
            executar_via_contrato(
                "continuidade_critica",
                modelos_brutos,
                resumo_curado="resumo de teste",
                modo="real",
                prompt_ficticio="prompt de teste",
                aprovado_por_humano=False,
            )
        mock_orquestrar.assert_not_called()


# 3. preservação de categoria e origem de erro
def test_sanitizar_resultado_preserva_categoria_e_origem_de_erro():
    resultado_orquestrado = ResultadoOrquestrado(
        tentativas=[
            TentativaCandidato(
                modelo_id="a/modelo:free",
                origem_erro="openrouter",
                categoria="indisponibilidade",
                aprovado_por_humano=True,
                mensagem="HTTP 429",
            )
        ],
        candidato_final=None,
        encerrado_por="interrompido_erro_critico",
        modo="real",
    )

    resultado = sanitizar_resultado(resultado_orquestrado)

    assert resultado.categoria == "indisponibilidade"
    assert resultado.origem_erro == "openrouter"


# 4. fallback explicitamente registrado
def test_fallback_e_registrado_explicitamente_quando_ha_mais_de_uma_tentativa():
    resultado_orquestrado = ResultadoOrquestrado(
        tentativas=[
            TentativaCandidato(
                modelo_id="a/modelo:free",
                origem_erro="openrouter",
                categoria="indisponibilidade",
                aprovado_por_humano=True,
                mensagem="HTTP 429",
            ),
            TentativaCandidato(
                modelo_id="b/modelo:free",
                origem_erro="openrouter",
                categoria="sucesso",
                aprovado_por_humano=True,
                mensagem="HTTP 200",
                resposta_sanitizada="ok",
            ),
        ],
        candidato_final=None,
        encerrado_por="sucesso",
        modo="real",
    )

    resultado = sanitizar_resultado(resultado_orquestrado)

    assert resultado.fallback_utilizado is True
    assert resultado.numero_tentativas == 2

    # e o inverso: uma única tentativa nunca é reportada como fallback
    resultado_unico = sanitizar_resultado(
        ResultadoOrquestrado(
            tentativas=[resultado_orquestrado.tentativas[0]],
            candidato_final=None,
            encerrado_por="interrompido_erro_critico",
            modo="real",
        )
    )
    assert resultado_unico.fallback_utilizado is False


# 5. resposta limitada a 300 caracteres
def test_resposta_sanitizada_e_limitada_a_300_caracteres():
    resposta_longa = "y" * 500
    resultado_orquestrado = ResultadoOrquestrado(
        tentativas=[
            TentativaCandidato(
                modelo_id="a/modelo:free",
                origem_erro="openrouter",
                categoria="sucesso",
                aprovado_por_humano=True,
                mensagem="HTTP 200",
                resposta_sanitizada=resposta_longa,
            )
        ],
        candidato_final=None,
        encerrado_por="sucesso",
        modo="real",
    )

    resultado = sanitizar_resultado(resultado_orquestrado)

    assert resultado.resposta is not None
    assert len(resultado.resposta) == 300


# 6. confirmação de que nenhum segredo aparece no resultado
def test_resultado_sanitizado_da_integracao_nunca_contem_segredo():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = executar_via_contrato(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    campos = set(resultado.__dataclass_fields__)
    termos_proibidos = {"chave", "token", "senha", "credencial", "authorization", "api_key", "secret"}
    assert not (campos & termos_proibidos)

    valores_textuais = [str(v).lower() for v in (resultado.modelo, resultado.resposta, resultado.categoria, resultado.origem_erro)]
    for termo in termos_proibidos:
        assert not any(termo in v for v in valores_textuais)
