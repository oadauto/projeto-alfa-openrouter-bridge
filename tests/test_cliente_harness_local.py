"""Testes do cliente local do adaptador harness — Fases 4B e 4E
(scripts/cliente_harness_local.py).

Os 4 testes mínimos originais da Fase 4B (inalterados):
1. cliente chama o adaptador em dry-run;
2. cliente devolve JSON sanitizado válido;
3. cliente preserva erro estruturado e código de saída diferente de zero;
4. cliente não autoriza modo real sozinho.

Mais os testes mínimos de robustez de borda da Fase 4E:
5. timeout do subprocesso é convertido em erro estruturado, sem traceback;
6. entrada não serializável em JSON é convertida em erro estruturado;
7. stdout do script contém somente uma linha JSON, mesmo em caminho de erro;
8. nenhuma mensagem de erro desta camada contém chave/token/segredo.

Testado via chamada direta de `invocar_adaptador()` (que já executa
`adaptador_harness.py` como subprocesso de verdade) - não é necessário
nenhum mock de rede, porque nenhum destes cenários alcança uma tentativa
de execução real: dry-run nunca toca rede, e o caso de modo="real" aqui
testa apenas o bloqueio pelo portão de aprovação (que ocorre antes de
qualquer chamada a executor_real). Os testes de timeout/erro de
serialização usam apenas monkeypatch de `subprocess.run` ou entrada
deliberadamente não serializável - nenhum processo real precisa travar
para validar o comportamento.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cliente_harness_local  # noqa: E402
from cliente_harness_local import invocar_adaptador  # noqa: E402

CAMPOS_ESPERADOS = {
    "modelo",
    "categoria",
    "status_http",
    "duracao_segundos",
    "numero_tentativas",
    "fallback_utilizado",
    "origem_erro",
    "resposta",
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


# 1. cliente chama o adaptador em dry-run
def test_cliente_chama_o_adaptador_em_dryrun():
    saida, codigo_saida = invocar_adaptador(_entrada_dryrun_basica())

    assert codigo_saida == 0
    assert saida["categoria"] == "sucesso_simulado"
    assert saida["modelo"] == "a/modelo:free"


# 2. cliente devolve JSON sanitizado válido
def test_cliente_devolve_json_sanitizado_valido():
    saida, _codigo_saida = invocar_adaptador(_entrada_dryrun_basica())

    assert isinstance(saida, dict)
    assert set(saida.keys()) == CAMPOS_ESPERADOS


# 3. cliente preserva erro estruturado e código de saída diferente de zero
def test_cliente_preserva_erro_estruturado_e_codigo_de_saida():
    entrada_invalida = {
        "tarefa": "",  # tarefa vazia -> EntradaInvalidaError no harness_contrato
        "modelos_brutos": [],
        "resumo_curado": "resumo de teste",
        "modo": "dryrun",
        "respostas_humanas": [],
    }

    saida, codigo_saida = invocar_adaptador(entrada_invalida)

    assert codigo_saida != 0
    assert "erro" in saida
    assert "tipo_erro" in saida
    assert "categoria" not in saida  # nenhum campo de resultado deve vazar num erro


# 4. cliente não autoriza modo real sozinho
def test_cliente_nao_autoriza_modo_real_sozinho():
    entrada_modo_real_sem_aprovacao = {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste",
        "modo": "real",
        "prompt_ficticio": "prompt de teste",
        "respostas_humanas": ["1"],
        # aprovado_por_humano e confirmo_modo_real OMITIDOS de propósito -
        # o teste existe exatamente para confirmar que o CLIENTE não as
        # insere por conta própria antes de repassar ao adaptador.
    }

    saida, codigo_saida = invocar_adaptador(entrada_modo_real_sem_aprovacao)

    assert codigo_saida != 0
    assert saida["tipo_erro"] == "AprovacaoAusenteError"
    assert "status_http" not in saida


# --- Fase 4E — robustez de borda --------------------------------------------

TERMOS_PROIBIDOS = {"chave", "token", "senha", "credencial", "authorization", "api_key", "secret", "bearer"}


# 5. timeout do subprocesso é convertido em erro estruturado, sem traceback
def test_timeout_do_subprocesso_gera_erro_estruturado_sem_traceback(monkeypatch):
    def _subprocess_run_que_expira(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="adaptador_harness.py", timeout=kwargs.get("timeout", 0.01))

    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _subprocess_run_que_expira)

    saida, codigo_saida = invocar_adaptador(_entrada_dryrun_basica(), timeout=0.01)

    assert codigo_saida != 0
    assert saida["tipo_erro"] == "TimeoutExpired"
    assert "erro" in saida
    assert "categoria" not in saida  # nenhum campo de resultado deve vazar
    assert "Traceback (most recent call last)" not in saida["erro"]


# 6. entrada não serializável em JSON é convertida em erro estruturado
def test_entrada_nao_serializavel_gera_erro_estruturado():
    entrada_nao_serializavel = {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste",
        "modo": "dryrun",
        "respostas_humanas": ["1"],
        "campo_invalido": {1, 2, 3},  # set não é serializável em JSON
    }

    saida, codigo_saida = invocar_adaptador(entrada_nao_serializavel)

    assert codigo_saida != 0
    assert saida["tipo_erro"] == "TypeError"
    assert "erro" in saida
    assert "categoria" not in saida


# 7. stdout do script contém somente uma linha JSON, mesmo em caminho de erro
def test_stdout_do_script_contem_somente_json_em_caminho_de_erro():
    script = Path(cliente_harness_local.__file__).resolve()
    processo = subprocess.run(
        [sys.executable, str(script)],
        input="isto nao e json valido",
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert processo.returncode != 0
    linhas = [linha for linha in processo.stdout.splitlines() if linha.strip()]
    assert len(linhas) == 1
    saida = json.loads(linhas[0])  # levanta JSONDecodeError se stdout não for só JSON
    assert "erro" in saida
    assert "Traceback (most recent call last)" not in processo.stdout


# 8. nenhuma mensagem de erro desta camada contém chave/token/segredo
def test_mensagens_de_erro_do_cliente_nunca_contem_segredo(monkeypatch):
    def _subprocess_run_que_expira(*_args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="adaptador_harness.py", timeout=kwargs.get("timeout", 0.01))

    monkeypatch.setattr(cliente_harness_local.subprocess, "run", _subprocess_run_que_expira)

    saida, _codigo_saida = invocar_adaptador(_entrada_dryrun_basica(), timeout=0.01)

    texto_completo = json.dumps(saida).lower()
    for termo in TERMOS_PROIBIDOS:
        assert termo not in texto_completo
