# CI e secret scanning

Governança do repositório: todo PR para `main` é validado por dois workflows
do GitHub Actions. Nenhum deles usa credencial, segredo do GitHub ou chamada
ao OpenRouter.

## Workflows

| Arquivo | Job (nome do check) | Quando roda | O que faz |
|---|---|---|---|
| `.github/workflows/ci.yml` | `testes (ubuntu-latest)`, `testes (windows-latest)` | PR para `main`, push em `main` | Instala `requirements.txt` e roda `python -m pytest tests -q` (Python 3.12) |
| `.github/workflows/seguranca.yml` | `varredura de segredos` | PR para `main`, push em `main`, toda segunda-feira 05:17 UTC | Roda `scripts/verificar_segredos.py` na árvore rastreada e, nos PRs, no histórico do intervalo `origin/<base>..HEAD` |

Ambos usam `permissions: contents: read`, `pull_request` (nunca
`pull_request_target`), `persist-credentials: false` no checkout, timeout e
cancelamento de execuções antigas da mesma ref. Não referenciam `secrets.*`,
não publicam artefatos e não usam cache de dados do projeto.

## Garantias de log

- Os comandos dos workflows não imprimem ambiente, prompts, respostas nem
  conteúdo de `logs/`, `catalogo*.json` ou `scripts/executar_orquestrador.py`.
- O pytest roda sem `-s`, `-v` e `--showlocals`, com `--tb=short` e
  `--show-capture=no`: stdout, stderr e logs capturados de um teste que falhou
  não são impressos. Observação: a mensagem de uma asserção falha ainda pode
  citar valores usados no teste; os testes do projeto só usam valores
  fictícios.
- `scripts/verificar_segredos.py` nunca imprime o conteúdo encontrado: só
  `arquivo:linha [padrão]`, `commit arquivo [padrão]` e contagens.
- `tests/test_workflows.py` falha se alguém reintroduzir segredos, gatilho
  perigoso, permissão ampla, upload de artefato, `echo`/`cat`/`printenv`,
  referência a `logs/` ou flags de pytest que vazem saída.

## Secret scanning (`scripts/verificar_segredos.py`)

Só biblioteca padrão e `git`; nenhuma dependência nova.

1. Varre as linhas dos arquivos **rastreados** (`git ls-files`) em busca de
   padrões: chaves OpenRouter/Anthropic/estilo OpenAI, tokens GitHub, chaves
   AWS/Google, tokens Slack, chave privada, `Bearer` literal e atribuições do
   tipo `api_key = "..."`.
2. Com `--historico BASE`, varre as linhas adicionadas por cada commit de
   `BASE..HEAD` (pega segredo inserido e removido no mesmo PR).
3. Falha se estiver rastreado algum caminho proibido: `catalogo*.json`,
   `logs/*.jsonl`, `.env*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`.
4. Nunca abre `scripts/executar_orquestrador.py` nem `catalogo*.json`, mesmo
   que um dia sejam rastreados (arquivos locais, decisão de Adauto).

Códigos de saída: 0 sem achados; 1 achados; 2 erro de uso ou do git.

Falso positivo comprovadamente fictício: acrescente o marcador
`alfa-allow-secret` num comentário da mesma linha. Hoje só duas linhas de
`tests/test_observabilidade.py` o usam (valores com a palavra "ficticio",
criados para testar o saneamento do log). Prefira montar valores falsos em
tempo de execução, como em `tests/test_verificar_segredos.py`.

### Limites (leia antes de confiar)

- É uma varredura por expressões regulares: não mede entropia e não conhece
  todos os formatos de credencial. Complementa, não substitui, o secret
  scanning nativo do GitHub (ver abaixo).
- O histórico varrido no PR é só o do PR. Segredo já enviado ao remoto antes
  disso não é recuperado por este script.
- Se um segredo real for encontrado: revogar/rotacionar a credencial no
  provedor primeiro (para o OpenRouter, a chave `ProjetoAlfa-OpenRouter`),
  depois remover do código. Reescrever histórico só com autorização expressa
  de Adauto.

## Rodar localmente (PowerShell, raiz do repositório)

    py scripts\verificar_segredos.py
    py scripts\verificar_segredos.py --historico origin/main
    py -m pytest tests -q

## Configuração manual no GitHub (ação administrativa de Adauto)

Nada disso é feito pelo código do repositório. Os itens dependem do plano e da
visibilidade do repositório (público/privado), que não foram verificados aqui;
em repositório privado, parte dos recursos exige plano pago.

1. **Rodar os workflows uma vez** (abrir um PR) para que os checks apareçam na
   lista de checks obrigatórios.
2. **Secret scanning nativo e push protection:** *Settings → Code security*
   (ou *Advanced Security*) → ativar *Secret scanning* e *Push protection*.
3. **Proteção da `main`** (*Settings → Rules → Rulesets → New branch ruleset*,
   alvo `main`), conforme a proposta abaixo.

### Proposta de proteção da `main`

| Regra | Valor proposto | Motivo |
|---|---|---|
| Exigir pull request antes do merge | Sim, aprovações exigidas: 0 | Dono único: ninguém pode aprovar o próprio PR; a revisão do Codex é do processo, não do GitHub |
| Exigir checks de status | `testes (ubuntu-latest)` e `varredura de segredos` | CI verde e secret scanning ativo |
| Exigir branch atualizada com a `main` | Sim | Evita merge sobre base desatualizada |
| Bloquear force push | Sim | Preserva o histórico |
| Bloquear exclusão da `main` | Sim | |
| Resolver conversas antes do merge | Sim | |
| Histórico linear | Opcional | Preferência de Adauto |
| Bypass | Ninguém, inclusive administradores, depois da primeira semana estável | Evita atalho que anule a regra |

Entrada gradual: exigir primeiro só `testes (ubuntu-latest)` e
`varredura de segredos`. Incluir `testes (windows-latest)` quando tiver rodado
verde algumas vezes (o job existe mas não foi verificado em runner Windows
antes do primeiro PR).

## Endurecimentos futuros (fora deste ticket)

- Fixar as ações (`actions/checkout`, `actions/setup-python`) por SHA de
  commit, em vez de tag, e acompanhar atualizações com Dependabot para
  `github-actions`.
- `CODEOWNERS` para exigir revisão dos arquivos de workflow e de
  `scripts/verificar_segredos.py`.
- Decidir o destino de `scripts/executar_orquestrador.py` e a retenção de
  logs (decisões abertas de Adauto).
