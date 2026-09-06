"""Executor + classificador de resultado.

Trata explicitamente os códigos HTTP 200, 401, 403, 429 e 5xx. Nunca
inventa uma categoria para um código não mapeado - nesse caso, devolve
"nao_classificado" e exige decisão humana, no mesmo espírito do tratamento
dado ao HTTP 403 observado no teste F.7.1 do Projeto ALFA.

Esta versão NÃO faz nenhuma chamada de rede real. `executar_dryrun()` é o
único ponto de entrada disponível nesta etapa. Uma futura `executar_real()`
(fora do escopo desta versão) usaria `credencial.py` e uma chamada HTTP de
verdade, mas somente atrás do portão de autorização.
"""

from __future__ import annotations

from dataclasses import dataclass


CATEGORIAS_HTTP = {
    200: "sucesso",
    401: "problema_de_credencial",
    403: "restricao_de_acesso",
    429: "indisponibilidade",
}


def classificar_http(codigo: int) -> str:
    if codigo in CATEGORIAS_HTTP:
        return CATEGORIAS_HTTP[codigo]
    if 500 <= codigo < 600:
        return "indisponibilidade"
    return "nao_classificado"


@dataclass
class ResultadoSimulado:
    modelo_id: str
    modo: str
    mensagem: str


def executar_dryrun(modelo_id: str, contexto_minimo: str) -> ResultadoSimulado:
    """Simula a execução: nunca faz uma chamada de rede real.

    `contexto_minimo` é validado (não pode ser vazio) para que o fluxo
    simulado espelhe fielmente o fluxo real que será implementado depois.
    """
    if not contexto_minimo or not contexto_minimo.strip():
        raise ValueError("contexto_minimo vazio - o fluxo real também exigiria isso.")

    return ResultadoSimulado(
        modelo_id=modelo_id,
        modo="dry-run",
        mensagem=f"SIMULAÇÃO: chamaria '{modelo_id}' agora, com contexto mínimo de {len(contexto_minimo)} caracteres. Nenhuma chamada real foi feita.",
    )
