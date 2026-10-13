"""Verificador de segredos e de higiene do repositório — Projeto ALFA.

Usado pelo workflow `.github/workflows/seguranca.yml` e executável
localmente. Sem dependências além da biblioteca padrão e do `git`.

O que faz (somente leitura; nenhuma rede; nenhuma credencial):

1. Varre as linhas dos arquivos RASTREADOS pelo git (`git ls-files`) em
   busca de padrões de credencial conhecidos. Arquivos não rastreados nunca
   são abertos - em particular `scripts/executar_orquestrador.py` e
   `catalogo*.json`, que são locais e também estão excluídos por caminho.
2. Com `--historico BASE`, varre também as linhas ADICIONADAS por cada
   commit do intervalo `BASE..HEAD` (pega um segredo inserido e removido
   num commit seguinte do mesmo PR).
3. Falha se algum caminho proibido estiver rastreado (`catalogo*.json`,
   `logs/*.jsonl`, `.env*`, chaves privadas): são dados locais que não
   pertencem ao repositório.

Garantia de saída: este script NUNCA imprime o conteúdo de uma linha, o
trecho que casou nem qualquer valor. Só imprime `caminho:linha [padrão]`
(ou `commit:caminho [padrão]`) e contagens. Assim, mesmo que encontre um
segredo de verdade, o log do CI não o expõe.

Linha deliberadamente fictícia (ex.: em teste) pode conter o marcador
`alfa-allow-secret`; use com parcimônia e só para valores comprovadamente
falsos. Os testes do projeto montam seus valores falsos em tempo de execução
para não precisar do marcador.

Códigos de saída: 0 sem achados; 1 achados; 2 erro de uso/execução.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

MARCADOR_PERMITIDO = "alfa-allow-secret"
TAMANHO_MAXIMO_BYTES = 1_000_000

# Nome do padrão -> regex. Os nomes são o único texto que vai para a saída.
PADROES: dict[str, re.Pattern[str]] = {
    "chave_openrouter": re.compile(r"sk-or-(?:v1-)?[A-Za-z0-9]{32,}"),
    "chave_anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "chave_estilo_openai": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}"),
    "token_github": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"),
    "chave_aws": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "chave_google": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "token_slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    "chave_privada": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY"),
    "bearer_literal": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*"),
    "atribuicao_de_segredo": re.compile(
        r"""(?ix)\b(?:api[_-]?key|secret|token|passwd|password|senha)\w*\s*[:=]\s*["'][A-Za-z0-9_\-./+=]{16,}["']"""
    ),
}

# Caminhos que nunca devem estar rastreados (fnmatch, sobre o caminho com "/").
CAMINHOS_PROIBIDOS = (
    "catalogo*.json",
    "*/catalogo*.json",
    "logs/*.jsonl",
    "*/logs/*.jsonl",
    ".env",
    ".env.*",
    "*/.env",
    "*/.env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
)

# Nunca abertos, mesmo se um dia forem rastreados (locais, decisão de Adauto).
CAMINHOS_NAO_ABRIR = (
    "scripts/executar_orquestrador.py",
    "catalogo*.json",
    "*/catalogo*.json",
)


def _casa(caminho: str, padroes: tuple[str, ...]) -> bool:
    nome = caminho.replace("\\", "/")
    return any(fnmatch.fnmatch(nome, p) for p in padroes)


def escanear_texto(texto: str) -> list[tuple[int, str]]:
    """Devolve `[(numero_da_linha, nome_do_padrao)]`. Não devolve conteúdo."""
    achados: list[tuple[int, str]] = []
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if MARCADOR_PERMITIDO in linha:
            continue
        for nome, regex in PADROES.items():
            if regex.search(linha):
                achados.append((numero, nome))
    return achados


def _ler_texto(caminho: Path) -> str | None:
    try:
        if caminho.stat().st_size > TAMANHO_MAXIMO_BYTES:
            return None
        dados = caminho.read_bytes()
    except OSError:
        return None
    if b"\x00" in dados:  # binário
        return None
    return dados.decode("utf-8", errors="replace").lstrip("﻿")


