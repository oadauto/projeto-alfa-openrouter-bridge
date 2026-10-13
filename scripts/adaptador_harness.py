"""Adaptador local mínimo do harness — Projeto ALFA, Fase 4A.

Objetivo único: permitir que um agente externo (Claude, via subprocesso)
envie uma tarefa ao harness local e receba de volta um `ResultadoSanitizado`
em JSON — nada além disso. Não é uma API, não é um servidor, não usa MCP,
não usa automação de navegador: é um script Python comum, invocado como
subprocesso, que lê um objeto JSON de `stdin` e escreve um objeto JSON em
`stdout`.

Este módulo NÃO contém nenhuma lógica nova de seleção, fallback, execução
ou autorização - ele apenas chama `orquestrador.executar_via_contrato()`
(já existente desde a Fase 2), que já reaplica os portões definidos em
`harness_contrato.py`. Nenhum módulo de produção foi alterado para este
adaptador existir.

## Contrato de entrada (stdin, JSON)

```json
{
  "tarefa": "continuidade_critica",
  "modelos_brutos": [ {"id": "...", ...}, ... ],
  "resumo_curado": "resumo de texto",
  "modo": "dryrun",
  "prompt_ficticio": null,
  "aprovado_por_humano": false,
  "confirmo_modo_real": false,
  "respostas_humanas": ["1"]
}
```

- `modo="dryrun"` (padrão se omitido): não precisa de `aprovado_por_humano`
  nem `confirmo_modo_real` - nunca toca rede, nunca usa credencial.
- `modo="real"`: BLOQUEADO neste adaptador, SEMPRE (com ou sem
  `aprovado_por_humano`/`confirmo_modo_real`). Aprovações e respostas dentro
  de um JSON não provam confirmação humana: qualquer script ou agente
  consegue preenchê-las. O adaptador recusa ANTES de chamar
  `executar_via_contrato()` com `AprovacaoAusenteError` - nenhuma tentativa,
  nenhum acesso a `executor_real`/`credencial`/rede. A única forma de uma
  chamada real por este harness é
  `cliente_harness_local.py --continuidade-interativa`, com confirmação
  digitada no terminal por uma pessoa.
- `respostas_humanas`: lista de respostas pré-registradas para a(s)
  pergunta(s) de confirmação por candidato que `orquestrador.orquestrar()`
  já faz internamente (mesmo mecanismo usado por
  `executar_orquestrador.py`, só que aqui as respostas vêm prontas em vez
  de interativas, porque um subprocesso não tem teclado). Cada resposta é
  consumida em ordem, uma por tentativa. Se as respostas se esgotarem antes
  do orquestrador precisar de outra, o adaptador INTERROMPE com um erro
  controlado - nunca inventa uma resposta, nunca assume autorização
  implícita. `respostas_humanas` é obrigatório em QUALQUER modo (inclusive
  dry-run): este adaptador nunca autoriza nada por padrão/silêncio.
  `papel_executor` é sempre fixo como "alfa" - não é lido da entrada, para
  que nenhum chamador possa se autoatribuir um papel diferente.

## Continuidade controlada Claude/ChatGPT -> OpenRouter (opcional)

Chaves opcionais da entrada, usadas SOMENTE quando `sinal_servico` está
presente e seu estado efetivo é `limite_atingido` ou `indisponivel`:

- `sinal_servico`: `{"servico": "claude"|"chatgpt", "estado": ..., "fonte": ...,
  "motivo": ...}` informado por uma fonte autorizada (ver `continuidade.py`).
  Ausente, `disponivel`, `limite_proximo` ou `desconhecido` (inclui fonte não
  autorizada): o fluxo abaixo (dry-run/real) roda EXATAMENTE como antes, sem
  nenhuma alteração, e a saída continua sendo a de 8 campos.
- `modelo_continuidade`: id do modelo OpenRouter oferecido (obrigatório).
  O custo estimado vem do item correspondente de `modelos_brutos`, se houver.
- Este adaptador NUNCA executa a continuidade. Ele só devolve a OFERTA
  (serviço afetado, motivo, modelo, custo estimado), sem rede nem credencial.
- Se o JSON trouxer `aprovado_por_humano`/`confirmo_modo_real` verdadeiros ou
  respostas de autorização em `respostas_humanas`, esses campos NÃO provam confirmação humana (qualquer
  script consegue preenchê-los): a saída é uma RECUSA
  (`etapa: recusado_json`, `motivo_decisao: confirmacao_apenas_por_json`),
  sem pergunta, sem rede, sem credencial.
- A execução real (UMA chamada, `allow_fallbacks: false`, sem retry) só
  ocorre em `scripts/cliente_harness_local.py --continuidade-interativa`,
  com as confirmações digitadas no terminal por uma pessoa (3 respostas;
  4 se o modelo não for comprovadamente gratuito).
- Nesta rota o campo `modo` é ignorado e a saída é `{"continuidade": {...}}`
  (lista branca; sem prompt, resposta, credencial ou mensagem livre).

## Contrato de saída (stdout, JSON)

Em sucesso (mesmo que o resultado final seja um erro HTTP real, ex. 429):
```json
{
  "modelo": "...",
  "categoria": "...",
  "status_http": 200,
  "duracao_segundos": 0.42,
  "numero_tentativas": 1,
  "fallback_utilizado": false,
  "origem_erro": "...",
  "resposta": "..."
}
```
Somente estes oito campos - nunca chave, token, prompt bruto ou qualquer
outro dado além do que `harness_contrato.ResultadoSanitizado` já expõe.

Em erro (entrada inválida, aprovação ausente, respostas esgotadas, ou
qualquer exceção controlada):
```json
{"erro": "mensagem segura, sem segredo", "tipo_erro": "NomeDaExcecao"}
```
e o processo termina com código de saída diferente de zero. Uma exceção
NÃO tratada nunca deveria chegar ao usuário como traceback bruto no
stdout - o `main()` abaixo captura tudo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ponte_openrouter import continuidade as continuidade_mod  # noqa: E402
from ponte_openrouter.orquestrador import executar_via_contrato  # noqa: E402
from ponte_openrouter.harness_contrato import (  # noqa: E402
    EntradaInvalidaError,
    AprovacaoAusenteError,
    PapelNaoAutorizadoError,
)


class RespostasHumanasEsgotadasError(RuntimeError):
    """Levantado quando o orquestrador pede mais uma confirmação por
    candidato do que `respostas_humanas` continha. Nunca inventamos uma
    resposta nem assumimos autorização implícita quando isso acontece."""


def _construir_obter_escolha_humana(respostas_humanas: list[str]):
    fila = list(respostas_humanas)

    def _obter_escolha_humana(_mensagem: str) -> str:
        if not fila:
            raise RespostasHumanasEsgotadasError(
                "O orquestrador pediu uma confirmação humana adicional, mas "
                "'respostas_humanas' já havia se esgotado. Nenhuma tentativa "
                "adicional foi autorizada."
            )
        return fila.pop(0)

    return _obter_escolha_humana


def _processar_continuidade(entrada_json: dict) -> dict | None:
    """Rota de continuidade controlada: SOMENTE oferta ou recusa.

    Devolve None quando o sinal não é ofertável (ausente, `disponivel`,
    `limite_proximo`, `desconhecido` ou fonte não autorizada): o chamador
    segue o fluxo anterior, inalterado. Nunca executa, nunca toca rede ou
    credencial: confirmações vindas do JSON não provam ação humana.
    """
    try:
        oferta = continuidade_mod.montar_oferta_de_json(entrada_json)
    except ValueError as exc:
        raise EntradaInvalidaError(str(exc)) from None
    if oferta is None:
        return None

    respostas = entrada_json.get("respostas_humanas")
    respostas = respostas if isinstance(respostas, list) else []
    trouxe_confirmacao = bool(
        entrada_json.get("aprovado_por_humano")
        or entrada_json.get("confirmo_modo_real")
        or any(
            isinstance(r, str) and r.strip() in (continuidade_mod.RESPOSTA_AUTORIZACAO, continuidade_mod.RESPOSTA_CUSTO)
            for r in respostas
        )
    )
    if trouxe_confirmacao:
        return {"continuidade": dict(continuidade_mod.registro_recusa_json(oferta), etapa="recusado_json")}
    return {"continuidade": dict(continuidade_mod.registro_oferta(oferta), etapa="oferta")}


def _processar(entrada_json: dict) -> dict:
    if "sinal_servico" in entrada_json:
        saida_continuidade = _processar_continuidade(entrada_json)
        if saida_continuidade is not None:
            return saida_continuidade

    modo = entrada_json.get("modo", "dryrun")
    aprovado_por_humano = bool(entrada_json.get("aprovado_por_humano", False))
    confirmo_modo_real = bool(entrada_json.get("confirmo_modo_real", False))

    if modo == "real":
        # Bloqueio incondicional: aprovação vinda de JSON não é confirmação
        # humana. Mensagem fixa (não ecoa nada da entrada).
        raise AprovacaoAusenteError(
            "modo='real' está bloqueado neste adaptador: aprovações em JSON não "
            "provam confirmação humana. Use cliente_harness_local.py "
            "--continuidade-interativa (confirmação digitada no terminal). "
            "Nenhuma execução foi tentada."
        )

    respostas_humanas = entrada_json.get("respostas_humanas")
    if not isinstance(respostas_humanas, list):
        raise EntradaInvalidaError(
            "'respostas_humanas' é obrigatório (lista de strings), mesmo em dry-run."
        )

    obter_escolha_humana = _construir_obter_escolha_humana(respostas_humanas)

    resultado = executar_via_contrato(
        tarefa=entrada_json.get("tarefa", ""),
        modelos_brutos=entrada_json.get("modelos_brutos", []),
        resumo_curado=entrada_json.get("resumo_curado", ""),
        modo=modo,
        obter_escolha_humana=obter_escolha_humana,
        prompt_ficticio=entrada_json.get("prompt_ficticio"),
        papel_executor="alfa",  # fixo - nunca lido da entrada
        aprovado_por_humano=aprovado_por_humano,
    )

    return {
        "modelo": resultado.modelo,
        "categoria": resultado.categoria,
        "status_http": resultado.status_http,
        "duracao_segundos": resultado.duracao_segundos,
        "numero_tentativas": resultado.numero_tentativas,
        "fallback_utilizado": resultado.fallback_utilizado,
        "origem_erro": resultado.origem_erro,
        "resposta": resultado.resposta,
    }


def main() -> int:
    bruto = sys.stdin.read()

    try:
        entrada_json = json.loads(bruto)
    except json.JSONDecodeError as exc:
        print(json.dumps({"erro": f"JSON de entrada inválido: {exc}", "tipo_erro": "JSONDecodeError"}))
        return 2

    if not isinstance(entrada_json, dict):
        print(json.dumps({"erro": "A entrada JSON deve ser um objeto.", "tipo_erro": "EntradaInvalidaError"}))
        return 2

    try:
        saida = _processar(entrada_json)
    except (
        EntradaInvalidaError,
        AprovacaoAusenteError,
        PapelNaoAutorizadoError,
        RespostasHumanasEsgotadasError,
        ValueError,
        NotImplementedError,
    ) as exc:
        print(json.dumps({"erro": str(exc), "tipo_erro": type(exc).__name__}))
        return 1
    except Exception as exc:  # noqa: BLE001 - nunca deixamos um traceback bruto vazar
        print(json.dumps({"erro": "erro interno inesperado no adaptador.", "tipo_erro": type(exc).__name__}))
        return 1

    print(json.dumps(saida, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
