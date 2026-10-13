"""Testes mínimos da integração da continuidade controlada ao harness
(scripts/adaptador_harness.py + scripts/observabilidade.py).

Nenhuma chamada de rede e nenhuma credencial reais: nos caminhos que
alcançariam o OpenRouter, apenas `requests.post` e `CredentialManagerReader`
são substituídos; todo o resto (adaptador, continuidade, executor_real)
roda de verdade. Os caminhos que não chegam ao executor (oferta, recusa,
fluxo anterior) rodam no adaptador como subprocesso real.
"""
from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import adaptador_harness as adaptador  # noqa: E402
import observabilidade as obs  # noqa: E402
import cliente_harness_local as cliente  # noqa: E402
from cliente_harness_local import invocar_adaptador_observado  # noqa: E402

MODELO = "vendor/modelo-teste:free"
SEGREDO = "SEGREDO-NUNCA-PODE-VAZAR-valor-ficticio-sem-padrao-de-segredo"
CHAVE = "CHAVE-FAKE-NUNCA-PODE-VAZAR-credencial-de-teste"

CAMPOS_8 = {
    "modelo", "categoria", "status_http", "duracao_segundos",
    "numero_tentativas", "fallback_utilizado", "origem_erro", "resposta",
}


def _bruto(id_):
    return {
        "id": id_, "name": id_, "context_length": 128000, "description": "",
        "pricing": {"prompt": "0", "completion": "0"},
    }


def _base_dryrun() -> dict:
    return {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_bruto("a/modelo:free"), _bruto(MODELO)],
        "resumo_curado": "resumo de teste suficientemente descritivo",
        "modo": "dryrun",
        "respostas_humanas": ["1"],
    }


def _sinal(estado="limite_atingido", servico="claude", fonte="adauto", motivo="cota_atingida"):
    return {"servico": servico, "estado": estado, "fonte": fonte, "motivo": motivo}


def _entrada_oferta(**sinal) -> dict:
    return {**_base_dryrun(), "sinal_servico": _sinal(**sinal), "modelo_continuidade": MODELO}


def _entrada_execucao(prompt="Responda apenas: ok", respostas=None, **sinal) -> dict:
    return {
        **_entrada_oferta(**sinal),
        "aprovado_por_humano": True,
        "confirmo_modo_real": True,
        "prompt_ficticio": prompt,
        "respostas_humanas": respostas if respostas is not None else ["claude", MODELO, "AUTORIZO"],
    }


def _rodar_subprocesso(entrada) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "adaptador_harness.py")],
        input=json.dumps(entrada), capture_output=True, text=True, timeout=20,
    )


@contextmanager
def _rede_mockada(status=200, conteudo="ok", side_effect=None):
    resposta = MagicMock()
    resposta.status_code = status
    resposta.json.return_value = {"choices": [{"message": {"content": conteudo}}]}
    with patch("requests.post") as post, patch("ponte_openrouter.executor_real.CredentialManagerReader") as cred:
        cred.return_value.obter_chave.return_value = CHAVE
        post.return_value = resposta
        if side_effect is not None:
            post.side_effect = side_effect
        yield post, cred


# 1 + 8. Caminho normal sem fallback e comportamento anterior preservado sem sinal ofertável
@pytest.mark.parametrize(
    "sinal",
    [
        None,  # sem sinal nenhum
        _sinal(estado="disponivel"),
        _sinal(estado="limite_proximo"),
        _sinal(estado="desconhecido"),
        _sinal(fonte="fonte_nao_autorizada"),  # indisponivel/limite só valem com fonte autorizada
        "texto que não é um objeto",
    ],
)
def test_sem_sinal_ofertavel_o_fluxo_anterior_e_identico(sinal):
    esperado = adaptador._processar(_base_dryrun())
    entrada = _base_dryrun()
    if sinal is not None:
        entrada["sinal_servico"] = sinal
        entrada["modelo_continuidade"] = MODELO
    with _rede_mockada() as (post, cred):
        saida = adaptador._processar(entrada)
    assert saida == esperado
    assert set(saida) == CAMPOS_8 and "continuidade" not in saida
    assert saida["categoria"] == "sucesso_simulado" and saida["fallback_utilizado"] is False
    post.assert_not_called()
    cred.assert_not_called()


