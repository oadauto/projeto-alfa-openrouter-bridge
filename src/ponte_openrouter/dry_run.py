"""Ponto de entrada principal desta etapa: roda o fluxo completo em modo
seguro (dry-run), sem nunca alcançar uma chamada de rede real.

Uso (exemplo):
    python -m ponte_openrouter.dry_run
"""

from __future__ import annotations

from . import catalogo as catalogo_mod
from . import seletor as seletor_mod
from . import autorizacao as autorizacao_mod
from . import contexto as contexto_mod
from . import executor as executor_mod


def rodar(
    tarefa: str,
    modelos_brutos: list[dict],
    resumo_curado: str,
    obter_escolha_humana=None,
) -> str:
    """Executa o fluxo completo em modo dry-run e devolve a mensagem final.

    `modelos_brutos` é a lista já obtida de uma chamada externa a
    GET /api/v1/models (este módulo não faz a chamada de rede em si - isso
    mantém o fluxo inteiro testável com dados simulados).
    """
    catalogo_filtrado = catalogo_mod.filtrar_gratuitos(modelos_brutos)
    if not catalogo_filtrado:
        return "Nenhum candidato gratuito disponível no catálogo fornecido."

    candidatos = seletor_mod.selecionar(tarefa, catalogo_filtrado)
    decisao = autorizacao_mod.confirmar(candidatos, obter_escolha_humana=obter_escolha_humana)

    if not decisao.autorizado:
        return f"Fluxo interrompido: {decisao.motivo}. Nenhuma chamada foi simulada."

    contexto_min = contexto_mod.montar_contexto_minimo(resumo_curado)
    resultado = executor_mod.executar_dryrun(decisao.candidato_escolhido.modelo.id, contexto_min)
    return resultado.mensagem


if __name__ == "__main__":
    print(
        "Este ponto de entrada requer uma lista de modelos (catálogo bruto) e "
        "um resumo curado como entrada programática - ver tests/ para exemplos "
        "de uso com dados simulados. Nenhuma chamada de rede é feita por este módulo."
    )
