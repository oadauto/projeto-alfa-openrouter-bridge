# Fase 5 / 5.2 - Observabilidade segura do cliente harness local

Registro opt-in de cada chamada ao harness local, para verificar resultado e
comportamento **sem expor segredos nem conteudo**. Sem rede, sem credencial,
sem chamada ao OpenRouter.

## Uso

```
py scripts\cliente_harness_local.py --log logs\harness_observabilidade.jsonl < entrada.json
```

- Sem `--log`, **nada e gravado** e o comportamento e identico ao das fases
  anteriores.
- Com `--log`, o stdout continua sendo somente o resultado do harness; o
  registro vai apenas para o arquivo (uma linha JSON por chamada).
- O caminho deve terminar em `.jsonl` e ficar **dentro da pasta `logs/` do
  repositorio** (relativo ou absoluto; `..` e links sao resolvidos antes da
  checagem).
- `--log` sem valor, com valor iniciado por `--`, fora de `logs/` ou sem
  `.jsonl` e **erro explicito**: saida `{"erro": ..., "tipo_erro":
  "LogPathInvalido"}` com codigo de saida 2, sem executar o harness. A
  mensagem nao ecoa o caminho informado.
- Uso como biblioteca: `invocar_adaptador_observado(entrada, log_path=...)`
  grava no caminho recebido sem a checagem de pasta (a validacao e do CLI).

## Campos registrados

`schema_versao`, `timestamp_utc`, `codigo_saida`, `sucesso`, `modelo`,
`categoria`, `status_http`, `duracao_segundos` (HTTP), `duracao_cliente_segundos`,
`numero_tentativas`, `fallback_utilizado`, `origem_erro`, `tipo_erro`, `erro`,
`stdout_bytes`, `stderr_bytes`, `stderr_trecho`, `resposta_caracteres`,
`log_gravado`, `tipo_erro_log`.

## O que nunca e gravado

- A resposta do modelo (so o comprimento, em `resposta_caracteres`).
- O prompt, o resumo e qualquer entrada do usuario.
- Mensagens livres de erro: o campo `erro` recebe sempre o texto fixo
  `mensagem omitida`; o diagnostico fica em `tipo_erro` (nome do tipo).
- Chaves, tokens, senhas e credenciais. O `stderr_trecho` (ate 200
  caracteres) passa por redacao de padroes de segredo (Bearer, `sk-...`,
  `chave=valor`, cadeias opacas longas). A redacao e por padrao: nao substitui
  o cuidado de nunca colocar segredo em stderr.
- O caminho ou a mensagem de uma falha ao gravar o log (so o nome do tipo da
  excecao, em `tipo_erro_log`).

Uma falha ao gravar o log **nunca** altera o resultado da chamada nem o codigo
de saida (`log_gravado=false`).

## Retencao e limpeza

- Cada log tem limite de 1 MiB. Ao atingir o limite, o arquivo atual vira
  `NOME.1.jsonl` (substituindo um `.1` anterior) e um novo arquivo comeca: no
  maximo dois arquivos por log.
- Nada e apagado automaticamente alem dessa substituicao.
- `logs/*.jsonl` e ignorado pelo git. Limpeza manual: apagar os `*.jsonl` de
  `logs/` e seguro e nao afeta o codigo.
