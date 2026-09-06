"""Minimizador de contexto.

Nesta versão, este módulo NÃO acessa o Notion diretamente - recebe um
resumo já pronto (string), preparado fora deste código (curadoria manual,
como em todas as fases anteriores do Projeto ALFA). Isso evita introduzir
uma nova permissão/chamada automática sem aprovação explícita separada.
"""

from __future__ import annotations

LIMITE_CARACTERES_PADRAO = 2000


def montar_contexto_minimo(resumo_curado: str, limite_caracteres: int = LIMITE_CARACTERES_PADRAO) -> str:
    """Valida e corta (se necessário) um resumo já curado manualmente.

    Nunca aceita um texto que pareça ser uma transcrição completa (uso de
    um heurístico simples de tamanho) - isso não substitui a curadoria
    humana, apenas adiciona uma salvaguarda extra.
    """
    if not resumo_curado or not resumo_curado.strip():
        raise ValueError("Resumo curado vazio - não é permitido montar contexto sem conteúdo mínimo definido.")

    texto = resumo_curado.strip()

    if len(texto) > limite_caracteres:
        raise ValueError(
            f"Resumo curado excede {limite_caracteres} caracteres ({len(texto)} recebidos). "
            "Isso sugere uma transcrição completa em vez de um resumo mínimo - revise antes de prosseguir."
        )

    return texto
