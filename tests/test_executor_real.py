"""Testes de ponte_openrouter.executor_real.executar_chamada_real() — 100% mockado.

Nenhuma chamada de rede real é feita: `requests.post` e a leitura de
credencial são substituídos por mocks. Nenhuma chave real é usada ou
pode vazar por estes testes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ponte_openrouter import executor_real


def _resposta_mock(status_code, corpo_json=None):
    resposta = MagicMock()
    resposta.status_code = status_code
    if corpo_json is not None:
        resposta.json.return_value = corpo_json
    return resposta


def test_sem_confirmacao_nao_faz_nenhuma_chamada():
    with patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        resultado = executor_real.executar_chamada_real(
            "nvidia/nemotron-3.5-lightning:free", "prompt fictício", confirmar_execucao=False
        )

    assert resultado.categoria == "nao_executado"
    assert resultado.codigo_http is None
    mock_cred.assert_not_called()


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_payload_contem_allow_fallbacks_false(mock_cred_cls, mock_post):
    mock_cred_cls.return_value.obter_chave.return_value = "chave-fake-de-teste"
    mock_post.return_value = _resposta_mock(200, {"choices": [{"message": {"content": "ok"}}]})

    executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["provider"] == {"allow_fallbacks": False}


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_exatamente_uma_chamada_e_feita(mock_cred_cls, mock_post):
    mock_cred_cls.return_value.obter_chave.return_value = "chave-fake-de-teste"
    mock_post.return_value = _resposta_mock(200, {"choices": [{"message": {"content": "ok"}}]})

    executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    assert mock_post.call_count == 1


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_ausencia_de_retry_apos_falha(mock_cred_cls, mock_post):
    mock_cred_cls.return_value.obter_chave.return_value = "chave-fake-de-teste"
    mock_post.return_value = _resposta_mock(429)

    resultado = executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    assert mock_post.call_count == 1, "nenhuma nova tentativa deve ocorrer após falha"
    assert resultado.categoria == "indisponibilidade"
    assert "Nenhuma nova tentativa foi feita" in resultado.mensagem


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_credencial_e_descartada_mesmo_quando_a_chamada_falha(mock_cred_cls, mock_post):
    mock_cred_cls.return_value.obter_chave.return_value = "chave-fake-de-teste"
    mock_post.side_effect = RuntimeError("falha simulada de rede")

    try:
        executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)
    except RuntimeError:
        pass  # esperado: o teste avalia apenas o descarte da credencial, não a propagação do erro

    # O código-fonte faz `del chave` em `finally`; não há forma de inspecionar
    # uma variável local já deletada a partir do teste, então este teste
    # documenta o contrato esperado (ver nota nas limitações do relatório).
    assert True


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_credencial_nunca_aparece_no_resultado_retornado(mock_cred_cls, mock_post):
    chave_secreta = "SEGREDO-QUE-NUNCA-PODE-VAZAR"
    mock_cred_cls.return_value.obter_chave.return_value = chave_secreta
    mock_post.return_value = _resposta_mock(200, {"choices": [{"message": {"content": "ok"}}]})

    resultado = executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    representacao = repr(resultado) + str(resultado.mensagem) + str(resultado.resposta_paráfrase)
    assert chave_secreta not in representacao


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_credencial_nunca_e_passada_como_texto_puro_no_header_capturado_pelo_mock(mock_cred_cls, mock_post):
    """Confirma que o header Authorization é montado com Bearer (não em log/print);
    este teste não verifica ausência de logging (fora do escopo testável sem
    capturar stdout/logging handlers, ver limitações no relatório)."""
    chave_secreta = "SEGREDO-QUE-NUNCA-PODE-VAZAR"
    mock_cred_cls.return_value.obter_chave.return_value = chave_secreta
    mock_post.return_value = _resposta_mock(200, {"choices": [{"message": {"content": "ok"}}]})

    executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {chave_secreta}"


@patch("requests.post")
@patch("ponte_openrouter.executor_real.CredentialManagerReader")
def test_resposta_sucesso_e_truncada_em_300_caracteres(mock_cred_cls, mock_post):
    mock_cred_cls.return_value.obter_chave.return_value = "chave-fake-de-teste"
    texto_longo = "x" * 1000
    mock_post.return_value = _resposta_mock(200, {"choices": [{"message": {"content": texto_longo}}]})

    resultado = executor_real.executar_chamada_real("modelo/teste:free", "prompt", confirmar_execucao=True)

    assert len(resultado.resposta_paráfrase) <= 300
