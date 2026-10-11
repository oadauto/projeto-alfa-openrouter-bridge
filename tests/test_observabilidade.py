"""Testes da observabilidade segura do cliente harness — Fase 5
(scripts/observabilidade.py e invocar_adaptador_observado em
scripts/cliente_harness_local.py).

Todos os testes usam dry-run ou mocks de `subprocess.run`: nenhum toca rede,
credencial real ou OpenRouter. Os "segredos" usados aqui são FICTÍCIOS e
existem apenas para provar que o saneamento os remove.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cliente_harness_local  # noqa: E402
import observabilidade  # noqa: E402
from cliente_harness_local import invocar_adaptador, invocar_adaptador_observado  # noqa: E402
from observabilidade import (  # noqa: E402
    LIMITE_ARQUIVO_BYTES,
    LogPathInvalido,
    MENSAGEM_ERRO_OMITIDA,
    construir_registro,
    gravar_registro,
    sanitizar_texto,
    validar_caminho_log,
)

# Valores fictícios, com o formato típico de segredos - NUNCA reais.
CHAVE_FICTICIA = "sk-or-v1-FICTICIA0123456789abcdefghijklmnop"
BEARER_FICTICIO = "Bearer abcDEF123456.token-ficticio_xyz"
TEXTO_DA_RESPOSTA = "TEXTO_DA_RESPOSTA_DO_MODELO_QUE_NAO_PODE_SER_REGISTRADO"

CAMPOS_REGISTRO = {
    "schema_versao",
    "timestamp_utc",
    "codigo_saida",
    "sucesso",
    "modelo",
    "categoria",
    "status_http",
    "duracao_segundos",
    "duracao_cliente_segundos",
    "numero_tentativas",
    "fallback_utilizado",
    "origem_erro",
    "tipo_erro",
    "erro",
    "stdout_bytes",
    "stderr_bytes",
    "stderr_trecho",
    "resposta_caracteres",
    "log_gravado",
    "tipo_erro_log",
}


def _modelo_bruto(id_, contexto=128000):
    return {
        "id": id_,
        "name": id_,
        "context_length": contexto,
        "description": "",
        "pricing": {"prompt": "0", "completion": "0"},
    }


def _entrada_dryrun_basica() -> dict:
    return {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste suficientemente descritivo",
        "modo": "dryrun",
        "respostas_humanas": ["1"],
    }


def _entrada_invalida() -> dict:
    return {
        "tarefa": "",
        "modelos_brutos": [],
        "resumo_curado": "resumo de teste",
        "modo": "dryrun",
        "respostas_humanas": [],
    }


def _falso_subprocess_run(stdout="", stderr="", returncode=0):
    def _run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)

    return _run


# --- saneamento ---------------------------------------------------------------


def test_sanitizar_remove_padroes_tipicos_de_segredo():
    texto = (
        f"falha {CHAVE_FICTICIA} e {BEARER_FICTICIO} e api_key=valor-secreto-123 "
        f"e Authorization: topsecretvalue e token: abc123 e {'A1b2C3d4' * 6}"
    )
    saneado = sanitizar_texto(texto)
    assert CHAVE_FICTICIA not in saneado
    assert "abcDEF123456" not in saneado
    assert "valor-secreto-123" not in saneado
    assert "topsecretvalue" not in saneado
    assert "abc123" not in saneado
    assert "A1b2C3d4" * 6 not in saneado
    assert observabilidade.MARCADOR_REDACAO in saneado


def test_sanitizar_trunca_e_aceita_none_e_bytes():
    assert sanitizar_texto(None) == ""
    assert sanitizar_texto(b"erro simples") == "erro simples"
    longo = "palavra " * 500
    saneado = sanitizar_texto(longo, limite=100)
    assert len(saneado) <= 100 + len("...[truncado]")
    assert saneado.endswith("...[truncado]")


# --- registro -----------------------------------------------------------------


def test_registro_de_sucesso_dryrun_tem_somente_campos_da_lista_branca():
    saida, codigo, registro = invocar_adaptador_observado(_entrada_dryrun_basica())

    assert codigo == 0
    assert set(registro.keys()) == CAMPOS_REGISTRO
    assert registro["sucesso"] is True
    assert registro["codigo_saida"] == 0
    assert registro["modelo"] == "a/modelo:free"
    assert registro["categoria"] == "sucesso_simulado"
    assert registro["status_http"] is None  # dry-run
    assert registro["duracao_segundos"] is None  # dry-run
    assert registro["duracao_cliente_segundos"] >= 0
    assert registro["numero_tentativas"] == 1
    assert registro["fallback_utilizado"] is False
    assert registro["tipo_erro"] is None
    assert registro["erro"] is None
    assert registro["stdout_bytes"] > 0
    assert "resposta" not in registro
    assert registro["resposta_caracteres"] is None or isinstance(registro["resposta_caracteres"], int)
    assert registro["log_gravado"] is False  # sem log_path


def test_registro_de_erro_estruturado_marca_falha():
    saida, codigo, registro = invocar_adaptador_observado(_entrada_invalida())

    assert codigo != 0
    assert "erro" in saida
    assert registro["sucesso"] is False
    assert registro["codigo_saida"] == codigo
    assert registro["tipo_erro"] == saida["tipo_erro"]
    assert registro["categoria"] is None
    assert set(registro.keys()) == CAMPOS_REGISTRO


def test_observado_nao_altera_o_resultado_de_invocar_adaptador():
    entrada = _entrada_dryrun_basica()
    saida_normal, codigo_normal = invocar_adaptador(entrada)
    saida_obs, codigo_obs, _registro = invocar_adaptador_observado(entrada)

    assert codigo_normal == codigo_obs
    assert set(saida_normal.keys()) == set(saida_obs.keys())
    assert saida_normal["modelo"] == saida_obs["modelo"]
    assert saida_normal["categoria"] == saida_obs["categoria"]


def test_timeout_registra_tipo_e_redige_stderr(monkeypatch):
    def _run_que_expira(*_args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="adaptador_harness.py",
            timeout=kwargs.get("timeout", 0.01),
            output=b"",
            stderr=f"falha de rede usando {CHAVE_FICTICIA} e {BEARER_FICTICIO}".encode(),
        )

    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _run_que_expira)

    saida, codigo, registro = invocar_adaptador_observado(_entrada_dryrun_basica(), timeout=0.01)

    assert codigo != 0
    assert registro["sucesso"] is False
    assert registro["tipo_erro"] == "TimeoutExpired"
    assert registro["stderr_bytes"] > 0
    texto = json.dumps(registro)
    assert CHAVE_FICTICIA not in texto
    assert "abcDEF123456" not in texto
    assert observabilidade.MARCADOR_REDACAO in registro["stderr_trecho"]


def test_registro_nunca_contem_a_resposta_do_modelo(monkeypatch):
    stdout = json.dumps(
        {
            "modelo": "a/modelo:free",
            "categoria": "sucesso",
            "status_http": 200,
            "duracao_segundos": 1.5,
            "numero_tentativas": 1,
            "fallback_utilizado": False,
            "origem_erro": None,
            "resposta": TEXTO_DA_RESPOSTA,
        }
    )
    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _falso_subprocess_run(stdout=stdout))

    saida, codigo, registro = invocar_adaptador_observado(_entrada_dryrun_basica())

    assert saida["resposta"] == TEXTO_DA_RESPOSTA  # o resultado do harness segue intacto
    assert codigo == 0
    assert registro["sucesso"] is True
    assert registro["status_http"] == 200
    assert registro["duracao_segundos"] == 1.5
    assert registro["resposta_caracteres"] == len(TEXTO_DA_RESPOSTA)
    assert TEXTO_DA_RESPOSTA not in json.dumps(registro)


def test_stdout_invalido_nao_vaza_conteudo_bruto_no_registro(monkeypatch):
    bruto = f"isto nao e json {CHAVE_FICTICIA}"
    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _falso_subprocess_run(stdout=bruto, stderr="boom"))

    saida, codigo, registro = invocar_adaptador_observado(_entrada_dryrun_basica())

    assert codigo != 0
    assert registro["tipo_erro"] == "JSONDecodeError"
    assert registro["stdout_bytes"] == len(bruto.encode())
    assert registro["stderr_trecho"] == "boom"
    assert CHAVE_FICTICIA not in json.dumps(registro)


# --- gravação em arquivo ------------------------------------------------------


def test_log_so_e_gravado_com_log_path_explicito(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    invocar_adaptador_observado(_entrada_dryrun_basica())
    assert list(tmp_path.iterdir()) == []  # opt-in: nada foi criado

    destino = tmp_path / "sub" / "obs.jsonl"
    _s, _c, registro = invocar_adaptador_observado(_entrada_dryrun_basica(), log_path=destino)
    assert destino.exists()
    assert registro["log_gravado"] is True


def test_log_acrescenta_uma_linha_json_valida_por_chamada(tmp_path):
    destino = tmp_path / "obs.jsonl"
    invocar_adaptador_observado(_entrada_dryrun_basica(), log_path=destino)
    invocar_adaptador_observado(_entrada_invalida(), log_path=destino)

    linhas = destino.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    primeiro, segundo = (json.loads(linha) for linha in linhas)
    assert primeiro["sucesso"] is True and primeiro["log_gravado"] is True
    assert segundo["sucesso"] is False and segundo["log_gravado"] is True
    assert set(primeiro.keys()) == CAMPOS_REGISTRO


def test_arquivo_de_log_nao_contem_segredo_nem_resposta(tmp_path, monkeypatch):
    stdout = json.dumps(
        {
            "modelo": "a/modelo:free",
            "categoria": "sucesso",
            "status_http": 200,
            "duracao_segundos": 0.5,
            "numero_tentativas": 1,
            "fallback_utilizado": False,
            "origem_erro": None,
            "resposta": f"{TEXTO_DA_RESPOSTA} {CHAVE_FICTICIA}",
        }
    )
    stderr = f"aviso: usando {CHAVE_FICTICIA} {BEARER_FICTICIO} api_key=segredo-ficticio-999"
    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _falso_subprocess_run(stdout=stdout, stderr=stderr))

    destino = tmp_path / "obs.jsonl"
    invocar_adaptador_observado(_entrada_dryrun_basica(), log_path=destino)

    conteudo = destino.read_text(encoding="utf-8")
    for proibido in (CHAVE_FICTICIA, "abcDEF123456", "segredo-ficticio-999", TEXTO_DA_RESPOSTA):
        assert proibido not in conteudo


def test_falha_ao_gravar_log_nao_altera_o_resultado(tmp_path):
    arquivo_no_caminho = tmp_path / "arquivo"
    arquivo_no_caminho.write_text("x", encoding="utf-8")
    destino_invalido = arquivo_no_caminho / "obs.jsonl"  # pai é um arquivo

    saida_ref, codigo_ref = invocar_adaptador(_entrada_dryrun_basica())
    saida, codigo, registro = invocar_adaptador_observado(_entrada_dryrun_basica(), log_path=destino_invalido)

    assert codigo == codigo_ref == 0
    assert saida["categoria"] == saida_ref["categoria"]
    assert registro["log_gravado"] is False
    assert registro["tipo_erro_log"]  # só o nome do tipo da exceção
    assert str(tmp_path) not in json.dumps(registro)  # nunca o caminho/mensagem


def test_gravar_registro_direto_devolve_flags_corretas(tmp_path):
    registro = construir_registro({"modelo": "m", "categoria": "sucesso"}, 0, 0.1, stdout="{}", stderr="")
    gravado = gravar_registro(registro, tmp_path / "x.jsonl")
    assert gravado["log_gravado"] is True and gravado["tipo_erro_log"] is None
    assert registro["log_gravado"] is False  # o original não é mutado


# --- CLI ----------------------------------------------------------------------


def _rodar_cli(args, entrada=None, cwd=None):
    script = Path(cliente_harness_local.__file__).resolve()
    return subprocess.run(
        [sys.executable, str(script), *args],
        input=json.dumps(entrada if entrada is not None else _entrada_dryrun_basica()),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


def test_cli_com_log_mantem_stdout_somente_json_e_grava_o_arquivo():
    script = Path(cliente_harness_local.__file__).resolve()
    pasta_logs = cliente_harness_local.RAIZ_LOGS
    pasta_logs.mkdir(exist_ok=True)
    destino = pasta_logs / f"teste_fase52_{os.getpid()}.jsonl"
    destino.unlink(missing_ok=True)
    processo = subprocess.run(
        [sys.executable, str(script), "--log", str(destino)],
        input=json.dumps(_entrada_dryrun_basica()),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert processo.returncode == 0
    linhas = [linha for linha in processo.stdout.splitlines() if linha.strip()]
    assert len(linhas) == 1
    saida = json.loads(linhas[0])
    assert saida["categoria"] == "sucesso_simulado"
    assert "log_gravado" not in saida  # o registro vai só para o arquivo
    try:
        registros = [json.loads(linha) for linha in destino.read_text(encoding="utf-8").splitlines()]
    finally:
        destino.unlink(missing_ok=True)
    assert len(registros) == 1 and registros[0]["sucesso"] is True


def test_cli_sem_log_nao_cria_arquivos(tmp_path):
    script = Path(cliente_harness_local.__file__).resolve()
    processo = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(_entrada_dryrun_basica()),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    assert processo.returncode == 0
    assert list(tmp_path.iterdir()) == []


def test_modo_real_sem_aprovacao_continua_bloqueado_e_e_observado(tmp_path):
    entrada = {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste",
        "modo": "real",
        "prompt_ficticio": "prompt de teste",
        "respostas_humanas": ["1"],
        # aprovado_por_humano e confirmo_modo_real omitidos de propósito.
    }
    saida, codigo, registro = invocar_adaptador_observado(entrada, log_path=tmp_path / "o.jsonl")

    assert codigo != 0
    assert saida["tipo_erro"] == "AprovacaoAusenteError"
    assert registro["sucesso"] is False
    assert registro["status_http"] is None  # nenhuma chamada real ocorreu
    assert registro["tipo_erro"] == "AprovacaoAusenteError"


def test_modulo_observabilidade_nao_importa_rede_nem_credencial():
    codigo = Path(observabilidade.__file__).read_text(encoding="utf-8")
    for proibido in ("import requests", "import urllib", "import socket", "openrouter.ai"):
        assert proibido not in codigo


# --- Fase 5.2 -----------------------------------------------------------------


def test_erro_livre_nunca_e_gravado_so_o_tipo(tmp_path):
    saida = {"erro": f"falha com dado sensivel {CHAVE_FICTICIA} e texto livre qualquer", "tipo_erro": "ValueError"}
    registro = construir_registro(saida, 2, 0.1, stdout="", stderr="")
    assert registro["erro"] == MENSAGEM_ERRO_OMITIDA
    assert registro["tipo_erro"] == "ValueError"
    serializado = json.dumps(registro)
    assert "texto livre qualquer" not in serializado and CHAVE_FICTICIA not in serializado


def test_validar_caminho_aceita_arquivo_jsonl_dentro_de_logs(tmp_path):
    raiz = tmp_path / "logs"
    assert validar_caminho_log(raiz / "a.jsonl", raiz) == (raiz / "a.jsonl").resolve()
    assert validar_caminho_log(raiz / "sub" / "b.jsonl", raiz).name == "b.jsonl"


@pytest.mark.parametrize("ruim", [None, "", "   "])
def test_validar_caminho_recusa_ausente_ou_vazio(tmp_path, ruim):
    with pytest.raises(LogPathInvalido):
        validar_caminho_log(ruim, tmp_path / "logs")


def test_validar_caminho_recusa_fora_de_logs_sufixo_errado_e_travessia(tmp_path):
    raiz = tmp_path / "logs"
    for ruim in (
        tmp_path / "outro.jsonl",
        raiz / "a.txt",
        raiz / ".." / "fuga.jsonl",
        raiz,
        tmp_path / "logs_irmao" / "a.jsonl",
    ):
        with pytest.raises(LogPathInvalido):
            validar_caminho_log(ruim, raiz)


@pytest.mark.parametrize("args", [["--log"], ["--log", "--outra"], ["--log", "fora_de_logs.jsonl"], ["--log", "logs/x.txt"]])
def test_cli_recusa_log_invalido_sem_executar_o_harness(tmp_path, args):
    processo = _rodar_cli(args, cwd=tmp_path)
    assert processo.returncode == 2
    saida = json.loads(processo.stdout)
    assert saida["tipo_erro"] == "LogPathInvalido"
    assert "fora_de_logs" not in processo.stdout  # não ecoa o caminho informado
    assert list(tmp_path.iterdir()) == []


def test_rotacao_move_o_log_cheio_para_ponto_1_e_recomeca(tmp_path):
    destino = tmp_path / "obs.jsonl"
    registro = construir_registro({"modelo": "m", "categoria": "sucesso"}, 0, 0.1, stdout="{}", stderr="")
    gravar_registro(registro, destino, limite_bytes=1)  # 1a linha: arquivo novo
    gravar_registro(registro, destino, limite_bytes=1)  # cheio -> rotaciona
    gravar_registro(registro, destino, limite_bytes=1)  # cheio de novo -> substitui o .1

    anterior = tmp_path / "obs.1.jsonl"
    assert destino.exists() and anterior.exists()
    assert len(destino.read_text(encoding="utf-8").splitlines()) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["obs.1.jsonl", "obs.jsonl"]  # no maximo 2


def test_sem_rotacao_abaixo_do_limite(tmp_path):
    destino = tmp_path / "obs.jsonl"
    registro = construir_registro({"modelo": "m", "categoria": "sucesso"}, 0, 0.1, stdout="{}", stderr="")
    gravar_registro(registro, destino)
    gravar_registro(registro, destino)
    assert len(destino.read_text(encoding="utf-8").splitlines()) == 2
    assert not (tmp_path / "obs.1.jsonl").exists()
    assert LIMITE_ARQUIVO_BYTES == 1024 * 1024


def test_falha_na_rotacao_nao_altera_o_resultado(tmp_path, monkeypatch):
    destino = tmp_path / "obs.jsonl"
    destino.write_text("x" * 10, encoding="utf-8")

    def _falha(*_a, **_k):
        raise OSError("falha simulada")

    monkeypatch.setattr(observabilidade.os, "replace", _falha)
    registro = construir_registro({"modelo": "m", "categoria": "sucesso"}, 0, 0.1, stdout="{}", stderr="")
    gravado = gravar_registro(registro, destino, limite_bytes=1)
    assert gravado["log_gravado"] is False
    assert gravado["tipo_erro_log"] == "OSError"
    assert "falha simulada" not in json.dumps(gravado)
