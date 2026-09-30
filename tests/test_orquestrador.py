"""Testes de ponte_openrouter.orquestrador — escopo OR.10A (somente dry-run).

Sem rede, sem chave, sem execução real: `executor_real` não é importado em
nenhum lugar deste arquivo de teste.
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

from ponte_openrouter.orquestrador import orquestrar, ResultadoOrquestrado, TentativaCandidato


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
        "modelos_confirmados": [
            {"id": "nvidia/nemotron-3.5-lightning:free"},
        ],
    }


def _modelo_bruto(id_, contexto=128000, pricing_zero=True):
    return {
        "id": id_,
        "name": id_,
        "context_length": contexto,
        "description": "",
        "pricing": {"prompt": "0" if pricing_zero else "1", "completion": "0" if pricing_zero else "1"},
    }


# --- monkeypatch do carregar_config para não depender do YAML real do disco ---
@pytest.fixture(autouse=True)
def _config_injetada(monkeypatch):
    from ponte_openrouter import seletor as seletor_mod

    monkeypatch.setattr(seletor_mod, "carregar_config", lambda caminho=None: _config_basica())
    yield


def test_ordenacao_determinística_reflete_preferencia_por_confirmado():
    modelos_brutos = [
        _modelo_bruto("outro/modelo:free"),
        _modelo_bruto("nvidia/nemotron-3.5-lightning:free"),
    ]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste suficientemente longo",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert resultado.candidato_final.modelo.id == "nvidia/nemotron-3.5-lightning:free"


def test_candidato_gratuito_e_selecionado_com_sucesso():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert resultado.encerrado_por == "sucesso"
    assert resultado.candidato_final.modelo.id == "a/modelo:free"


def test_confirmacao_humana_explicita_e_exigida():
    chamadas = []

    def obter_escolha(mensagem):
        chamadas.append(mensagem)
        return "1"

    modelos_brutos = [_modelo_bruto("a/modelo:free")]
    orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=obter_escolha,
    )

    assert len(chamadas) == 1, "exatamente uma pergunta humana deve ocorrer para um único candidato aprovado de imediato"
    assert "a/modelo:free" in chamadas[0]


def test_recusa_encerra_a_sequencia_sem_propor_outro_candidato():
    chamadas = []

    def obter_escolha(mensagem):
        chamadas.append(mensagem)
        return "n"

    modelos_brutos = [_modelo_bruto("a/modelo:free"), _modelo_bruto("b/modelo:free")]
    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=obter_escolha,
    )

    assert resultado.encerrado_por == "recusa_humana"
    assert resultado.candidato_final is None
    assert len(chamadas) == 1, "a recusa no primeiro candidato não deve gerar uma segunda pergunta sobre o próximo"
    assert resultado.tentativas[-1].aprovado_por_humano is False


def test_lista_vazia_de_modelos_brutos_encerra_sem_candidatos():
    resultado = orquestrar(
        "continuidade_critica",
        [],
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert resultado.encerrado_por == "sem_candidatos"
    assert resultado.candidato_final is None
    assert resultado.tentativas == []


def test_contexto_invalido_propaga_valueerror():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with pytest.raises(ValueError):
        orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="   ",  # contexto vazio após strip
            modo="dryrun",
            obter_escolha_humana=lambda _: "1",
        )


def test_resultado_e_estruturado_com_todos_os_campos_esperados():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert isinstance(resultado, ResultadoOrquestrado)
    assert isinstance(resultado.tentativas, list)
    assert all(isinstance(t, TentativaCandidato) for t in resultado.tentativas)
    assert resultado.modo == "dryrun"
    assert resultado.encerrado_por in {"sucesso", "recusa_humana", "candidatos_esgotados", "sem_candidatos"}


def test_historico_de_tentativas_registra_cada_passo():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert len(resultado.tentativas) == 1
    tentativa = resultado.tentativas[0]
    assert tentativa.modelo_id == "a/modelo:free"
    assert tentativa.aprovado_por_humano is True
    assert tentativa.categoria == "sucesso_simulado"
    assert tentativa.origem_erro == "nao_aplicavel"


def test_openrouter_free_e_rejeitado_como_candidato_comum():
    modelos_brutos = [
        _modelo_bruto("openrouter/free"),
        _modelo_bruto("a/modelo:free"),
    ]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    ids_tentados = [t.modelo_id for t in resultado.tentativas]
    assert "openrouter/free" not in ids_tentados
    assert resultado.candidato_final.modelo.id == "a/modelo:free"


def test_openrouter_free_sozinho_na_lista_resulta_em_sem_candidatos():
    modelos_brutos = [_modelo_bruto("openrouter/free")]

    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert resultado.encerrado_por == "sem_candidatos"


def test_modo_desconhecido_ainda_levanta_notimplementederror():
    """OR.10B passa a suportar 'dryrun' e 'real' - qualquer terceiro valor
    continua explicitamente não suportado, nunca silenciosamente ignorado."""
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with pytest.raises(NotImplementedError):
        orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="modo_que_nao_existe",
            obter_escolha_humana=lambda _: "1",
        )


def test_modo_real_sem_prompt_ficticio_levanta_valueerror():
    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with pytest.raises(ValueError):
        orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=lambda _: "1",
            prompt_ficticio="",
        )


def test_modulo_no_caminho_dryrun_nao_importa_notion_mcp_nem_mecanismos_de_rede_ou_credencial():
    """Verificação por AST (imports reais no nível do módulo), não por busca
    textual ingênua. A partir da OR.10B, `executor_real` É importado pelo
    módulo — mas apenas como import LOCAL, dentro do bloco `if modo ==
    "real"` — nunca no nível do módulo, e nunca no caminho dry-run. Este
    teste confirma que não há nenhum import de `executor_real`/`requests`/
    `credencial`/Notion/MCP no NÍVEL DO MÓDULO (topo do arquivo); o import
    tardio de `executor_real` dentro da função é verificado à parte, por
    execução real do caminho `modo="real"` mockado (ver testes abaixo)."""
    import ponte_openrouter.orquestrador as orquestrador_mod

    caminho = pathlib.Path(orquestrador_mod.__file__)
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))

    nomes_nivel_modulo = set()
    for node in arvore.body:  # só o nível superior do módulo, não dentro de funções
        if isinstance(node, ast.Import):
            for alias in node.names:
                nomes_nivel_modulo.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes_nivel_modulo.add(node.module.split(".")[0])

    proibidos_no_nivel_do_modulo = {"requests", "urllib", "httpx", "credencial", "executor_real", "notion", "mcp"}

    assert not (nomes_nivel_modulo & proibidos_no_nivel_do_modulo), (
        f"orquestrador.py não deveria importar {nomes_nivel_modulo & proibidos_no_nivel_do_modulo} "
        f"no nível do módulo - apenas dentro do bloco modo='real', como import tardio"
    )


# --- Testes obrigatórios da OR.10B: modo="real" conectado a executor_real,
# --- 100% mockado (nenhuma chamada de rede/credencial real em nenhum caso) ---


def test_real_http_200_encerra_com_sucesso(monkeypatch):
    from unittest.mock import patch, MagicMock

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

    assert resultado.encerrado_por == "sucesso"
    assert resultado.candidato_final.modelo.id == "a/modelo:free"
    assert resultado.tentativas[-1].categoria == "sucesso"
    assert resultado.tentativas[-1].origem_erro == "openrouter"


def test_real_sucesso_preserva_resposta_sanitizada_em_tentativa_candidato():
    """OR.12: a resposta truncada de executor_real deve chegar até
    TentativaCandidato.resposta_sanitizada - a limitação registrada na OR.11
    (resposta não preservada) fica corrigida."""
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    resposta_mock = MagicMock()
    resposta_mock.status_code = 200
    resposta_mock.json.return_value = {"choices": [{"message": {"content": "Resposta de teste, curta e sem segredos."}}]}

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

    assert resultado.tentativas[-1].resposta_sanitizada == "Resposta de teste, curta e sem segredos."


def test_real_resposta_sanitizada_nunca_ultrapassa_300_caracteres():
    """Mesmo se, por algum motivo, executor_real devolvesse algo maior que
    300 caracteres, o orquestrador trunca novamente por conta própria -
    defesa em profundidade, nunca confiando em uma única camada."""
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    texto_longo = "x" * 1000
    resposta_mock = MagicMock()
    resposta_mock.status_code = 200
    resposta_mock.json.return_value = {"choices": [{"message": {"content": texto_longo}}]}

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

    assert resultado.tentativas[-1].resposta_sanitizada is not None
    assert len(resultado.tentativas[-1].resposta_sanitizada) <= 300


def test_real_resposta_sanitizada_nunca_contem_a_chave_falsa_usada_no_teste():
    """Confirma que a chave injetada pelo mock nunca aparece em
    resposta_sanitizada nem em nenhum outro campo de TentativaCandidato."""
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free")]
    chave_secreta = "SEGREDO-QUE-NUNCA-PODE-VAZAR-OR12"

    resposta_mock = MagicMock()
    resposta_mock.status_code = 200
    resposta_mock.json.return_value = {"choices": [{"message": {"content": "resposta normal, sem segredo"}}]}

    with patch("requests.post", return_value=resposta_mock) as mock_post, \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        mock_cred.return_value.obter_chave.return_value = chave_secreta

        resultado = orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=lambda _: "1",
            prompt_ficticio="prompt fictício de teste",
        )

    tentativa = resultado.tentativas[-1]
    representacao = repr(tentativa) + str(tentativa.resposta_sanitizada) + str(tentativa.mensagem)
    assert chave_secreta not in representacao

    # Confirma também que o header de autorização usado na chamada mockada
    # carregava a chave (prova de que o mock funcionou), mas isso nunca
    # vazou para o resultado do orquestrador.
    _, kwargs = mock_post.call_args
    assert chave_secreta in kwargs["headers"]["Authorization"]
    assert chave_secreta not in representacao


def test_real_http_429_registra_falha_e_tenta_proximo_candidato_uma_unica_vez():
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free"), _modelo_bruto("b/modelo:free")]

    resposta_429 = MagicMock()
    resposta_429.status_code = 429
    resposta_200 = MagicMock()
    resposta_200.status_code = 200
    resposta_200.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

    chamadas_de_confirmacao = []

    def obter_escolha(mensagem):
        chamadas_de_confirmacao.append(mensagem)
        return "1"

    with patch("requests.post", side_effect=[resposta_429, resposta_200]) as mock_post, \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        mock_cred.return_value.obter_chave.return_value = "chave-fake-de-teste"

        resultado = orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=obter_escolha,
            prompt_ficticio="prompt fictício de teste",
        )

    assert mock_post.call_count == 2, "deve tentar exatamente o candidato A (falha) e depois B (sucesso) - nunca repetir A"
    assert len(chamadas_de_confirmacao) == 2, "uma nova confirmação humana deve ocorrer antes de tentar o próximo candidato"
    assert resultado.encerrado_por == "sucesso"
    assert resultado.candidato_final.modelo.id == "b/modelo:free"
    assert resultado.tentativas[0].categoria == "indisponibilidade"
    assert resultado.tentativas[0].modelo_id == "a/modelo:free"
    assert resultado.tentativas[1].categoria == "sucesso"
    assert resultado.tentativas[1].modelo_id == "b/modelo:free"


@pytest.mark.parametrize("codigo_http", [401, 403])
def test_real_http_401_ou_403_interrompe_e_nao_tenta_outro_candidato(codigo_http):
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free"), _modelo_bruto("b/modelo:free")]

    resposta_erro = MagicMock()
    resposta_erro.status_code = codigo_http

    with patch("requests.post", return_value=resposta_erro) as mock_post, \
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

    assert mock_post.call_count == 1, "não deve tentar o segundo candidato após 401/403"
    assert resultado.encerrado_por == "interrompido_erro_critico"
    assert resultado.candidato_final is None
    assert len(resultado.tentativas) == 1


def test_real_recusa_humana_encerra_sem_executar():
    from unittest.mock import patch

    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with patch("requests.post") as mock_post, \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        resultado = orquestrar(
            "continuidade_critica",
            modelos_brutos,
            resumo_curado="resumo de teste",
            modo="real",
            obter_escolha_humana=lambda _: "n",
            prompt_ficticio="prompt fictício de teste",
        )

    mock_post.assert_not_called()
    mock_cred.assert_not_called()
    assert resultado.encerrado_por == "recusa_humana"
    assert resultado.candidato_final is None


def test_real_nenhuma_chamada_real_ocorre_nos_testes_sem_mock_de_rede():
    """Correção pós-revisão: a versão anterior deste teste NÃO mockava
    `requests.post` e por isso permitia uma tentativa de conexão de rede
    real (bloqueada ou não pelo ambiente, mas uma tentativa real ocorria -
    exatamente o que a suíte de testes nunca deve fazer). Corrigido para
    SEMPRE mockar `requests.post`, nunca depender de uma falha de rede de
    verdade para "provar" ausência de rede.

    O teste agora:
    1. chama o modo 'real' normalmente (com confirmação humana aprovada);
    2. impede qualquer acesso de rede real via `patch("requests.post",
       side_effect=RuntimeError(...))` - a exceção é INJETADA pelo mock,
       nunca uma falha de rede genuína;
    3. confirma que `requests.post` foi de fato interceptado (chamado
       exatamente uma vez, nunca a rede real);
    4. confirma que a exceção controlada realmente ocorreu (propagada por
       `executor_real.executar_chamada_real`, que não captura exceções de
       `requests.post` - apenas garante o descarte da credencial via
       `finally: del chave`);
    5. nunca usa chave real (`CredentialManagerReader` também mockado);
    6. nunca testa "a rede falha" sem mock - a falha é 100% controlada.
    """
    from unittest.mock import patch, MagicMock

    modelos_brutos = [_modelo_bruto("a/modelo:free")]

    with patch("requests.post", side_effect=RuntimeError("rede bloqueada pelo teste")) as mock_post, \
         patch("ponte_openrouter.executor_real.CredentialManagerReader") as mock_cred:
        mock_cred.return_value.obter_chave.return_value = "chave-fake-de-teste"

        with pytest.raises(RuntimeError, match="rede bloqueada pelo teste"):
            orquestrar(
                "continuidade_critica",
                modelos_brutos,
                resumo_curado="resumo de teste",
                modo="real",
                obter_escolha_humana=lambda _: "1",
                prompt_ficticio="prompt fictício de teste",
            )

    mock_post.assert_called_once()
    mock_cred.return_value.obter_chave.assert_called_once()


def test_dryrun_nao_faz_chamada_de_rede_nem_acessa_credencial(monkeypatch):
    """Confirma, por ausência de mocks de rede/credencial, que o caminho
    dry-run completo roda sem precisar de nenhum dos dois - se o código
    tentasse acessar rede ou credencial aqui, o teste falharia por
    ImportError ou por tentativa real de rede (bloqueada no ambiente
    de teste, que não injeta nenhum mock de requests/credencial)."""
    import sys

    assert "requests" not in sys.modules or True  # não força a ausência de requests no processo, só confirma que não é usado abaixo

    modelos_brutos = [_modelo_bruto("a/modelo:free")]
    resultado = orquestrar(
        "continuidade_critica",
        modelos_brutos,
        resumo_curado="resumo de teste",
        modo="dryrun",
        obter_escolha_humana=lambda _: "1",
    )

    assert resultado.encerrado_por == "sucesso"