# 2. Oferta quando Claude/ChatGPT estão indisponíveis (subprocesso real, sem rede)
@pytest.mark.parametrize("estado, servico", [("limite_atingido", "claude"), ("indisponivel", "chatgpt")])
def test_oferta_quando_servico_indisponivel_nao_executa_nada(estado, servico):
    processo = _rodar_subprocesso(_entrada_oferta(estado=estado, servico=servico))
    assert processo.returncode == 0
    saida = json.loads(processo.stdout)
    assert set(saida) == {"continuidade"}
    c = saida["continuidade"]
    assert c["etapa"] == "oferta"
    assert (c["servico_afetado"], c["estado_servico"], c["modelo"]) == (servico, estado, MODELO)
    assert c["custo_estimado"] == "gratuito" and c["motivo"] == "cota_atingida"
    assert c["chamada_realizada"] is False and c["numero_chamadas"] == 0
    assert c["categoria"] == "nao_executado" and c["autorizado"] is False
    assert MODELO in c["oferta_texto"] and servico in c["oferta_texto"]


def test_oferta_exige_modelo_continuidade():
    entrada = _entrada_oferta()
    del entrada["modelo_continuidade"]
    processo = _rodar_subprocesso(entrada)
    assert processo.returncode != 0
    assert json.loads(processo.stdout)["tipo_erro"] == "EntradaInvalidaError"


def _leitor(*respostas):
    """Leitor com a marca de terminal real (como leitor_interativo). O que se
    testa é o fluxo; a digitação por pessoa é simulada só aqui."""
    fila = list(respostas)
    perguntas = []

    def _ler(pergunta):
        perguntas.append(pergunta)
        if not fila:
            raise EOFError
        return fila.pop(0)

    _ler.origem_interativa = True
    _ler.perguntas = perguntas
    return _ler


def _executar(entrada, *respostas):
    leitor = _leitor(*respostas) if respostas else None
    return cliente.executar_continuidade_interativa(entrada, leitor=leitor)


def _entrada_cli(prompt="Responda apenas: ok") -> dict:
    return {**_entrada_oferta(), "prompt_ficticio": prompt}


TRIPLA = ("claude", MODELO, "AUTORIZO")


# 3. JSON pré-preenchido NÃO autoriza execução (bloqueio de segurança)
def test_json_pre_preenchido_nao_autoriza_execucao_no_adaptador():
    with _rede_mockada() as (post, cred), patch("ponte_openrouter.executor_real.executar_chamada_real") as exec_real:
        saida = adaptador._processar(_entrada_execucao())
    c = saida["continuidade"]
    assert c["etapa"] == "recusado_json" and c["motivo_decisao"] == "confirmacao_apenas_por_json"
    assert c["categoria"] == "recusado_pelo_humano" and c["autorizado"] is False
    assert c["chamada_realizada"] is False and c["numero_chamadas"] == 0
    post.assert_not_called()
    cred.assert_not_called()
    exec_real.assert_not_called()


@pytest.mark.parametrize(
    "ajuste",
    [
        {"aprovado_por_humano": True},
        {"confirmo_modo_real": True},
        {"respostas_humanas": ["claude", MODELO, "AUTORIZO"]},
        {"respostas_humanas": ["ACEITO O CUSTO"]},
        {"aprovado_por_humano": True, "confirmo_modo_real": True, "respostas_humanas": ["x", "y", "z"]},
    ],
)
def test_qualquer_aprovacao_no_json_vira_recusa_via_subprocesso_sem_rede(ajuste):
    entrada = _entrada_oferta()
    entrada.update(ajuste)
    processo = _rodar_subprocesso(entrada)
    assert processo.returncode == 0
    c = json.loads(processo.stdout)["continuidade"]
    assert c["etapa"] == "recusado_json" and c["numero_chamadas"] == 0 and c["autorizado"] is False


