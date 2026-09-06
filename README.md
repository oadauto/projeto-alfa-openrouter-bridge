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

## Estado atual: modo seguro (dry-run) apenas

Nesta primeira etapa, o projeto:

- NÃO faz nenhuma chamada real de geração à API do OpenRouter;
- NÃO executa fallback automático;
- NÃO grava nada automaticamente no Notion;
- NÃO expõe nenhum servidor MCP;
- NÃO se conecta ao ChatGPT.

Todo fluxo (catálogo → seleção → autorização → "chamada") é simulado. O ponto
de entrada `src/ponte_openrouter/dry_run.py` imprime o que seria feito e para,
sem nunca alcançar uma chamada de rede de geração.

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
- `.gitignore` bloqueia qualquer arquivo que pareça conter segredo
  (`*credential*`, `*secret*`, `*token*`, `.env`, etc.).
- `tests/test_seguranca_logs.py` varre as saídas geradas nos testes e falha
  caso encontre qualquer padrão de chave/segredo.

## Estrutura

Ver `docs/ARQUITETURA.md` para os 6 componentes e o fluxo completo de decisão.

## Próximas etapas (fora do escopo desta versão)

- Leitura automática de contexto mínimo diretamente do Notion (hoje,
  `contexto.py` apenas recebe um resumo já pronto como parâmetro).
- Execução real de chamadas (fora do modo dry-run), sempre atrás do portão
  de autorização humana.
- Compatibilidade MCP para expor esta camada ao ChatGPT/Codex.
- Gravação automática de resultados no Notion (hoje, o registro continua
  manual e revisado, como em todas as fases anteriores do Projeto ALFA).
