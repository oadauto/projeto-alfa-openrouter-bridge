"""Testes do módulo executor_real - todos com rede simulada (nenhuma
chamada real é feita nestes testes)."""

from __future__ import annotations

import sys
import types

import pytest


def test_sem_confirmacao_nao_faz_nada(monkeypatch):
    from ponte_openrouter import executor_real

    resultado = executor_real.executar_chamada_real("qualquer/modelo:free", "prompt fictício")
    assert resultado.categoria == "nao_executado"
    assert resultado.codigo_http is None


def test_com_confirmacao_chama_e_classifica_sucesso(monkeypatch):
    from ponte_openrouter import executor_real, credencial

    class FakeResposta:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "resposta fictícia de teste"}}]}

    class FakeRequestsModule:
        @staticmethod
        def post(url, headers=None, json=None, timeout=None):
            assert "Authorization" in headers
            return FakeResposta()

    monkeypatch.setitem(sys.modules, "requests", FakeRequestsModule)
    monkeypatch.setattr(credencial.CredentialManagerReader, "obter_chave", lambda self, target="ProjetoAlfa-OpenRouter": "chave-ficticia-de-teste")

    resultado = executor_real.executar_chamada_real("modelo/ficticio:free", "prompt fictício", confirmar_execucao=True)

    assert resultado.codigo_http == 200
    assert resultado.categoria == "sucesso"
    assert resultado.resposta_paráfrase == "resposta fictícia de teste"


def test_com_confirmacao_classifica_falha_429(monkeypatch):
    from ponte_openrouter import executor_real, credencial

    class FakeResposta:
        status_code = 429

        def json(self):
            raise AssertionError("json() não deveria ser chamado para uma falha")

    class FakeRequestsModule:
        @staticmethod
        def post(url, headers=None, json=None, timeout=None):
            return FakeResposta()

    monkeypatch.setitem(sys.modules, "requests", FakeRequestsModule)
    monkeypatch.setattr(credencial.CredentialManagerReader, "obter_chave", lambda self, target="ProjetoAlfa-OpenRouter": "chave-ficticia-de-teste")

    resultado = executor_real.executar_chamada_real("modelo/ficticio:free", "prompt fictício", confirmar_execucao=True)

    assert resultado.codigo_http == 429
    assert resultado.categoria == "indisponibilidade"
    assert resultado.resposta_paráfrase is None


def test_chave_nunca_aparece_no_resultado(monkeypatch):
    from ponte_openrouter import executor_real, credencial

    class FakeResposta:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeRequestsModule:
        @staticmethod
        def post(url, headers=None, json=None, timeout=None):
            return FakeResposta()

    chave_secreta_de_teste = "sk-or-chave-ficticia-nao-deve-vazar"
    monkeypatch.setitem(sys.modules, "requests", FakeRequestsModule)
    monkeypatch.setattr(credencial.CredentialManagerReader, "obter_chave", lambda self, target="ProjetoAlfa-OpenRouter": chave_secreta_de_teste)

    resultado = executor_real.executar_chamada_real("modelo/ficticio:free", "prompt fictício", confirmar_execucao=True)

    representacao_completa = str(resultado.__dict__)
    assert chave_secreta_de_teste not in representacao_completa
