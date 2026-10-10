"""Observabilidade segura do cliente harness — Projeto ALFA, Fase 5.

Objetivo: tornar verificáveis (sem expor segredos) o resultado e o
comportamento de cada chamada ao harness local feita por
`cliente_harness_local.py`: código de saída, duração, modelo, status HTTP,
sucesso/falha e um trecho saneado de stderr.

Princípios (herdados das Fases 4A-4H e da governança do Projeto ALFA):

- **Lista branca, não lista negra.** O registro é construído campo a campo a
  partir de valores estruturados e de comprimentos. Nenhum texto bruto de
  stdout/stderr, prompt, resumo ou resposta do modelo é copiado
  integralmente para o registro.
- **A resposta do modelo nunca é registrada**, apenas o seu comprimento em
  caracteres (`resposta_caracteres`).
- **Saneamento defensivo** (`sanitizar_texto`): mesmo os poucos trechos
  textuais permitidos (`erro` e `stderr_trecho`) passam por redação de
  padrões típicos de segredo (Bearer, `sk-...`, `chave=valor`, cadeias
  opacas longas) e por truncamento.
- **Opt-in.** Nada é gravado em disco a menos que o chamador informe um
  caminho de log explicitamente. Este módulo nunca escolhe um caminho por
  conta própria.
- **Falha de log não derruba a chamada.** Uma falha ao gravar o log é
  reportada no próprio registro (`log_gravado=False`, `tipo_erro_log`) e
  nunca altera o resultado da chamada ao harness, nem o código de saída, nem
  o stdout do cliente. Não há retry nem caminho alternativo de gravação.
- Sem rede, sem credencial, sem chamada ao OpenRouter.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSAO = 1
LIMITE_TRECHO_CARACTERES = 500
MARCADOR_REDACAO = "[REDACTED]"

# Ordem importa: padrões mais específicos primeiro.
_PADROES_SEGREDO: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{6,}=*"), f"Bearer {MARCADOR_REDACAO}"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), MARCADOR_REDACAO),
    (
        re.compile(
            r"(?i)\b(authorization|api[_\-]?key|apikey|access[_\-]?token|token|secret|"
            r"senha|password|passwd|chave|credencial|credential)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
        ),
        rf"\1\2{MARCADOR_REDACAO}",
    ),
    # Cadeias opacas longas (chaves, hashes, tokens base64/hex) sem espaços.
    (re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}"), MARCADOR_REDACAO),
]


def sanitizar_texto(texto, limite: int = LIMITE_TRECHO_CARACTERES) -> str:
    """Redige padrões típicos de segredo e trunca o texto.

    Aceita `str`, `bytes` ou `None`. Sempre devolve `str`.
    """
    if texto is None:
        return ""
    if isinstance(texto, (bytes, bytearray)):
        texto = bytes(texto).decode("utf-8", errors="replace")
    elif not isinstance(texto, str):
        texto = str(texto)

    for padrao, substituicao in _PADROES_SEGREDO:
        texto = padrao.sub(substituicao, texto)

    texto = texto.strip()
    if len(texto) > limite:
        texto = texto[:limite] + "...[truncado]"
    return texto


def _tamanho(valor) -> int:
    if valor is None:
        return 0
    if isinstance(valor, (bytes, bytearray)):
        return len(valor)
    return len(str(valor).encode("utf-8", errors="replace"))


def construir_registro(
    saida: dict,
    codigo_saida: int,
    duracao_cliente_segundos: float,
    stdout=None,
    stderr=None,
) -> dict:
    """Constrói o registro de observabilidade por lista branca.

    `saida` é o objeto JSON devolvido por `invocar_adaptador` (resultado
    sanitizado de 8 campos ou erro estruturado). `stdout` e `stderr` são os
    textos brutos do subprocesso: deles só saem comprimentos e um trecho
    saneado e truncado de stderr.
    """
    saida = saida if isinstance(saida, dict) else {}
    eh_erro = "erro" in saida
    sucesso = (codigo_saida == 0) and (not eh_erro)

    resposta = saida.get("resposta")
    resposta_caracteres = len(resposta) if isinstance(resposta, str) else None

    registro = {
        "schema_versao": SCHEMA_VERSAO,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "codigo_saida": codigo_saida,
        "sucesso": sucesso,
        "modelo": saida.get("modelo"),
        "categoria": saida.get("categoria"),
        "status_http": saida.get("status_http"),
        "duracao_segundos": saida.get("duracao_segundos"),
        "duracao_cliente_segundos": round(float(duracao_cliente_segundos), 4),
        "numero_tentativas": saida.get("numero_tentativas"),
        "fallback_utilizado": saida.get("fallback_utilizado"),
        "origem_erro": saida.get("origem_erro"),
        "tipo_erro": saida.get("tipo_erro"),
        "erro": sanitizar_texto(saida.get("erro")) if eh_erro else None,
        "stdout_bytes": _tamanho(stdout),
        "stderr_bytes": _tamanho(stderr),
        "stderr_trecho": sanitizar_texto(stderr),
        "resposta_caracteres": resposta_caracteres,
        "log_gravado": False,
        "tipo_erro_log": None,
    }
    # Campos de texto livre vindos de `saida` que não passaram pelo
    # saneamento acima (modelo, categoria, origem_erro, tipo_erro) são
    # tratados como strings curtas e também saneados por segurança.
    for campo in ("modelo", "categoria", "origem_erro", "tipo_erro"):
        if isinstance(registro[campo], str):
            registro[campo] = sanitizar_texto(registro[campo], limite=200)
    return registro


def gravar_registro(registro: dict, caminho) -> dict:
    """Acrescenta `registro` (uma linha JSON) ao arquivo `caminho`.

    Nunca levanta exceção: em caso de falha, devolve o registro com
    `log_gravado=False` e `tipo_erro_log` preenchido (somente o nome do tipo
    da exceção, nunca a mensagem, que poderia conter o caminho ou dados).
    Não há retry nem caminho alternativo.
    """
    try:
        destino = Path(caminho)
        destino.parent.mkdir(parents=True, exist_ok=True)
        registro_gravado = dict(registro)
        registro_gravado["log_gravado"] = True
        registro_gravado["tipo_erro_log"] = None
        linha = json.dumps(registro_gravado, ensure_ascii=False)
        with destino.open("a", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write(linha + "\n")
        return registro_gravado
    except Exception as exc:  # noqa: BLE001 - falha de log nunca derruba a chamada.
        registro_falho = dict(registro)
        registro_falho["log_gravado"] = False
        registro_falho["tipo_erro_log"] = type(exc).__name__
        return registro_falho