def _git(raiz: Path, *args: str) -> bytes:
    processo = subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, check=False)
    if processo.returncode != 0:
        raise RuntimeError(f"git {args[0]} falhou (código {processo.returncode})")
    return processo.stdout


def arquivos_rastreados(raiz: Path) -> list[str]:
    saida = _git(raiz, "ls-files", "-z")
    return [p.decode("utf-8", errors="replace") for p in saida.split(b"\0") if p]


def caminhos_proibidos_rastreados(rastreados: list[str]) -> list[str]:
    return [p for p in rastreados if _casa(p, CAMINHOS_PROIBIDOS)]


def escanear_arvore(raiz: Path, rastreados: list[str]) -> list[tuple[str, int, str]]:
    achados: list[tuple[str, int, str]] = []
    for caminho in rastreados:
        if _casa(caminho, CAMINHOS_NAO_ABRIR):
            continue
        texto = _ler_texto(raiz / caminho)
        if texto is None:
            continue
        achados.extend((caminho, n, nome) for n, nome in escanear_texto(texto))
    return achados


def escanear_historico(raiz: Path, base: str) -> list[tuple[str, str, str]]:
    """Linhas ADICIONADAS em `base..HEAD`. Devolve `(commit_curto, caminho, padrao)`."""
    saida = _git(raiz, "log", "-p", "--no-color", "--no-ext-diff", "--format=@@COMMIT@@%h", f"{base}..HEAD")
    texto = saida.decode("utf-8", errors="replace")
    achados: list[tuple[str, str, str]] = []
    commit, caminho = "?", "?"
    vistos: set[tuple[str, str, str]] = set()
    for linha in texto.splitlines():
        if linha.startswith("@@COMMIT@@"):
            commit = linha[len("@@COMMIT@@"):]
        elif linha.startswith("+++ "):
            alvo = linha[4:]
            caminho = alvo[2:] if alvo.startswith("b/") else alvo
        elif linha.startswith("+") and not linha.startswith("+++"):
            if _casa(caminho, CAMINHOS_NAO_ABRIR):
                continue
            for _numero, nome in escanear_texto(linha[1:]):
                chave = (commit, caminho, nome)
                if chave not in vistos:
                    vistos.add(chave)
                    achados.append(chave)
    return achados


def _argumentos(argv: list[str]) -> tuple[Path, str | None]:
    raiz = Path(__file__).resolve().parent.parent
    base = None
    i = 0
    while i < len(argv):
        if argv[i] == "--historico" and i + 1 < len(argv):
            base = argv[i + 1]
            i += 2
        elif argv[i] == "--raiz" and i + 1 < len(argv):
            raiz = Path(argv[i + 1]).resolve()
            i += 2
        else:
            raise ValueError("uso: verificar_segredos.py [--historico BASE_REF] [--raiz CAMINHO]")
    return raiz, base


def main(argv: list[str] | None = None) -> int:
    try:
        raiz, base = _argumentos(sys.argv[1:] if argv is None else argv)
        rastreados = arquivos_rastreados(raiz)
        proibidos = caminhos_proibidos_rastreados(rastreados)
        achados = escanear_arvore(raiz, rastreados)
        historico = escanear_historico(raiz, base) if base else []
    except (ValueError, RuntimeError, OSError) as exc:
        # Mensagem fixa por tipo; nunca ecoa conteúdo de arquivo.
        print(f"ERRO: {type(exc).__name__} - verificação não concluída.")
        return 2

    for caminho in proibidos:
        print(f"PROIBIDO-RASTREADO: {caminho}")
    for caminho, linha, nome in achados:
        print(f"SEGREDO-SUSPEITO: {caminho}:{linha} [{nome}]")
    for commit, caminho, nome in historico:
        print(f"SEGREDO-SUSPEITO-NO-HISTORICO: {commit} {caminho} [{nome}]")

    total = len(proibidos) + len(achados) + len(historico)
    print(
        f"arquivos_rastreados={len(rastreados)} proibidos={len(proibidos)} "
        f"suspeitos={len(achados)} historico={len(historico)}"
    )
    if total:
        print("FALHA: revise os itens acima (o conteúdo não é impresso de propósito).")
        return 1
    print("OK: nenhum segredo suspeito nem caminho proibido rastreado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
