# projeto-alfa-openrouter-bridge

Camada programática do Projeto ALFA responsável por propor — nunca executar
automaticamente — a migração para um modelo do OpenRouter quando ChatGPT/Codex
ou Claude ficarem indisponíveis (cota, limite de tokens, rate limit, falha).

## Finalidade

Este projeto implementa, em código, o protocolo já formalizado na Política de
Memória Única e Deduplicação (v2.3, seção "Finalidade do OpenRouter no Projeto
ALFA") e homologado manualmente nas Fases F.1–F.7 do Projeto ALFA. Ele NÃO
substitui ChatGPT/Codex ou Claude — existe apenas para garantir continuidade
quando um desses agentes principais estiver indisponível.

## Estado atual: modo seguro (dry-run) por padrão, com execução real disponível sob confirmação explícita

Por padrão, todo fluxo (catálogo → seleção → autorização → "chamada") é
simulado: o ponto de entrada `src/ponte_openrouter/dry_run.py` imprime o
que seria feito e para, sem nunca alcançar uma chamada de rede de geração.

Existe também um executor real, mínimo e deliberadamente isolado
(`src/ponte_openrouter/executor_real.py`, acionado via
`scripts/teste_real_ponte.py`), que faz UMA única chamada real ao
OpenRouter — nunca mais de uma — e apenas quando:

- o chamador passa `confirmar_execucao=True` explicitamente; e
- (no script de linha de comando) o usuário confirma digitando "s"
  interativamente antes da chamada.

Sem essa dupla confirmação, nenhuma chamada é feita. O executor real:

- NÃO faz retry nem troca de modelo automaticamente — se a chamada falhar,
  apenas informa o resultado e para;
- envia `"provider": {"allow_fallbacks": false}` no corpo da requisição,
  impedindo que o próprio roteador do OpenRouter atenda a chamada por
  outro provedor do mesmo modelo sem decisão humana;
- NÃO grava nada automaticamente no Notion;
- NÃO expõe nenhum servidor MCP;
- NÃO se conecta ao ChatGPT.

## Papéis (Governança do Projeto ALFA)

- **Claude/Cowork** — orquestrador: planeja, revisa e decide quando esta
  camada pode ser acionada.
- **Claude Code** — executor de engenharia: mantém e evolui este código.
- **Codex** — especialista complementar; compatibilidade MCP para ChatGPT é
  uma etapa futura, não iniciada.
- **Usuário** — autoridade final: nenhuma chamada real ocorre sem sua
  autorização explícita, em cada execução.

## Regras de segurança (não negociáveis)

- A chave de API é lida em tempo de execução exclusivamente do Windows
  Credential Manager (`credencial.py`) e mantida apenas em memória, pelo
  tempo mínimo necessário.
- A chave NUNCA é escrita em arquivo, log, teste, saída de teste ou
  variável de ambiente persistente.
- No executor real, a chave é descartada da memória (`del chave`) assim
  que a chamada HTTP termina, e a resposta do modelo é sempre truncada a
  300 caracteres na saída — nunca a resposta integral sem limite.
- `.gitignore` bloqueia qualquer arquivo que pareça conter segredo
  (`*credential*`, `*secret*`, `*token*`, `.env`, etc.).
- `tests/test_seguranca_logs.py` varre as saídas geradas nos testes e falha
  caso encontre qualquer padrão de chave/segredo.

## Continuidade controlada (Claude/ChatGPT -> OpenRouter)

`src/ponte_openrouter/continuidade.py` oferece o OpenRouter como alternativa
quando Claude ou ChatGPT estao no limite ou indisponiveis. Nunca troca
silenciosamente.

- **Quando e oferecido:** somente se uma FONTE AUTORIZADA informar o estado
  `limite_atingido` ou `indisponivel` para `claude` ou `chatgpt`
  (`SinalServico`). `disponivel`, `limite_proximo` e `desconhecido` nunca
  geram oferta nem chamada. Sinal com fonte, servico ou estado fora dos
  conjuntos fechados vira `desconhecido`. O modulo nao calcula percentuais
  nem detecta cota: quem informa e a fonte.
- **Sinal x erro do OpenRouter:** o sinal de indisponibilidade do
  Claude/ChatGPT e uma ENTRADA (`fonte_sinal`). Um HTTP 429/5xx e o RESULTADO
  de uma chamada ao OpenRouter (`origem_resultado="openrouter"`,
  `status_http`). Sao registrados em campos separados e nunca se misturam.
- **Oferta:** servico afetado, motivo (vocabulario fechado), modelo e custo
  estimado (`gratuito`, `pago (...)` ou `indisponivel` quando o preco do
  catalogo faltar ou for ilegivel - nunca inventado).
- **Confirmacao interativa:** tres respostas separadas e exatas - nome do
  servico, identificador do modelo e a palavra `AUTORIZO` - mais uma quarta,
  `ACEITO O CUSTO`, quando o modelo nao e comprovadamente gratuito (pago ou
  custo indisponivel). Ausente, divergente ou invalida em qualquer uma cancela
  tudo; nao existe confirmacao unica implicita. As respostas so valem se
  digitadas por uma pessoa no terminal (`leitor_interativo`); respostas
  vindas de JSON, arquivo, pipe ou lista sao recusadas antes de qualquer
  pergunta.
- **Uma chamada, sem retry:** `executar_oferta_confirmada()` chama
  diretamente `executor_real.executar_chamada_real()` no maximo uma vez
  (`allow_fallbacks: false`). Nao usa `orquestrar()` (cujo laco pode avancar
  para outros candidatos), nao repete e nao troca de modelo. 200, 429, 5xx e
  codigos desconhecidos sao resultado final.
- **Registro seguro:** lista branca; nunca token, credencial, prompt,
  resposta (apenas o comprimento) nem mensagem livre de erro.
- **Integração ao harness (adaptador JSON):** `scripts/adaptador_harness.py`
  aceita, de forma opcional, `sinal_servico` e `modelo_continuidade`. Só
  quando o sinal é ofertável (`limite_atingido`/`indisponivel` de fonte
  autorizada) a rota de continuidade entra em ação; em qualquer outro caso
  (sem sinal, `disponivel`, `limite_proximo`, `desconhecido`, fonte não
  autorizada) o fluxo anterior roda inalterado e a saída segue sendo a de 8
  campos. O adaptador JSON NUNCA executa: só devolve a oferta. Se o JSON
  trouxer `aprovado_por_humano`, `confirmo_modo_real` ou respostas de
  autorizacao, isso e tratado como recusa (`recusado_json`), pois qualquer
  script consegue preencher esses campos. O `modo: real` antigo tambem esta
  bloqueado no adaptador (`AprovacaoAusenteError`, sempre, mesmo com
  aprovacoes no JSON), entao a unica via de chamada real pelo harness e
  a interativa. A execucao real so ocorre em
  `py scripts\cliente_harness_local.py --continuidade-interativa`, com as
  confirmacoes digitadas no terminal por uma pessoa; sem terminal real, recusa.
  Com `--log`, o registro vai para `logs/` por lista branca (ver
  `docs/fase5-observabilidade.md`).

Ver `docs/ARQUITETURA.md`.

## Observabilidade (Fase 5 / 5.2)

O cliente harness local aceita `--log logs\ARQUIVO.jsonl` (opt-in) para
registrar, por lista branca, codigo de saida, duracao, modelo, status HTTP e
sucesso/falha - nunca a resposta do modelo, o prompt, mensagens livres de erro
ou segredos. Ver `docs/fase5-observabilidade.md`.

## Estrutura

Ver `docs/ARQUITETURA.md` para os 6 componentes e o fluxo completo de decisão.

## Próximas etapas (fora do escopo desta versão)

- Leitura automática de contexto mínimo diretamente do Notion (hoje,
  `contexto.py` apenas recebe um resumo já pronto como parâmetro).
- Compatibilidade MCP para expor esta camada ao ChatGPT/Codex.
- Gravação automática de resultados no Notion (hoje, o registro continua
  manual e revisado, como em todas as fases anteriores do Projeto ALFA).
