"""Testes do cliente local do adaptador harness — Fase 4B
(scripts/cliente_harness_local.py).

Exatamente os 4 testes mínimos exigidos, somente estes:
1. cliente chama o adaptador em dry-run;
2. cliente devolve JSON sanitizado válido;
3. cliente preserva erro estruturado e código de saída diferente de zero;
4. cliente não autoriza modo real sozinho.

Testado via chamada direta de `invocar_adaptador()` (que já executa
`adaptador_harness.py` como subprocesso de verdade) - não é necessário
nenhum mock de rede, porque nenhum destes cenários alcança uma tentativa
de execução real: dry-run nunca toca rede, e o caso de modo="real" aqui
testa apenas o bloqueio pelo portão de aprovação (que ocorre antes de
qualquer chamada a executor_real).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
