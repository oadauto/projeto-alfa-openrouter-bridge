"""Testes do adaptador local mínimo — Fase 4A (scripts/adaptador_harness.py).

Exatamente os 5 testes essenciais exigidos, somente estes:
1. chamada local em dry-run;
2. saída JSON válida (e contendo somente os campos sanitizados esperados);
3. bloqueio do modo real sem dupla confirmação;
4. ausência de segredo no resultado;
5. propagação correta de erro do subprocesso.

O adaptador é invocado como subprocesso de verdade (não como função Python
importada), para testar exatamente a interface JSON/stdin/stdout que um
agente externo (Claude) usaria. Nenhuma chamada de rede real ocorre em
nenhum destes testes: os casos de modo="real" aqui testam apenas o
bloqueio pelo portão de aprovação, que acontece ANTES de qualquer
tentativa de rede - nenhum mock de `requests` é necessário porque a
execução real nunca é alcançada.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "adaptador_harness.py"

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


def _rodar_adaptador(entrada: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(entrada),
        capture_output=True,
        text=True,
        timeout=15,
    )


def _entrada_dryrun_basica() -> dict:
    return {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste suficientemente descritivo",
        "modo": "dryrun",
        "respostas_humanas": ["1"],
    }


# 1. chamada local em dry-run
def test_chamada_local_em_dryrun_tem_sucesso():
    processo = _rodar_adaptador(_entrada_dryrun_basica())

    assert processo.returncode == 0
    saida = json.loads(processo.stdout)
    assert saida["categoria"] == "sucesso_simulado"
    assert saida["modelo"] == "a/modelo:free"


# 2. saída JSON válida, com somente os campos sanitizados esperados
def test_saida_e_json_valido_com_somente_os_campos_esperados():
    processo = _rodar_adaptador(_entrada_dryrun_basica())

    saida = json.loads(processo.stdout)  # levanta JSONDecodeError se inválido
    assert set(saida.keys()) == CAMPOS_ESPERADOS


# 3. bloqueio do modo real sem dupla confirmação
def test_modo_real_sem_dupla_confirmacao_e_bloqueado():
    entrada = {
        "tarefa": "continuidade_critica",
        "modelos_brutos": [_modelo_bruto("a/modelo:free")],
        "resumo_curado": "resumo de teste",
        "modo": "real",
        "prompt_ficticio": "prompt de teste",
        "respostas_humanas": ["1"],
        # aprovado_por_humano e confirmo_modo_real OMITIDOS de propósito
    }

    processo = _rodar_adaptador(entrada)

    assert processo.returncode != 0
    saida = json.loads(processo.stdout)
    assert saida["tipo_erro"] == "AprovacaoAusenteError"
    assert "erro" in saida
    assert "status_http" not in saida  # nenhum campo de resultado deve aparecer


# 4. ausência de segredo no resultado
def test_resultado_dryrun_nunca_contem_segredo():
    processo = _rodar_adaptador(_entrada_dryrun_basica())

    texto_completo = processo.stdout.lower()
    termos_proibidos = {"chave", "token", "senha", "credencial", "authorization", "api_key", "secret", "bearer"}
    for termo in termos_proibidos:
        assert termo not in texto_completo


# 5. propagação correta de erro do subprocesso
def test_entrada_invalida_propaga_erro_estruturado_sem_traceback_bruto():
    processo = _rodar_adaptador("isto nao e json valido")  # string, não dict - via _rodar_adaptador abaixo

    assert processo.returncode != 0
    saida = json.loads(processo.stdout)
    assert "erro" in saida
    assert "tipo_erro" in saida
    # nunca deve vazar um traceback Python bruto no stdout
    assert "Traceback (most recent call last)" not in processo.stdout
