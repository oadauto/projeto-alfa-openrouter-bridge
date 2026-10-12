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

6. **Executor + registrador** — dividido em dois módulos:
   - `executor.py` — usado no modo dry-run (`executar_dryrun()`); trata
     explicitamente os códigos HTTP 200, 401, 403, 429 e 5xx via
     `classificar_http()`, cada um com uma classificação própria (sucesso
     / problema de credencial / restrição de acesso / indisponibilidade
     / erro de servidor) — nunca inventa uma categoria para um código não
     mapeado; nesse caso, sinaliza como "não classificado" e pede decisão
     humana, no mesmo espírito do tratamento dado ao HTTP 403 observado
     no teste F.7.1 do Projeto ALFA.
   - `executor_real.py` — só é alcançável após a autorização do
     componente 4 E após uma segunda confirmação explícita
     (`confirmar_execucao=True`, mais confirmação interativa no script de
     linha de comando). Faz UMA única chamada real, sem retry e sem troca
     de modelo em caso de falha; usa `"provider": {"allow_fallbacks":
     false}` para impedir fallback automático do lado do OpenRouter;
     reaproveita `classificar_http()` de `executor.py` para classificar o
     resultado; descarta a chave da memória (`del chave`) logo após a
     chamada e nunca grava a chave nem a resposta integral em log ou
     resultado — a resposta é sempre truncada a 300 caracteres.

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
        ├── modo dry-run (padrão) ──> dry_run.py imprime "SIMULAÇÃO: chamaria {modelo}" e para
        │
        └── modo real (requer confirmar_execucao=True + confirmação
             interativa no script) ──> executor_real.executar_chamada_real(modelo, prompt)
                                                                    │
                                                                    ▼
                                                    trata HTTP 200/401/403/429/5xx
                                                    (via executor.classificar_http)
                                                    sem retry, sem troca de provedor
                                                    (provider.allow_fallbacks=false)
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

Além do portão de autorização (nível de política), há um controle técnico
equivalente no nível da chamada HTTP: `executor_real.py` envia
`"provider": {"allow_fallbacks": false}` no corpo da requisição ao
OpenRouter, impedindo que o próprio roteador atenda a chamada por outro
provedor do mesmo modelo sem decisão humana. Adicionalmente, o módulo não
implementa retry nem troca de modelo em caso de falha — se a chamada
falhar, apenas informa o resultado e para.

## Continuidade controlada (`continuidade.py`)

Camada que OFERECE o OpenRouter quando Claude ou ChatGPT estao no limite ou
indisponiveis. Complementa o componente 1 (detector de falha) sem
automatiza-lo: o estado do servico e informado por uma fonte autorizada
(`FONTES_AUTORIZADAS`); o modulo nao detecta nem calcula cota.

```
SinalServico (fonte autorizada informa o estado)
        |
        v
estado_efetivo()  -- fonte/servico/estado invalido --> desconhecido (sem oferta)
        |
        +-- disponivel / limite_proximo / desconhecido --> nenhuma oferta, nenhuma chamada
        |
        +-- limite_atingido / indisponivel
                |
                v
        montar_oferta()  (servico, motivo, modelo, custo estimado - so texto)
                |
                v
        confirmar_tripla()  servico -> modelo -> "AUTORIZO"  (qualquer falha cancela)
                |
                v
        executor_real.executar_chamada_real()   UMA chamada, allow_fallbacks=false
                |
                v
        registro seguro (lista branca) - 200/429/5xx/desconhecido sao resultado final
```

Por que nao ha fallback silencioso: nenhuma chamada ocorre sem as tres
confirmacoes; nao ha retry; nao ha troca de modelo; e o caminho NAO passa por
`orquestrador.orquestrar()`, cujo laco de candidatos pode avancar para outro
modelo apos 429/5xx (com nova confirmacao a cada passo). Aqui o limite e uma
unica chamada por autorizacao.

Sinal x erro do OpenRouter: o sinal de indisponibilidade do Claude/ChatGPT e
entrada (`fonte_sinal`); HTTP 429/5xx e resultado da chamada ao OpenRouter
(`origem_resultado`, `status_http`). Campos separados no registro.

Custo: lido do `pricing` do catalogo; `gratuito` so com prompt e completion
iguais a zero; preco ausente ou ilegivel resulta em `indisponivel`. Um modelo
pago e mostrado como tal na oferta, e a confirmacao tripla vale para ele.

Integracao futura com o adaptador JSON (`adaptador_harness.py`) e com o
cliente local: fora deste ticket, exige ticket e autorizacao proprios.

## Limitações conhecidas desta versão

- `credencial.py` depende do Windows Credential Manager — não é portável
  para outros sistemas operacionais sem um módulo equivalente.
- `contexto.py` não lê o Notion diretamente — recebe um resumo já pronto.
- Não há detecção automática de falha nos agentes principais — a decisão
  de acionar esta camada continua sendo do orquestrador (Claude/Cowork).
  A continuidade controlada (`continuidade.py`) só OFERECE o OpenRouter a
  partir de um sinal informado por fonte autorizada.
- Não há compatibilidade MCP nem conexão com ChatGPT nesta versão.
