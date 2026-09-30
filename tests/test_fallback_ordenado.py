"""Teste do fluxo simulado A -> B -> C (formalização da simulação de mesa da OR.6).

IMPORTANTE (ver relatório OR.8, item "limitações"): o pacote atual NÃO
possui uma função de orquestração de fallback ordenado com pausa humana
entre tentativas — ela não existe como peça única de código (confirmado
na auditoria OR.6/OR.7). Este teste, portanto, NÃO testa uma função
`fallback_ordenado()` real (ela não existe), e sim COMPÕE manualmente,
dentro do próprio teste, os componentes já existentes (`executor.
classificar_http`, `autorizacao.confirmar`) para verificar que, SE essa
composição fosse feita da forma descrita na OR.6, o comportamento seria o
esperado. Isto é deliberadamente marcado como uma simulação dentro do
teste, não como uma prova de que o produto final já se comporta assim
em produção.
"""
from __future__ import annotations

from ponte_openrouter.catalogo import ModeloCatalogo
from ponte_openrouter.seletor import Candidato
from ponte_openrouter.executor import classificar_http
from ponte_openrouter.autorizacao import confirmar, apresentar_candidatos


def _candidato(id_, pontuacao):
    return Candidato(
        modelo=ModeloCatalogo(id=id_, nome=id_, contexto=128000, descricao=""),
        pontuacao=pontuacao,
        justificativa=[],
    )


def test_fluxo_simulado_a_indisponivel_b_indisponivel_c_selecionado_com_aviso_humano():
    candidato_a = _candidato("modelo/a:free", pontuacao=3)
    candidato_b = _candidato("modelo/b:free", pontuacao=2)
    candidato_c = _candidato("modelo/c:free", pontuacao=1)
    candidatos_ordenados = [candidato_a, candidato_b, candidato_c]

    # Passo 1-2: A indisponível (simulação de HTTP 429, sem chamada real)
    categoria_a = classificar_http(429)
    assert categoria_a == "indisponibilidade"

    # Passo 3-4: B também indisponível
    categoria_b = classificar_http(429)
    assert categoria_b == "indisponibilidade"

    # Passo 5: C é o próximo da lista ordenada -> tratado como candidato a apresentar
    candidatos_restantes = [
        c for c in candidatos_ordenados if c.modelo.id not in {candidato_a.modelo.id, candidato_b.modelo.id}
    ]
    assert candidatos_restantes == [candidato_c], "apenas C deve restar após descartar A e B"

    # Passo 6: aviso humano é apresentado ANTES de qualquer migração/decisão
    texto_aviso = apresentar_candidatos(candidatos_restantes)
    assert candidato_c.modelo.id in texto_aviso

    # Passo 7: confirmação humana explícita, escolhendo o único candidato restante (índice 1)
    respostas_simuladas = iter(["1"])
    decisao = confirmar(candidatos_restantes, obter_escolha_humana=lambda _: next(respostas_simuladas))

    assert decisao.autorizado is True
    assert decisao.candidato_escolhido.modelo.id == "modelo/c:free"
    # Encerramento: nenhuma chamada real é feita neste teste - nenhum
    # import de `executor_real` ou `requests` ocorre neste arquivo.


def test_ausencia_de_candidato_disponivel_apos_todos_indisponiveis_nao_autoriza_nada():
    candidato_a = _candidato("modelo/a:free", pontuacao=3)

    categoria_a = classificar_http(429)
    assert categoria_a == "indisponibilidade"

    # Todos os candidatos foram descartados - lista vazia chega à autorização
    decisao = confirmar([], obter_escolha_humana=lambda _: "1")

    assert decisao.autorizado is False
    assert "nenhum candidato disponível" in decisao.motivo


def test_recusa_humana_no_ultimo_candidato_nao_autoriza_migracao():
    candidato_c = _candidato("modelo/c:free", pontuacao=1)

    decisao = confirmar([candidato_c], obter_escolha_humana=lambda _: "n")

    assert decisao.autorizado is False, "recusa humana deve impedir a migração mesmo com um único candidato"
