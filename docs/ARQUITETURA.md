# Arquitetura — projeto-alfa-openrouter-bridge

## Os 6 componentes

1. **Detector de falha** (fora do escopo desta versão de código — hoje é o
   próprio Claude Code/Cowork que percebe uma falha de cota/limite numa
   chamada e decide invocar esta camada). É uma camada estritamente
   programática: não existe forma de detectar automaticamente uma
   indisponibilidade dentro das interfaces nativas de chat do ChatGPT ou do
   Claude — isso só é possível onde há uma chamada de API instrumentada.

2. **Catálogo dinâmico** (`catalogo.py`) — consulta `GET /api/v1/models` do
   OpenRouter (endpoint público, sem necessidade de chave) e filtra
   modelos gratuitos (`id` terminado em `:free` e preço de entrada e saída
   numericamente igual a zero). Aceita uma lista de exclusão (modelos já
   testados ou indisponíveis).

3. **Seletor declarativo por tarefa** (`seletor.py` + `config/selecao_por_tarefa.yaml`)
   — aplica regras legíveis e auditáveis (não uma decisão de LLM) para
   ordenar candidatos por adequação ao tipo de tarefa em curso.

4. **Portão de autorização humana** (`autorizacao.py`) — apresenta os
   candidatos (provedor, custo, capacidades, limitações) e exige
   confirmação explícita antes de liberar qualquer chamada real. Sem essa
   confirmação, o executor nunca é alcançado.

5. **Minimizador de contexto** (`contexto.py`) — nesta versão, recebe como
   parâmetro um resumo já pronto (string), preparado fora deste módulo
   (por exemplo, por curadoria manual a partir do Notion). Não faz nenhuma
   leitura automática do Notion nesta etapa.

6. **Executor + registrador** (`executor.py`) — só é alcançável fora do
   modo dry-run e após autorização confirmada. Trata explicitamente os
   códigos HTTP 200, 401, 403, 429 e 5xx, cada um com uma classificação
   própria (sucesso / problema de credencial / restrição de acesso /
   indisponibilidade / erro de servidor) — nunca inventa uma categoria
   para um código não mapeado; nesse caso, sinaliza como "não classificado"
   e pede decisão humana, no mesmo espírito do tratamento dado ao HTTP 403
   observado no teste F.7.1 do Projeto ALFA.

## Fluxo de decisão

```
falha detectada (fora deste código)
        │
        ▼
catalogo.buscar_catalogo_free()  ──> lista de modelos gratuitos atual
        │
        ▼
seletor.selecionar(tarefa, catalogo)  ──> candidatos ordenados + justificativa
        │
        ▼
autorizacao.confirmar(candidatos)  ──> usuário escolhe UM candidato, ou nenhum
        │
        ├── modo dry-run ──> dry_run.py imprime "SIMULAÇÃO: chamaria {modelo}" e para
        │
        └── modo real (etapa futura, não implementada) ──> executor.executar(modelo, contexto)
                                                                    │
                                                                    ▼
                                                    trata HTTP 200/401/403/429/5xx
                                                                    │
                                                                    ▼
                                                    (etapa futura) registro no Notion,
                                                    revisado manualmente antes de gravar
```

## Por que não há fallback automático

Cada seta do fluxo acima que levaria a uma chamada real passa por um portão
de autorização humana. Isso é deliberado: a Política v2.3 exige autorização
explícita antes de qualquer troca de modelo, e o histórico de testes
manuais (F.4.1–F.7.2) mostrou a importância de não tratar automaticamente
códigos ambíguos (como o 403 do F.7.1) como uma categoria já conhecida.

## Limitações conhecidas desta versão

- `credencial.py` depende do Windows Credential Manager — não é portável
  para outros sistemas operacionais sem um módulo equivalente.
- `contexto.py` não lê o Notion diretamente — recebe um resumo já pronto.
- Não há detecção automática de falha nos agentes principais — a decisão
  de acionar esta camada continua sendo do orquestrador (Claude/Cowork).
- Não há compatibilidade MCP nem conexão com ChatGPT nesta versão.
