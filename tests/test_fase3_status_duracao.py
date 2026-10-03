"""Testes da Fase 3 — propagação de status_http e duracao_segundos.

Exatamente os 4 testes mínimos exigidos, somente estes:
1. sucesso real mockado: status_http e duracao_segundos preservados;
2. dry-run: ambos permanecem None;
3. erro real mockado (429): ambos preservados também no caminho de erro;
4. TentativaCandidato continua podendo ser construído sem os novos campos
   (compatibilidade retroativa).

Somente mocks; nenhuma chamada de rede real e nenhuma credencial real.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from ponte_openrouter.orquestrador import orquestrar, sanitizar_resultado, TentativaCandidato


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


# 1. sucesso real mockado com HTTP 200
def test_sucesso_real_preserva_status_http_e_duracao_segundos():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resposta_mock = MagicMock()
    resposta_mock.status_code = 200
    resposta_mock.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    with patch("requests.post", return_value=resposta_mock), \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        mock_cred.return_value.obter_chave.return_value = "chave-fake-de-teste"

        resultado = orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=lambda _: "1",
            prompt_ficticio="prompt fictício de teste",
        )

    tentativa = resultado.tentativas[-1]
    assert tentativa.status_http == 200
    assert tentativa.duracao_segundos is not None
    assert tentativa.duracao_segundos >= 0.0

    sanitizado = sanitizar_resultado(resultado)
    assert sanitizado.status_http == 200
    assert sanitizado.duracao_segundos is not None


# 2. dry-run: ambos permanecem None
def test_dryrun_mantem_status_http_e_duracao_segundos_como_none():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    tentativa = resultado.tentativas[-1]
    assert tentativa.status_http is None
    assert tentativa.duracao_segundos is None

    sanitizado = sanitizar_resultado(resultado)
    assert sanitizado.status_http is None
    assert sanitizado.duracao_segundos is None


# 3. erro real mockado (429): ambos preservados
def test_erro_real_429_preserva_status_http_e_duracao_segundos():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resposta_mock = MagicMock()
    resposta_mock.status_code = 429

    with patch("requests.post", return_value=resposta_mock), \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        mock_cred.return_value.obter_chave.return_value = "chave-fake-de-teste"

        resultado = orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=lambda _: "1",
            prompt_ficticio="prompt fictício de teste",
        )

    tentativa = resultado.tentativas[-1]
    assert tentativa.status_http == 429
    assert tentativa.duracao_segundos is not None
    assert tentativa.categoria == "indisponibilidade"


# 4. TentativaCandidato continua podendo ser construído sem os novos campos
def test_tentativa_candidato_mantem_compatibilidade_sem_novos_campos():
    tentativa = TentativaCandidato(
        modelo_id="a/modelo:free",
        origem_erro="nao_aplicavel",
        categoria="sucesso_simulado",
        aprovado_por_humano=True,
        mensagem="mensagem de teste",
    )

    assert tentativa.status_http is None
    assert tentativa.duracao_segundos is None