def test_json_pre_preenchido_nao_autoriza_no_cliente_interativo_sem_terminal():
    # Sem leitor e sem terminal real, as chaves de aprovação do JSON são ignoradas.
    with _rede_mockada() as (post, cred), patch("ponte_openrouter.continuidade._abrir_terminal", side_effect=OSError):
        saida, codigo = cliente.executar_continuidade_interativa(_entrada_execucao())
    c = saida["continuidade"]
    assert codigo == 3 and c["motivo_decisao"] == "sem_terminal_interativo" and c["numero_chamadas"] == 0
    post.assert_not_called()
    cred.assert_not_called()


def test_leitor_nao_interativo_injetado_e_recusado_pelo_cliente():
    fila = list(TRIPLA)
    with _rede_mockada() as (post, _c):
        saida, codigo = cliente.executar_continuidade_interativa(_entrada_execucao(), leitor=lambda _p: fila.pop(0))
    assert codigo == 3 and saida["continuidade"]["motivo_decisao"] == "confirmacao_nao_interativa"
    assert len(fila) == 3  # nenhuma pergunta foi feita
    post.assert_not_called()


# 3b. Recusa sem confirmação digitada correta: nenhuma chamada
@pytest.mark.parametrize(
    "respostas",
    [
        (),
        ("claude",),
        ("claude", MODELO),
        ("chatgpt", MODELO, "AUTORIZO"),
        ("claude", "outro/modelo:free", "AUTORIZO"),
        ("claude", MODELO, "sim"),
    ],
)
def test_recusa_sem_confirmacao_tripla_nao_chama_nada(respostas):
    with _rede_mockada() as (post, cred):
        saida, codigo = cliente.executar_continuidade_interativa(_entrada_cli(), leitor=_leitor(*respostas))
    c = saida["continuidade"]
    assert codigo == 3
    assert c["categoria"] == "recusado_pelo_humano" and c["autorizado"] is False
    assert c["chamada_realizada"] is False and c["numero_chamadas"] == 0
    post.assert_not_called()
    cred.assert_not_called()


def test_fluxo_de_oferta_continua_sem_rede_mesmo_com_aprovacoes_falsas_a_false():
    entrada = _entrada_execucao()
    entrada["aprovado_por_humano"] = False
    entrada["confirmo_modo_real"] = False
    entrada["respostas_humanas"] = ["1"]
    c = json.loads(_rodar_subprocesso(entrada).stdout)["continuidade"]
    assert c["etapa"] == "oferta" and c["chamada_realizada"] is False


# 4. Uma única chamada após confirmação digitada, sem orquestrar(), com allow_fallbacks=False
def test_uma_unica_chamada_apos_confirmacao_com_allow_fallbacks_false():
    with _rede_mockada(200, "ok") as (post, cred), patch("ponte_openrouter.orquestrador.orquestrar") as orquestrar:
        saida, codigo = _executar(_entrada_cli(), *TRIPLA)
    assert codigo == 0
    assert post.call_count == 1
    corpo = post.call_args.kwargs["json"]
    assert corpo["model"] == MODELO and corpo["provider"] == {"allow_fallbacks": False}
    assert cred.return_value.obter_chave.call_count == 1
    orquestrar.assert_not_called()
    c = saida["continuidade"]
    assert c["etapa"] == "execucao" and c["autorizado"] is True
    assert c["categoria"] == "sucesso" and c["status_http"] == 200
    assert (c["numero_chamadas"], c["retry"], c["troca_de_modelo"], c["fallback_utilizado"]) == (1, False, False, False)


