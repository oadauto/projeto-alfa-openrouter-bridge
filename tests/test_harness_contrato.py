"""Testes de ponte_openrouter.harness_contrato — Fase 1.

Exatamente os 8 testes exigidos, somente estes:
1. entrada válida
2. entrada inválida
3. aprovação recusada
4. resultado de sucesso
5. resultado de erro
6. resposta limitada a 300 caracteres
7. ausência de segredo no resultado
8. confirmação de que o modo dryrun não usa rede nem credencial

Sem rede, sem chave, sem execução real: nenhum mock de requests/credencial
é necessário porque o próprio módulo não importa nada disso (verificado
no teste 8 via AST, no mesmo padrão já usado em test_orquestrador.py).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from ponte_openrouter.harness_contrato import (
    EntradaTarefa,
    EntradaInvalidaError,
    AprovacaoAusenteError,
    ResultadoSanitizado,
    MODO_DRYRUN,
    MODO_REAL,
    executar_contrato,
)


def _entrada_valida(modo=MODO_DRYRUN, modelos_brutos=()):
    return EntradaTarefa(
        tarefa="continuidade_critica",
        modelos_brutos=modelos_brutos,
        resumo_curado="resumo de teste suficientemente descritivo",
        modo=modo,
    )


# 1. entrada válida
def test_entrada_valida_nao_levanta_excecao():
    entrada = _entrada_valida()
    entrada.validar()  # não deve levantar


# 2. entrada inválida
def test_entrada_invalida_levanta_erro():
    entrada = EntradaTarefa(
        tarefa="",  # tarefa vazia é inválida
        modelos_brutos=(),
        resumo_curado="resumo de teste",
        modo=MODO_DRYRUN,
    )
    with pytest.raises(EntradaInvalidaError):
        entrada.validar()


# 3. aprovação recusada
def test_aprovacao_recusada_em_modo_real_levanta_erro_e_nao_executa():
    entrada = _entrada_valida(modo=MODO_REAL, modelos_brutos=({"id": "a/modelo:free"},))

    def executor_que_nao_deveria_ser_chamado(_entrada, _obter_escolha_humana):
        raise AssertionError("o executor não deveria ser chamado sem aprovação humana")

    with pytest.raises(AprovacaoAusenteError):
        executar_contrato(
            entrada,
            executor_que_nao_deveria_ser_chamado,
            papel_executor="alfa",
            aprovado_por_humano=False,
        )


# 4. resultado de sucesso
def test_resultado_de_sucesso_e_construido_corretamente():
    entrada = _entrada_valida(modo=MODO_DRYRUN)

    def executor_sucesso(_entrada, _obter_escolha_humana):
        return ResultadoSanitizado(
            modelo="a/modelo:free",
            status_http=None,
            categoria="sucesso_simulado",
            duracao_segundos=0.01,
            numero_tentativas=1,
            fallback_utilizado=False,
            resposta="resposta simulada de sucesso",
            origem_erro="nao_aplicavel",
        )

    resultado = executar_contrato(entrada, executor_sucesso)

    assert isinstance(resultado, ResultadoSanitizado)
    assert resultado.categoria == "sucesso_simulado"
    assert resultado.modelo == "a/modelo:free"


# 5. resultado de erro
def test_resultado_de_erro_preserva_categoria_e_origem():
    entrada = _entrada_valida(modo=MODO_DRYRUN)

    def executor_erro(_entrada, _obter_escolha_humana):
        return ResultadoSanitizado(
            modelo="a/modelo:free",
            status_http=429,
            categoria="indisponibilidade",
            duracao_segundos=0.02,
            numero_tentativas=1,
            fallback_utilizado=False,
            resposta=None,
            origem_erro="openrouter",
        )

    resultado = executar_contrato(entrada, executor_erro)

    assert resultado.categoria == "indisponibilidade"
    assert resultado.status_http == 429
    assert resultado.origem_erro == "openrouter"


# 6. resposta limitada a 300 caracteres
def test_resposta_e_truncada_em_300_caracteres():
    resposta_longa = "x" * 500
    resultado = ResultadoSanitizado(
        modelo="a/modelo:free",
        status_http=200,
        categoria="sucesso",
        duracao_segundos=1.0,
        numero_tentativas=1,
        fallback_utilizado=False,
        resposta=resposta_longa,
        origem_erro="openrouter",
    )

    assert resultado.resposta is not None
    assert len(resultado.resposta) == 300


# 7. ausência de segredo no resultado
def test_resultado_sanitizado_nunca_contem_campo_de_segredo():
    entrada = _entrada_valida(modo=MODO_DRYRUN)

    def executor_sucesso(_entrada, _obter_escolha_humana):
        return ResultadoSanitizado(
            modelo="a/modelo:free",
            status_http=200,
            categoria="sucesso",
            duracao_segundos=1.0,
            numero_tentativas=1,
            fallback_utilizado=False,
            resposta="resposta sem segredo algum",
            origem_erro="openrouter",
        )

    resultado = executar_contrato(entrada, executor_sucesso)

    campos = {f for f in resultado.__dataclass_fields__}
    termos_proibidos = {"chave", "token", "senha", "credencial", "authorization", "api_key", "secret"}
    assert not (campos & termos_proibidos)
    # também garante que nenhum valor textual contenha os termos proibidos
    valores_textuais = [str(v).lower() for v in (resultado.modelo, resultado.resposta, resultado.categoria, resultado.origem_erro)]
    for termo in termos_proibidos:
        assert not any(termo in v for v in valores_textuais)


# 8. confirmação de que o modo dryrun não usa rede nem credencial
def test_modulo_nao_importa_rede_nem_credencial():
    """Verificação por AST (imports reais do próprio módulo de contrato),
    não por busca textual — evita falso positivo com a prosa do docstring
    que precisa MENCIONAR essas palavras para explicar o que o módulo NÃO
    faz."""
    import ponte_openrouter.harness_contrato as harness_mod

    caminho = pathlib.Path(harness_mod.__file__)
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                nomes.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module.split(".")[0])

    proibidos = {"requests", "urllib", "httpx", "credencial", "executor_real", "notion", "mcp"}
    assert not (nomes & proibidos), f"harness_contrato.py não deveria importar {nomes & proibidos}"

    # e confirma que o caminho dryrun completo roda sem qualquer mock de
    # rede/credencial (se precisasse de rede, falharia aqui por tentativa
    # real de conexão, que este ambiente de teste não permite)
    entrada = _entrada_valida(modo=MODO_DRYRUN)

    def executor_dryrun(_entrada, _obter_escolha_humana):
        return ResultadoSanitizado(
            modelo="a/modelo:free",
            status_http=None,
            categoria="sucesso_simulado",
            duracao_segundos=0.0,
            numero_tentativas=1,
            fallback_utilizado=False,
            resposta="ok",
            origem_erro="nao_aplicavel",
        )

    resultado = executar_contrato(entrada, executor_dryrun)
    assert resultado.categoria == "sucesso_simulado"
