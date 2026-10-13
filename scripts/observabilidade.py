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

Fase 5.2:

- **Mensagens livres de erro nunca são gravadas.** O campo `erro` recebe
  sempre o texto fixo `MENSAGEM_ERRO_OMITIDA`; o diagnóstico fica em
  `tipo_erro` (nome do tipo, curto e saneado).
- **Rotação simples.** Ao atingir `LIMITE_ARQUIVO_BYTES`, o log atual vira
  `NOME.1.jsonl` (substituindo um `.1` anterior) e um novo arquivo começa:
  no máximo dois arquivos por log. Nada é apagado fora disso.
- **Validação de caminho** (`validar_caminho_log`): o caminho de log deve
  resolver para dentro da pasta `logs/` do repositório e terminar em `.jsonl`.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSAO = 1
LIMITE_TRECHO_CARACTERES = 200
LIMITE_ARQUIVO_BYTES = 1024 * 1024  # 1 MiB por arquivo de log
MENSAGEM_ERRO_OMITIDA = "mensagem omitida"
SUFIXO_LOG = ".jsonl"
MARCADOR_REDACAO = "[REDACTED]"

# Continuidade controlada (OpenRouter): lista branca dos campos do objeto
# `continuidade` do adaptador que podem ir para o registro. Nunca entram
# `oferta_texto`, `mensagem`, prompt, resposta ou qualquer texto livre.
CAMPOS_CONTINUIDADE_TEXTO = (
    "etapa", "servico_afetado", "estado_servico", "fonte_sinal", "motivo",
    "modelo", "custo_estimado", "motivo_decisao", "origem_resultado",
    "categoria", "tipo_erro",
)
CAMPOS_CONTINUIDADE_BOOL = (
    "autorizado", "chamada_realizada", "retry", "troca_de_modelo", "fallback_utilizado",
)
CAMPOS_CONTINUIDADE_INT = ("numero_chamadas", "status_http", "resposta_caracteres")

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
        # Fase 5.2: mensagens livres de erro nunca vão para o registro.
        "erro": MENSAGEM_ERRO_OMITIDA if eh_erro else None,
        "stdout_bytes": _tamanho(stdout),
        "stderr_bytes": _tamanho(stderr),
        "stderr_trecho": sanitizar_texto(stderr),
        "resposta_caracteres": resposta_caracteres,
        "log_gravado": False,
        "tipo_erro_log": None,
    }
    # Continuidade controlada: só quando a saída trouxe o objeto `continuidade`
    # (o registro das demais chamadas permanece exatamente como antes).
    continuidade = saida.get("continuidade")
    if isinstance(continuidade, dict):
        extraido = _extrair_continuidade(continuidade)
        registro["continuidade"] = extraido
        registro["modelo"] = extraido["modelo"]
        registro["categoria"] = extraido["categoria"]
        registro["status_http"] = extraido["status_http"]
        registro["numero_tentativas"] = extraido["numero_chamadas"]
        registro["fallback_utilizado"] = extraido["fallback_utilizado"]
        registro["origem_erro"] = extraido["origem_resultado"]
        registro["tipo_erro"] = extraido["tipo_erro"]
        registro["resposta_caracteres"] = extraido["resposta_caracteres"]
    # Campos de texto livre vindos de `saida` que não passaram pelo
    # saneamento acima (modelo, categoria, origem_erro, tipo_erro) são
    # tratados como strings curtas e também saneados por segurança.
    for campo in ("modelo", "categoria", "origem_erro", "tipo_erro"):
        if isinstance(registro[campo], str):
            registro[campo] = sanitizar_texto(registro[campo], limite=200)
    return registro


def _extrair_continuidade(continuidade: dict) -> dict:
    """Copia, por lista branca e com tipo verificado, os campos permitidos do
    objeto `continuidade`. Textos passam por `sanitizar_texto`."""
    extraido: dict = {}
    for campo in CAMPOS_CONTINUIDADE_TEXTO:
        valor = continuidade.get(campo)
        extraido[campo] = sanitizar_texto(valor, limite=200) if isinstance(valor, str) else None
    for campo in CAMPOS_CONTINUIDADE_BOOL:
        valor = continuidade.get(campo)
        extraido[campo] = valor if isinstance(valor, bool) else None
    for campo in CAMPOS_CONTINUIDADE_INT:
        valor = continuidade.get(campo)
        extraido[campo] = valor if isinstance(valor, int) and not isinstance(valor, bool) else None
    return extraido


class LogPathInvalido(ValueError):
    """Caminho de log recusado por `validar_caminho_log`."""


def validar_caminho_log(caminho, raiz_logs) -> Path:
    """Devolve o caminho absoluto e resolvido do log, ou levanta
    `LogPathInvalido`.

    Regras: valor não vazio; sufixo `.jsonl`; o caminho resolvido (absoluto,
    sem `..` nem links) deve ficar dentro de `raiz_logs` (e não ser a própria
    pasta). Relativo é resolvido a partir do diretório atual.
    """
    if caminho is None or not isinstance(caminho, (str, os.PathLike)) or not str(caminho).strip():
        raise LogPathInvalido("caminho ausente")
    destino = Path(caminho).resolve()
    raiz = Path(raiz_logs).resolve()
    if destino.suffix.lower() != SUFIXO_LOG:
        raise LogPathInvalido("sufixo")
    if raiz not in destino.parents:
        raise LogPathInvalido("fora da pasta de logs")
    return destino


def _rotacionar_se_necessario(destino: Path, limite_bytes: int) -> None:
    if destino.exists() and destino.stat().st_size >= limite_bytes:
        anterior = destino.with_name(f"{destino.stem}.1{destino.suffix}")
        os.replace(destino, anterior)


def gravar_registro(registro: dict, caminho, limite_bytes: int = LIMITE_ARQUIVO_BYTES) -> dict:
    """Acrescenta `registro` (uma linha JSON) ao arquivo `caminho`.

    Nunca levanta exceção: em caso de falha, devolve o registro com
    `log_gravado=False` e `tipo_erro_log` preenchido (somente o nome do tipo
    da exceção, nunca a mensagem, que poderia conter o caminho ou dados).
    Não há retry nem caminho alternativo.
    """
    try:
        destino = Path(caminho)
        destino.parent.mkdir(parents=True, exist_ok=True)
        _rotacionar_se_necessario(destino, limite_bytes)
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
