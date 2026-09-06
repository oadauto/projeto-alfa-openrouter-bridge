"""Portão de autorização humana.

Nenhuma chamada real (fora do modo dry-run) pode ocorrer sem que
`confirmar()` retorne um candidato explicitamente escolhido pelo usuário.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .seletor import Candidato


@dataclass
class DecisaoAutorizacao:
    autorizado: bool
    candidato_escolhido: Candidato | None
    motivo: str


def apresentar_candidatos(candidatos: list[Candidato]) -> str:
    """Monta o texto de apresentação (provedor, custo, capacidades,
    limitações) no mesmo formato usado manualmente nas Fases F.4-F.7.
    """
    linhas = []
    for i, c in enumerate(candidatos, start=1):
        linhas.append(
            f"{i}. {c.modelo.id} (provedor: {c.modelo.provedor}, custo: gratuito, "
            f"contexto: {c.modelo.contexto}, pontuação: {c.pontuacao})\n"
            f"   Justificativa: {'; '.join(c.justificativa) if c.justificativa else 'sem critérios aplicáveis'}"
        )
    return "\n".join(linhas)


def confirmar(
    candidatos: list[Candidato],
    obter_escolha_humana: Callable[[str], str] | None = None,
) -> DecisaoAutorizacao:
    """Exige confirmação humana explícita antes de liberar qualquer chamada.

    `obter_escolha_humana` é injetável para testes (nunca usa `input()`
    real durante os testes automatizados). Em uso real via CLI, o padrão
    é `input`.
    """
    if not candidatos:
        return DecisaoAutorizacao(autorizado=False, candidato_escolhido=None, motivo="nenhum candidato disponível")

    pedir = obter_escolha_humana or input
    texto = apresentar_candidatos(candidatos)
    resposta = pedir(
        f"{texto}\n\nAutoriza chamar algum destes modelos? "
        f"Digite o número do candidato, ou 'n' para não autorizar: "
    ).strip().lower()

    if resposta in ("n", "nao", "não", ""):
        return DecisaoAutorizacao(autorizado=False, candidato_escolhido=None, motivo="usuário não autorizou")

    try:
        indice = int(resposta) - 1
        escolhido = candidatos[indice]
    except (ValueError, IndexError):
        return DecisaoAutorizacao(autorizado=False, candidato_escolhido=None, motivo=f"resposta inválida: '{resposta}'")

    return DecisaoAutorizacao(autorizado=True, candidato_escolhido=escolhido, motivo="autorizado explicitamente pelo usuário")
