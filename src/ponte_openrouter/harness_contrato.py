"""Contrato mínimo do harness — Projeto ALFA, Fase 1.

Define o contrato de dados e de responsabilidades entre três partes,
sem implementar nenhuma integração real com nenhuma delas:

- **Claude/Cowork**: orquestração geral - decide quando invocar o harness
  e recebe o `ResultadoSanitizado` final. Não seleciona candidatos nem
  executa chamadas diretamente.
- **ALFA** (o orquestrador local, ex.: `ponte_openrouter.orquestrador`):
  responsável pela seleção de candidatos, pelo portão de autorização
  humana e pela execução em si (dry-run ou real). É a única parte que
  pode produzir um `ResultadoSanitizado` com `origem_erro="openrouter"`.
- **ChatGPT/Codex**: consulta o resultado, valida de forma independente,
  e produz relatório. NUNCA executa chamadas reais - `validar_papel()`
  abaixo barra isso explicitamente, como parte do próprio contrato, não
  apenas como uma convenção documentada.

Este módulo é puramente um contrato: dataclasses, constantes e funções de
validação/composição. Não faz nenhuma chamada de rede, não importa
`requests`/`credencial`/`executor_real`, e não decide fallback por conta
própria - fallback só existe se o `executor` injetado (ex.:
`orquestrador.orquestrar`) decidir e reportar isso explicitamente no
campo `fallback_utilizado`, nunca de forma silenciosa.

Fora de escopo desta Fase 1 (propositalmente): nenhuma integração real
com Claude, ChatGPT ou Gemini; nenhuma leitura/escrita no Notion; nenhuma
alteração no comportamento atual da ponte OpenRouter (`seletor.py`,
`executor.py`, `executor_real.py`, `orquestrador.py` permanecem
intocados). Este módulo pode ser usado como uma camada de composição
sobre eles em uma fase futura, mas não os importa nem os modifica aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


MODO_DRYRUN = "dryrun"
MODO_REAL = "real"
MODOS_VALIDOS = (MODO_DRYRUN, MODO_REAL)

# Item 6 do contrato: vocabulário fechado de erros previsíveis. Uma
# categoria fora deste conjunto é rejeitada na construção do resultado -
# nunca inferida ou inventada.
CATEGORIAS_ERRO_PREVISIVEIS = frozenset(
    {
        "sucesso",
        "problema_de_credencial",  # equivalente a HTTP 401
        "restricao_de_acesso",  # equivalente a HTTP 403
        "indisponibilidade",  # equivalente a HTTP 429 ou 5xx
        "nao_classificado",  # código HTTP fora do mapa conhecido
        "recusado_pelo_humano",  # aprovação negada antes de qualquer tentativa
        "nao_executado",  # modo=real sem confirmar_execucao
        "sucesso_simulado",  # resultado do caminho dry-run
    }
)

# Origens de erro previstas (ver relatório OR.9, item 9 - o mesmo
# vocabulário é reafirmado aqui como parte do contrato formal).
ORIGENS_ERRO_PREVISTAS = frozenset(
    {
        "openrouter",  # a tentativa de fato chegou a executor/executor_real
        "nao_aplicavel",  # dry-run, ou recusa humana antes de qualquer tentativa
        "chatgpt_openai",  # falha do lado do cliente ChatGPT/Codex, nunca atribuída aqui
        "claude_sessao",  # limitação do ambiente de execução do Claude/Cowork
    }
)

# Item 7 do contrato: responsabilidades fixas. ChatGPT/Codex nunca recebe
# o papel de execução real - isso é reforçado em código por
# `validar_papel_execucao_real()`, não apenas descrito em prosa.
PAPEIS = {
    "claude": "orquestracao",
    "alfa": "selecao_autorizacao_execucao",
    "chatgpt_codex": "consulta_validacao_relatorio",
}

PAPEIS_PERMITIDOS_PARA_EXECUCAO_REAL = frozenset({"alfa"})


class EntradaInvalidaError(ValueError):
    """Levantado quando uma EntradaTarefa não passa em validar()."""


class AprovacaoAusenteError(PermissionError):
    """Levantado quando modo='real' é solicitado sem aprovação humana explícita."""


class PapelNaoAutorizadoError(PermissionError):
    """Levantado quando uma parte tenta um papel que o contrato não permite a ela."""


@dataclass(frozen=True)
class EntradaTarefa:
    """Item 1 do contrato: entrada de uma tarefa.

    `modelos_brutos` é a lista já obtida do catálogo (nenhuma chamada de
    rede é feita por este módulo para obtê-la).
    """

    tarefa: str
    modelos_brutos: tuple[dict, ...]
    resumo_curado: str
    modo: str = MODO_DRYRUN

    def validar(self) -> None:
        if not self.tarefa or not self.tarefa.strip():
            raise EntradaInvalidaError("EntradaTarefa.tarefa não pode ser vazia.")
        if self.modo not in MODOS_VALIDOS:
            raise EntradaInvalidaError(
                f"modo inválido: {self.modo!r}. Use um de {MODOS_VALIDOS}."
            )
        if not self.resumo_curado or not self.resumo_curado.strip():
            raise EntradaInvalidaError("EntradaTarefa.resumo_curado não pode ser vazio.")
        if self.modo == MODO_REAL and not self.modelos_brutos:
            raise EntradaInvalidaError(
                "modo='real' exige ao menos um candidato em modelos_brutos."
            )


@dataclass(frozen=True)
class CandidatoContrato:
    """Item 2 do contrato: um candidato dentro da lista ordenada.

    Formato mínimo e deliberadamente simples - não depende de
    `ponte_openrouter.seletor.Candidato` para que este contrato possa,
    no futuro, ser reaproveitado por outra integração além do OpenRouter.
    """

    modelo_id: str
    pontuacao: int
    provedor: str = ""


def construir_lista_ordenada(candidatos: list[CandidatoContrato]) -> tuple[CandidatoContrato, ...]:
    """Item 2 do contrato: ordena por pontuação decrescente, de forma
    determinística (ordenação estável do Python - empates preservam a
    ordem de entrada)."""
    return tuple(sorted(candidatos, key=lambda c: c.pontuacao, reverse=True))


@dataclass
class ResultadoSanitizado:
    """Item 5 do contrato: resultado sanitizado devolvido pelo harness.

    Nunca contém chave, token ou cabeçalho de autorização - apenas os
    campos explicitamente listados no contrato. `resposta` é sempre
    truncada a `LIMITE_RESPOSTA_CARACTERES` caracteres na construção.
    """

    LIMITE_RESPOSTA_CARACTERES = 300

    modelo: str | None
    status_http: int | None
    categoria: str
    duracao_segundos: float | None
    numero_tentativas: int
    fallback_utilizado: bool
    resposta: str | None
    origem_erro: str

    def __post_init__(self) -> None:
        if self.categoria not in CATEGORIAS_ERRO_PREVISIVEIS:
            raise EntradaInvalidaError(
                f"categoria não prevista pelo contrato: {self.categoria!r}. "
                f"Categorias previstas: {sorted(CATEGORIAS_ERRO_PREVISIVEIS)}"
            )
        if self.origem_erro not in ORIGENS_ERRO_PREVISTAS:
            raise EntradaInvalidaError(
                f"origem_erro não prevista pelo contrato: {self.origem_erro!r}. "
                f"Origens previstas: {sorted(ORIGENS_ERRO_PREVISTAS)}"
            )
        if self.numero_tentativas < 0:
            raise EntradaInvalidaError("numero_tentativas não pode ser negativo.")
        if self.fallback_utilizado and self.numero_tentativas < 2:
            # Item 7: "nenhum fallback silencioso" - se houve fallback,
            # tem que ter havido mais de uma tentativa, por definição.
            raise EntradaInvalidaError(
                "fallback_utilizado=True exige numero_tentativas >= 2 "
                "(fallback silencioso com uma única tentativa não é permitido pelo contrato)."
            )
        if self.resposta is not None and len(self.resposta) > self.LIMITE_RESPOSTA_CARACTERES:
            self.resposta = self.resposta[: self.LIMITE_RESPOSTA_CARACTERES]


class ExecutorContrato(Protocol):
    """Item 3/4 do contrato: assinatura que qualquer executor real (ex.:
    uma futura camada sobre `orquestrador.orquestrar`) deve respeitar
    para ser usado com `executar_contrato()`."""

    def __call__(
        self,
        entrada: EntradaTarefa,
        obter_escolha_humana: Callable[[str], str] | None,
    ) -> ResultadoSanitizado: ...


def validar_papel_execucao_real(papel: str) -> None:
    """Item 7 do contrato: barra explicitamente qualquer papel que não
    seja 'alfa' de executar chamadas reais - em especial, ChatGPT/Codex
    nunca pode assumir este papel, mesmo que solicitado."""
    if papel not in PAPEIS:
        raise PapelNaoAutorizadoError(
            f"papel desconhecido: {papel!r}. Papéis previstos: {sorted(PAPEIS)}"
        )
    if papel not in PAPEIS_PERMITIDOS_PARA_EXECUCAO_REAL:
        raise PapelNaoAutorizadoError(
            f"o papel {papel!r} ({PAPEIS[papel]}) não está autorizado a executar "
            f"chamadas reais - apenas {sorted(PAPEIS_PERMITIDOS_PARA_EXECUCAO_REAL)} "
            f"pode fazê-lo, sempre sob aprovação humana explícita."
        )


def aprovar_modo_real(modo: str, aprovado_por_humano: bool) -> None:
    """Item 4 do contrato: nenhuma execução em modo='real' sem aprovação
    humana explícita - este é o único portão, e é obrigatório mesmo que
    o `executor` injetado também implemente seu próprio portão (defesa
    em profundidade, mesmo princípio já usado em `orquestrador.py`)."""
    if modo == MODO_REAL and not aprovado_por_humano:
        raise AprovacaoAusenteError(
            "modo='real' exige aprovação humana explícita antes de qualquer execução - "
            "nenhuma execução real ocorreu."
        )


def executar_contrato(
    entrada: EntradaTarefa,
    executor: ExecutorContrato,
    *,
    papel_executor: str = "alfa",
    obter_escolha_humana: Callable[[str], str] | None = None,
    aprovado_por_humano: bool = False,
) -> ResultadoSanitizado:
    """Ponto único de entrada do contrato: valida a entrada, valida o
    papel de quem executaria, aplica o portão de aprovação humana, e só
    então delega ao `executor` injetado (nunca implementado aqui - este
    módulo não executa nada real ou simulado por si só, apenas garante o
    contrato ao redor de quem executa).
    """
    entrada.validar()
    validar_papel_execucao_real(papel_executor) if entrada.modo == MODO_REAL else None
    aprovar_modo_real(entrada.modo, aprovado_por_humano)
    return executor(entrada, obter_escolha_humana)
