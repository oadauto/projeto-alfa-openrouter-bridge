"""Script mínimo de linha de comando para o primeiro teste REAL da ponte.

Uso:
    python scripts/teste_real_ponte.py nvidia/nemotron-3.5-lightning:free

Exige confirmação explícita (digitar 's') antes de fazer a única chamada
real. Nunca imprime a chave. Nunca faz mais de uma chamada. Nunca tenta
outro modelo automaticamente em caso de falha.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ponte_openrouter.executor_real import executar_chamada_real  # noqa: E402


PROMPT_FICTICIO = (
    "Teste real e mínimo da ponte do Projeto ALFA, fictício e sem dados reais: "
    "descreva em uma frase o que é um modelo de linguagem de propósito geral."
)


def main() -> None:
    if len(sys.argv) != 2:
        print("Uso: python scripts/teste_real_ponte.py <modelo_id>")
        sys.exit(1)

    modelo_id = sys.argv[1]

    print(f"Modelo a testar: {modelo_id}")
    print(f"Prompt (fictício, sem dados reais): {PROMPT_FICTICIO}")
    resposta = input("Confirma UMA chamada real a este modelo agora? (s/n): ").strip().lower()

    if resposta != "s":
        print("Não autorizado. Nenhuma chamada foi feita.")
        sys.exit(0)

    resultado = executar_chamada_real(modelo_id, PROMPT_FICTICIO, confirmar_execucao=True)

    print(f"\nModelo: {resultado.modelo_id}")
    print(f"Código HTTP: {resultado.codigo_http}")
    print(f"Categoria: {resultado.categoria}")
    print(f"Mensagem: {resultado.mensagem}")
    if resultado.resposta_paráfrase:
        print(f"Trecho da resposta (até 300 caracteres): {resultado.resposta_paráfrase}")


if __name__ == "__main__":
    main()
