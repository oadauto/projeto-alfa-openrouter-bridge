"""Execução REAL, mínima, de uma única chamada ao OpenRouter.

Escopo estritamente reduzido (Fase G mínima):
- uma chamada real por execução, nunca mais de uma;
- exige confirmação humana explícita antes da chamada;
- usa a chave apenas em memória (via credencial.CredentialManagerReader);
- nunca grava a chave em arquivo/log;
- classifica o resultado com executor.classificar_http (200/401/403/429/5xx,
  ou "nao_classificado" para qualquer código não mapeado);
- NÃO faz fallback automático em NENHUM dos dois níveis:
  (a) neste módulo, não há retry nem troca de modelo - se falhar, apenas
      informa e para;
  (b) no lado do OpenRouter, o corpo da requisição envia
      "provider": {"allow_fallbacks": false}, impedindo que o roteador
      atenda a chamada por outro provedor do mesmo modelo sem decisão
      humana explícita;
- NÃO grava nada no Notion (isso continua sendo feito manualmente, revisado).

Requer o pacote 'requests' apenas neste módulo (não usado em nenhum outro
módulo do pacote, para manter o resto 100% testável sem rede).
"""

from __future__ import annotations

from dataclasses import dataclass

from .credencial import CredentialManagerReader
from .executor import classificar_http


API_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class ResultadoReal:
    modelo_id: str
    codigo_http: int | None
    categoria: str
    mensagem: str
    resposta_paráfrase: str | None = None


def executar_chamada_real(
    modelo_id: str,
    prompt_ficticio: str,
    confirmar_execucao: bool = False,
) -> ResultadoReal:
    """Faz UMA chamada real ao OpenRouter. Só executa se
    `confirmar_execucao=True` for passado explicitamente pelo chamador
    (o script de linha de comando exige confirmação humana antes disso).
    """
    if not confirmar_execucao:
        return ResultadoReal(
            modelo_id=modelo_id,
            codigo_http=None,
            categoria="nao_executado",
            mensagem="Execução não confirmada - nenhuma chamada foi feita.",
        )

    import requests  # import local: só é necessário neste caminho de execução real

    chave = CredentialManagerReader().obter_chave()
    try:
        resposta = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {chave}"},
            json={
                "model": modelo_id,
                "messages": [{"role": "user", "content": prompt_ficticio}],
                # Bloqueio explícito de fallback automático no lado do
                # OpenRouter: sem isto, o roteador pode, por conta própria,
                # atender a requisição por OUTRO provedor do mesmo modelo
                # quando o provedor primário falha ou está indisponível -
                # exatamente o tipo de troca silenciosa que a política do
                # Projeto ALFA proíbe (nenhuma mudança de provedor/modelo
                # sem decisão humana explícita e registrada). Com
                # allow_fallbacks=False, a falha do provedor primário
                # retorna erro e para aqui, em vez de ser mascarada por um
                # sucesso vindo de um provedor que o usuário não escolheu.
                "provider": {"allow_fallbacks": False},
            },
            timeout=30,
        )
    finally:
        del chave  # descarta a referência à chave assim que a chamada termina

    categoria = classificar_http(resposta.status_code)

    if resposta.status_code == 200:
        corpo = resposta.json()
        texto = corpo.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ResultadoReal(
            modelo_id=modelo_id,
            codigo_http=200,
            categoria=categoria,
            mensagem=f"Sucesso HTTP 200 para '{modelo_id}'.",
            resposta_paráfrase=texto[:300],  # nunca a resposta integral sem limite
        )

    return ResultadoReal(
        modelo_id=modelo_id,
        codigo_http=resposta.status_code,
        categoria=categoria,
        mensagem=f"HTTP {resposta.status_code} ({categoria}) para '{modelo_id}'. Nenhuma nova tentativa foi feita.",
    )
