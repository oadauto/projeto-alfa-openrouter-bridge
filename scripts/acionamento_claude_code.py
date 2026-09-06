"""Teste mínimo de acionamento da ponte pelo Claude Code — modo dry-run.

Este script existe apenas para comprovar que o fluxo já validado
(catálogo -> seleção -> portão de autorização -> simulação) pode ser
acionado de ponta a ponta, sem depender de nenhum dado ou serviço externo.

Restrições estruturais (não apenas comportamentais — verificadas também
por tests/test_acionamento_claude_code.py):
- NÃO importa `credencial` nem `executor_real` (portanto não pode, em
  nenhuma hipótese, tocar a chave de API real);
- NÃO importa `requests`, `urllib` nem `httpx` (nenhuma chamada de rede
  é sequer possível a partir deste arquivo);
- usa um catálogo FICTÍCIO, embutido no próprio script — não consulta o
  OpenRouter real;
- NÃO acessa o Notion (não há nenhum código de leitura/escrita ao Notion
  aqui);
- NÃO cria nenhum arquivo de log;
- exige confirmação humana explícita antes de "simular" a chamada;
- executa uma única vez e termina — sem loop, sem menu, sem retry.

Uso:
    python scripts\\acionamento_claude_code.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ponte_openrouter import dry_run  # noqa: E402


# Catálogo fictício, embutido — não é uma chamada real a GET /api/v1/models.
CATALOGO_FICTICIO = [
    {
        "id": "ficticio/modelo-continuidade:free",
        "name": "Modelo Fictício de Continuidade (teste de acionamento)",
        "context_length": 128000,
        "description": "Modelo inteiramente fictício, usado apenas para testar o "
                        "acionamento da ponte pelo Claude Code. Não existe de verdade "
                        "no catálogo do OpenRouter.",
        "pricing": {"prompt": "0", "completion": "0"},
    },
]

RESUMO_CURADO_FICTICIO = (
    "Resumo mínimo e fictício, para teste de acionamento da ponte pelo Claude Code. "
    "Nenhum dado real do Notion ou de qualquer conversa foi usado aqui."
)


def confirmar_via_terminal(mensagem: str) -> str:
    return input(mensagem)


def main() -> None:
    print("=== Teste de acionamento da ponte pelo Claude Code (modo dry-run) ===")
    print("Catálogo: fictício e embutido neste script (nenhuma chamada real ao OpenRouter).")
    print("Contexto: resumo fictício embutido (nenhum acesso ao Notion).")
    print()

    resultado = dry_run.rodar(
        tarefa="continuidade_critica",
        modelos_brutos=CATALOGO_FICTICIO,
        resumo_curado=RESUMO_CURADO_FICTICIO,
        obter_escolha_humana=confirmar_via_terminal,
    )

    print()
    print(f"Resultado: {resultado}")
    print()
    print("Execução única concluída. Nenhuma chamada de rede foi feita. "
          "Nenhum arquivo de log foi criado. Nenhum dado foi registrado no Notion.")


if __name__ == "__main__":
    main()