def test_modelo_pago_exige_quarta_confirmacao_no_cliente():
    entrada = _entrada_cli()
    entrada["modelos_brutos"] = [_bruto("a/modelo:free"), {**_bruto(MODELO), "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]
    with _rede_mockada() as (post, _c):
        saida, codigo = _executar(entrada, *TRIPLA)  # falta a 4ª
    assert codigo == 3 and saida["continuidade"]["motivo_decisao"] == "resposta_ausente_custo"
    post.assert_not_called()
    with _rede_mockada() as (post, _c):
        saida, codigo = _executar(entrada, *TRIPLA, "ACEITO O CUSTO")
    assert codigo == 0 and post.call_count == 1 and saida["continuidade"]["custo_estimado"].startswith("pago")


# 5. 429/5xx/desconhecido do OpenRouter: sem retry e sem troca de modelo
@pytest.mark.parametrize(
    "status, categoria", [(429, "indisponibilidade"), (503, "indisponibilidade"), (418, "nao_classificado")]
)
def test_resposta_de_erro_do_openrouter_nao_provoca_retry_nem_troca_de_modelo(status, categoria):
    with _rede_mockada(status) as (post, _cred):
        saida, _codigo = _executar(_entrada_cli(), *TRIPLA)
    assert post.call_count == 1
    assert post.call_args.kwargs["json"]["model"] == MODELO
    c = saida["continuidade"]
    assert (c["status_http"], c["categoria"], c["origem_resultado"]) == (status, categoria, "openrouter")
    assert c["numero_chamadas"] == 1 and c["modelo"] == MODELO


# 6. Registro somente com campos permitidos (e gravação em arquivo de log)
def test_registro_so_tem_campos_permitidos_e_grava_uma_linha(tmp_path):
    base = obs.construir_registro(adaptador._processar(_base_dryrun()), 0, 0.1)
    with _rede_mockada(200, "resposta qualquer") as (_post, _cred):
        saida, _ = _executar(_entrada_cli(), *TRIPLA)
    registro = obs.construir_registro(saida, 0, 0.5)

    assert set(registro) == set(base) | {"continuidade"}
    permitidos = (
        set(obs.CAMPOS_CONTINUIDADE_TEXTO) | set(obs.CAMPOS_CONTINUIDADE_BOOL) | set(obs.CAMPOS_CONTINUIDADE_INT)
    )
    assert set(registro["continuidade"]) == permitidos
    assert "oferta_texto" not in registro["continuidade"] and "mensagem" not in registro["continuidade"]
    assert registro["modelo"] == MODELO and registro["numero_tentativas"] == 1
    assert registro["resposta_caracteres"] == len("resposta qualquer")  # só o comprimento

    caminho = tmp_path / "continuidade.jsonl"
    obs.gravar_registro(registro, caminho)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1 and json.loads(linhas[0])["continuidade"]["etapa"] == "execucao"


def test_log_de_ponta_a_ponta_pelo_cliente_registra_a_oferta(tmp_path):
    caminho = tmp_path / "oferta.jsonl"
    saida, codigo, registro = invocar_adaptador_observado(_entrada_oferta(), log_path=caminho)
    assert codigo == 0 and saida["continuidade"]["etapa"] == "oferta"
    assert registro["continuidade"]["etapa"] == "oferta" and registro["continuidade"]["numero_chamadas"] == 0
    assert registro["log_gravado"] is True and len(caminho.read_text(encoding="utf-8").splitlines()) == 1


def test_cliente_interativo_grava_log_proprio_sem_segredos(tmp_path):
    caminho = tmp_path / "interativo.jsonl"
    with _rede_mockada(200, f"resposta {SEGREDO}"):
        saida, _ = cliente.executar_continuidade_interativa(
            _entrada_cli(), leitor=_leitor(*TRIPLA), log_path=caminho
        )
    conteudo = caminho.read_text(encoding="utf-8")
    assert len(conteudo.splitlines()) == 1 and "execucao" in conteudo
    for proibido in (SEGREDO, CHAVE, "Bearer"):
        assert proibido not in conteudo


# 7. Prompt, resposta, token e segredo ausentes da saída e do log
def test_prompt_resposta_token_e_segredo_nao_aparecem_na_saida_nem_no_log(tmp_path):
    prompt = f"Resuma isto: {SEGREDO}"
    resposta_modelo = f"resposta do modelo contendo {SEGREDO}"
    caminho = tmp_path / "seguro.jsonl"

    entrada = _entrada_cli(prompt)
    cenarios = []
    with _rede_mockada(200, resposta_modelo):
        cenarios.append(_executar(entrada, *TRIPLA)[0])
    with _rede_mockada(side_effect=RuntimeError(f"falha Bearer {SEGREDO} {CHAVE}")):
        cenarios.append(_executar(entrada, *TRIPLA)[0])
    with _rede_mockada() as (post, _c):
        cenarios.append(_executar(entrada, SEGREDO)[0])
        post.assert_not_called()

    assert cenarios[1]["continuidade"]["categoria"] == "falha_execucao"
    for saida in cenarios:
        registro = obs.construir_registro(saida, 0, 0.2, stdout=json.dumps(saida), stderr="")
        obs.gravar_registro(registro, caminho)
        for texto in (json.dumps(saida, ensure_ascii=False), json.dumps(registro, ensure_ascii=False)):
            for proibido in (SEGREDO, CHAVE, prompt, resposta_modelo, "Bearer"):
                assert proibido not in texto
    conteudo_log = caminho.read_text(encoding="utf-8")
    for proibido in (SEGREDO, CHAVE, prompt, resposta_modelo, "Bearer"):
        assert proibido not in conteudo_log
    assert len(conteudo_log.splitlines()) == 3


# 8. Fluxo antigo `modo: real` não é caminho alternativo: bloqueado mesmo com aprovações no JSON
def _entrada_real_antiga(**extra) -> dict:
    return {
        **_base_dryrun(),
        "modo": "real",
        "aprovado_por_humano": True,
        "confirmo_modo_real": True,
        "prompt_ficticio": "Responda apenas: ok",
        "respostas_humanas": ["1"],
        **extra,
    }


def test_modo_real_antigo_e_bloqueado_mesmo_com_aprovacoes_no_json_via_subprocesso():
    processo = _rodar_subprocesso(_entrada_real_antiga())
    assert processo.returncode != 0
    saida = json.loads(processo.stdout)
    assert saida["tipo_erro"] == "AprovacaoAusenteError"
    assert "status_http" not in saida and "resposta" not in saida


def test_modo_real_antigo_nao_toca_rede_credencial_nem_orquestrador():
    with _rede_mockada() as (post, cred), patch("ponte_openrouter.orquestrador.orquestrar") as orq, patch(
        "ponte_openrouter.executor_real.executar_chamada_real"
    ) as exec_real, patch.object(adaptador, "executar_via_contrato") as via_contrato:
        with pytest.raises(adaptador.AprovacaoAusenteError):
            adaptador._processar(_entrada_real_antiga())
        with pytest.raises(adaptador.AprovacaoAusenteError):
            adaptador._processar(_entrada_real_antiga(sinal_servico=_sinal(estado="disponivel")))
    for alvo in (post, cred, orq, exec_real, via_contrato):
        alvo.assert_not_called()


def test_modo_real_antigo_continua_bloqueado_pelo_cliente_observado(tmp_path):
    saida, codigo, registro = invocar_adaptador_observado(_entrada_real_antiga(), log_path=tmp_path / "r.jsonl")
    assert codigo != 0 and saida["tipo_erro"] == "AprovacaoAusenteError"
    assert registro["status_http"] is None and registro["sucesso"] is False


def test_dryrun_antigo_continua_funcionando():
    saida = adaptador._processar(_base_dryrun())
    assert saida["categoria"] == "sucesso_simulado" and set(saida) == CAMPOS_8
