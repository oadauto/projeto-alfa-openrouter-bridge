"""Consulta e filtragem do catálogo público de modelos do OpenRouter.

O endpoint GET /api/v1/models é público e não exige chave de API. Este
módulo nunca lida com a chave de API — isso é responsabilidade exclusiva
de `credencial.py`, usado apenas em `executor.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


CATALOGO_URL = "https://openrouter.ai/api/v1/models"


@dataclass
class ModeloCatalogo:
    id: str
    nome: str
    contexto: int
    descricao: str
    multimodal: bool = False
    provedor: str = field(default="")

    def __post_init__(self) -> None:
        if not self.provedor:
            self.provedor = self.id.split("/", 1)[0] if "/" in self.id else "desconhecido"


def _preco_e_zero(pricing: dict[str, Any]) -> bool:
    try:
        return float(pricing.get("prompt", "1")) == 0.0 and float(pricing.get("completion", "1")) == 0.0
    except (TypeError, ValueError):
        return False


def filtrar_gratuitos(
    modelos_brutos: Iterable[dict[str, Any]],
    excluir_ids: Iterable[str] = (),
) -> list[ModeloCatalogo]:
    """Aplica os filtros já validados manualmente nas Fases F.4-F.7:
    ID terminado em ':free' e preço de entrada/saída numericamente zero.

    `modelos_brutos` é a lista bruta (ex.: `catalogo_json["data"]`) já obtida
    de uma chamada externa a GET /api/v1/models — esta função não faz
    nenhuma chamada de rede; isso é responsabilidade do chamador (mantendo
    este módulo fácil de testar com dados simulados).
    """
    excluidos = set(excluir_ids)
    resultado: list[ModeloCatalogo] = []

    for item in modelos_brutos:
        modelo_id = item.get("id", "")
        if not modelo_id.endswith(":free"):
            continue
        if modelo_id in excluidos:
            continue
        pricing = item.get("pricing", {})
        if not _preco_e_zero(pricing):
            continue

        descricao = item.get("description", "") or ""
        multimodal = "image" in descricao.lower() or "multimodal" in descricao.lower()

        resultado.append(
            ModeloCatalogo(
                id=modelo_id,
                nome=item.get("name", modelo_id),
                contexto=int(item.get("context_length", 0) or 0),
                descricao=descricao,
                multimodal=multimodal,
            )
        )

    return resultado
