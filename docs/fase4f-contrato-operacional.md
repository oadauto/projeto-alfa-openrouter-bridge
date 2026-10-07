# Fase 4F — Contrato operacional Claude → Harness local

## Objetivo

Padronizar como Claude, atuando como orquestrador principal, solicita uma
execução ao harness local. Claude decide quando usar a ponte e prepara o
contexto; o harness aplica seleção, autorização e execução conforme as regras
existentes. A autorização de modo real continua pertencendo ao humano.

## Entrada mínima

O cliente recebe um único objeto JSON com:

```json
{
  "tarefa": "analise_geral",
  "modelos_brutos": [],
  "resumo_curado": "Contexto mínimo e não sensível da tarefa.",
  "modo": "dryrun",
  "respostas_humanas": ["1"]
}
```

`tarefa` deve ser uma das tarefas declaradas em
`config/selecao_por_tarefa.yaml`: `analise_geral`, `multimodal`, `codigo` ou
`continuidade_critica`.

`resumo_curado` não deve conter credenciais, tokens ou dados desnecessários.
`modelos_brutos` deve ser o catálogo já obtido pelo chamador. O cliente não
busca catálogo, não escolhe modelo e não acrescenta confirmações.

## Regras de autorização

- Usar `modo: "dryrun"` por padrão.
- Cada candidato precisa de uma resposta humana explícita em
  `respostas_humanas`.
- Modo real exige também `aprovado_por_humano: true`,
  `confirmo_modo_real: true` e `prompt_ficticio` explícito.
- Claude nunca deve inserir essas confirmações por conta própria.
- Não há retry ou fallback implícito no cliente.

## Saída

Em sucesso, o stdout contém somente o resultado sanitizado com os oito campos
do contrato: `modelo`, `categoria`, `status_http`, `duracao_segundos`,
`numero_tentativas`, `fallback_utilizado`, `origem_erro` e `resposta`.

Em falha, o stdout contém somente `{"erro": ..., "tipo_erro": ...}` e o
código de saída é diferente de zero.

## Primeira validação da 4F

Executar um único cenário em dry-run, sem rede e sem credenciais:

```powershell
Set-Location "C:\Cowork_Adauto\05_AGENTES_PROGRAMACAO\projeto-alfa-openrouter-bridge"
$entrada = '{"tarefa":"analise_geral","modelos_brutos":[],"resumo_curado":"Teste operacional controlado do Claude ao harness.","modo":"dryrun","respostas_humanas":["1"]}'
$entrada | py scripts\cliente_harness_local.py
```

Critério de conclusão: JSON válido, código de saída zero, categoria de sucesso
simulado e nenhum segredo na saída.

Este documento não autoriza execução real e não substitui a validação humana.
