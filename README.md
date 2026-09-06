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

## Estrutura

Ver `docs/ARQUITETURA.md` para os 6 componentes e o fluxo completo de decisão.

## Próximas etapas (fora do escopo desta versão)

- Leitura automática de contexto mínimo diretamente do Notion (hoje,
  `contexto.py` apenas recebe um resumo já pronto como parâmetro).
- Compatibilidade MCP para expor esta camada ao ChatGPT/Codex.
- Gravação automática de resultados no Notion (hoje, o registro continua
  manual e revisado, como em todas as fases anteriores do Projeto ALFA).
