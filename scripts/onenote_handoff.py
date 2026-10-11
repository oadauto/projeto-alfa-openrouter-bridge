"""Hash e handoff idempotente do conector OneNote - Projeto ALFA, S-22.

Este modulo NAO le o OneNote, NAO escreve no OneNote e NAO fala com o Notion:
recebe o texto de UMA pagina ja lida (com autorizacao), calcula so metadados
(hash, tamanho, truncamento) e descarta o texto. O handoff devolvido tem
apenas metadados; o texto nunca e armazenado nem impresso.

Regras (forma canonica v1):
- hash SHA-256, hexadecimal minusculo, sobre texto Unicode NFC em UTF-8 sem BOM;
- quebras de linha -> "\\n", sem espacos no fim de cada linha, sem linhas
  vazias no fim;
- leitura limitada a LIMITE_CARACTERES; acima disso o hash e "hash_parcial"
  (nunca comparado com "hash_completo");
- identidade: "onenote|<page_id>"; versao: page_id + modified_at_utc + hash;
- mesmo hash (mesmo tipo) -> atualiza a verificacao do handoff existente;
  hash diferente -> acrescenta versao ao MESMO handoff; mais de um handoff
  para a mesma identidade -> HandoffAmbiguo (parar e perguntar).
"""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from datetime import datetime, timezone

FORMA_CANONICA = "v1"
LIMITE_CARACTERES = 20_000
LIMITE_RESUMO = 200
HASH_COMPLETO = "hash_completo"
HASH_PARCIAL = "hash_parcial"
ESTADOS = {"ok", "instavel", "nao_encontrada", "sem_permissao", "nao_textual"}


class HandoffAmbiguo(ValueError):
    """Mais de um handoff para a mesma identidade."""


def canonizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto.lstrip("﻿"))
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    linhas = [linha.rstrip() for linha in texto.split("\n")]
    return "\n".join(linhas).rstrip("\n")


def calcular_hash(texto: str, limite: int = LIMITE_CARACTERES) -> dict:
    """Devolve SOMENTE metadados do texto; o texto nao sai desta funcao."""
    total = len(texto)
    truncado = total > limite
    canonico = canonizar_texto(texto[:limite] if truncado else texto)
    digest = hashlib.sha256(canonico.encode("utf-8")).hexdigest()
    return {
        "hash": digest,
        "tipo_hash": HASH_PARCIAL if truncado else HASH_COMPLETO,
        "truncado": truncado,
        "caracteres_lidos": min(total, limite),
        "caracteres_totais": total,
        "forma_canonica": FORMA_CANONICA,
    }


def _page_id(page_id: str) -> str:
    if not isinstance(page_id, str) or not page_id.strip():
        raise ValueError("page_id ausente")
    return page_id.strip()


def chave_identidade(page_id: str) -> str:
    return f"onenote|{_page_id(page_id)}"


def normalizar_modificacao(valor) -> str:
    """Aceita datetime com fuso ou texto ISO 8601 com fuso; devolve UTC 'Z'."""
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    if not isinstance(valor, datetime) or valor.tzinfo is None:
        raise ValueError("modified_at precisa ser data/hora com fuso")
    return valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chave_versao(page_id: str, modified_at_utc: str, hash_: str) -> str:
    return f"{_page_id(page_id)}|{normalizar_modificacao(modified_at_utc)}|{hash_}"


def encontrar_handoff(handoffs: list, page_id: str):
    identidade = chave_identidade(page_id)
    achados = [h for h in handoffs if h.get("identidade") == identidade]
    if len(achados) > 1:
        raise HandoffAmbiguo(identidade)
    return achados[0] if achados else None


def _agora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def registrar(handoff, page_id, modified_at, resultado_hash, *, classificacao,
              estado="ok", resumo="", agora=None):
    """Aplica a regra de idempotencia. Devolve (handoff_novo, acao), com acao
    em {"criado", "verificacao_atualizada", "nova_versao"}. Nao muta a entrada."""
    if estado not in ESTADOS:
        raise ValueError("estado invalido")
    identidade = chave_identidade(page_id)
    if handoff is not None and handoff.get("identidade") != identidade:
        raise ValueError("handoff de outra identidade")
    agora = agora or _agora()
    modificada = normalizar_modificacao(modified_at)
    versao = {
        "chave_versao": chave_versao(page_id, modificada, resultado_hash["hash"]),
        "modified_at_utc": modificada,
        "hash": resultado_hash["hash"],
        "tipo_hash": resultado_hash["tipo_hash"],
        "truncado": resultado_hash["truncado"],
        "caracteres_lidos": resultado_hash["caracteres_lidos"],
        "lido_em": agora,
    }
    base = {
        "identidade": identidade,
        "classificacao": classificacao,
        "forma_canonica": resultado_hash["forma_canonica"],
        "estado": estado,
        "resumo": str(resumo)[:LIMITE_RESUMO],
        "ultima_verificacao": agora,
    }
    if handoff is None:
        return {**base, "versoes": [versao]}, "criado"

    novo = {**handoff, **base, "versoes": [dict(v) for v in handoff["versoes"]]}
    vigente = novo["versoes"][-1]
    if vigente["hash"] == versao["hash"] and vigente["tipo_hash"] == versao["tipo_hash"]:
        vigente["modified_at_utc"] = modificada  # so metadado de verificacao
        return novo, "verificacao_atualizada"
    novo["versoes"].append(versao)
    return novo, "nova_versao"


def renderizar_handoff(handoff: dict) -> str:
    """Texto (so metadados) para o bloco do handoff no Notion."""
    v = handoff["versoes"][-1]
    linhas = [
        "Origem: OneNote",
        f"Chave de identidade: {handoff['identidade']}",
        f"Classificacao (17.5): {handoff['classificacao']}",
        f"Forma canonica: {handoff['forma_canonica']}",
        f"Estado: {handoff['estado']}",
        f"Vigente: modificada_em {v['modified_at_utc']} | {v['tipo_hash']} {v['hash']}"
        f" | truncado: {'sim' if v['truncado'] else 'nao'} | caracteres_lidos: {v['caracteres_lidos']}",
        f"Ultima verificacao: {handoff['ultima_verificacao']}",
        f"Resumo: {handoff['resumo']}" if handoff["resumo"] else "Resumo: -",
        "Versoes:",
    ]
    linhas += [
        f"- {x['lido_em']} | modificada_em {x['modified_at_utc']} | {x['tipo_hash']} {x['hash']}"
        f" | truncado: {'sim' if x['truncado'] else 'nao'}"
        for x in handoff["versoes"]
    ]
    return "\n".join(linhas)


def main(argv=None) -> int:
    """CLI: le o texto da pagina na entrada padrao e imprime SOMENTE metadados.

    py scripts\\onenote_handoff.py --page-id ID --modified-at 2026-10-11T12:00:00Z
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    def opcao(nome):
        return argv[argv.index(nome) + 1] if nome in argv and argv.index(nome) + 1 < len(argv) else None

    try:
        page_id, modified = opcao("--page-id"), opcao("--modified-at")
        chave_identidade(page_id)
        modificada = normalizar_modificacao(modified)
        texto = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        resultado = calcular_hash(texto)
    except (ValueError, TypeError) as exc:
        print(json.dumps({"erro": "argumentos invalidos", "tipo_erro": type(exc).__name__}))
        return 2
    print(json.dumps({"identidade": chave_identidade(page_id), "modified_at_utc": modificada, **resultado}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
