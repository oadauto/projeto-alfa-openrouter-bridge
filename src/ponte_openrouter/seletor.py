"""Seleção declarativa de modelo por tipo de tarefa.

As regras vêm de config/selecao_por_tarefa.yaml. Nenhuma decisão aqui é
feita por um LLM - são critérios explícitos e auditáveis.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .catalogo import ModeloCatalogo

CONFIG_PADRAO = Path(__file__).resolve().parent.parent.parent / "config" / "selecao_por_tarefa.yaml"


@dataclass
class Candidato:
    modelo: ModeloCatalogo
    pontuacao: int
    justificativa: list[str]


def carregar_config(caminho: Path = CONFIG_PADRAO) -> dict[str, Any]:
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def selecionar(
    tarefa: str,
    catalogo: list[ModeloCatalogo],
    config: dict[str, Any] | None = None,
) -> list[Candidato]:
    """Ordena o catálogo já filtrado segundo os critérios da tarefa.

    Retorna uma lista de Candidato ordenada da maior para a menor
    pontuação, cada um com a justificativa (lista de strings) de por que
    recebeu aquela pontuação - para ser sempre apresentável a um humano
    antes de qualquer chamada.
    """
    cfg = config or carregar_config()
    tarefas = cfg.get("tarefas", {})
    if tarefa not in tarefas:
        raise ValueError(
            f"Tarefa '{tarefa}' não definida em selecao_por_tarefa.yaml. "
            f"Tarefas disponíveis: {sorted(tarefas.keys())}"
        )

    criterios_lista = tarefas[tarefa].get("criterios", [])
    criterios: dict[str, Any] = {}
    for item in criterios_lista:
        criterios.update(item)

    confirmados = {m["id"] for m in cfg.get("modelos_confirmados", [])}

    candidatos: list[Candidato] = []
    for modelo in catalogo:
        pontuacao = 0
        justificativa: list[str] = []

        contexto_minimo = criterios.get("contexto_minimo")
        if contexto_minimo is not None:
            if modelo.contexto >= contexto_minimo:
                pontuacao += 1
                justificativa.append(f"contexto {modelo.contexto} atende ao mínimo {contexto_minimo}")
            else:
                justificativa.append(f"contexto {modelo.contexto} abaixo do mínimo {contexto_minimo} (não excluído, apenas não pontua)")

        exige_multimodal = criterios.get("multimodal")
        if exige_multimodal is not None:
            if modelo.multimodal == exige_multimodal:
                pontuacao += 1
                justificativa.append(f"multimodal={modelo.multimodal} corresponde ao exigido")

        if criterios.get("preferir_confirmados") and modelo.id in confirmados:
            pontuacao += 2
            justificativa.append("modelo já confirmado como funcional em teste anterior do Projeto ALFA")

        evitar = set(criterios.get("evitar_provedores", []) or [])
        if modelo.provedor in evitar:
            pontuacao -= 2
            justificativa.append(f"provedor '{modelo.provedor}' está na lista de provedores a evitar")

        candidatos.append(Candidato(modelo=modelo, pontuacao=pontuacao, justificativa=justificativa))

    candidatos.sort(key=lambda c: c.pontuacao, reverse=True)
    return candidatos
