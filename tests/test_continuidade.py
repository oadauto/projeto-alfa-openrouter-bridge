"""Testes mínimos da continuidade controlada (ponte_openrouter.continuidade).

Mocks são usados EXCLUSIVAMENTE para impedir rede e consumo de crédito: o
fluxo testado é o código real de `continuidade.py`; só a função
`executor_real.executar_chamada_real` é substituída. Nenhuma credencial real
é lida e nenhuma chamada de rede é feita.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ponte_openrouter import continuidade as c
from ponte_openrouter.executor_real import ResultadoReal

ALVO = "ponte_openrouter.executor_real.executar_chamada_real"
MODELO = "vendor/modelo-teste:free"
SEGREDO = "SEGREDO-NUNCA-PODE-VAZAR-valor-ficticio-sem-padrao-de-segredo"


def _sinal(estado="limite_atingido", fonte="adauto", servico="claude", motivo="cota_atingida"):
    return c.SinalServico(servico=servico, estado=estado, fonte=fonte, motivo=motivo)


def _oferta(**kw):
    bruto = {"id": MODELO, "pricing": {"prompt": "0", "completion": "0"}}
    return c.montar_oferta(_sinal(**kw), MODELO, bruto)


def _respostas(*valores):
    fila = list(valores)
    perguntas: list[str] = []

    def _obter(pergunta: str) -> str:
        perguntas.append(pergunta)
        if not fila:
            raise EOFError
        return fila.pop(0)

    _obter.perguntas = perguntas
    _obter.origem_interativa = True  # simula leitor_interativo (terminal real)
    return _obter


def _tripla():
    return _respostas("claude", MODELO, "AUTORIZO")


def _real(codigo, categoria, texto=None, mensagem="msg"):
    return ResultadoReal(
        modelo_id=MODELO,
        codigo_http=codigo,
        categoria=categoria,
        mensagem=mensagem,
        resposta_paráfrase=texto,
    )


# 1. estado desconhecido (e demais não ofertáveis) não gera oferta
@pytest.mark.parametrize("estado", ["desconhecido", "disponivel", "limite_proximo"])
def test_estado_nao_ofertavel_nao_gera_oferta_nem_chamada(estado):
    with patch(ALVO) as chamada:
        assert c.montar_oferta(_sinal(estado=estado), MODELO) is None
    chamada.assert_not_called()


# 2. sinal sem fonte autorizada (ou inválido) vira desconhecido e não gera oferta
@pytest.mark.parametrize(
    "sinal",
    [
        _sinal(fonte="alguem_qualquer"),
        _sinal(fonte=""),
        _sinal(servico="outro_servico"),
        _sinal(estado="quase_no_limite"),
        "não é um sinal",
    ],
)
def test_sinal_sem_fonte_autorizada_ou_invalido_vira_desconhecido(sinal):
    assert c.estado_efetivo(sinal) == "desconhecido"
    assert c.montar_oferta(sinal, MODELO) is None


# 3. oferta contém serviço, motivo, modelo e custo (ou "indisponível")
def test_oferta_contem_servico_motivo_modelo_e_custo():
    oferta = _oferta(estado="indisponivel", servico="chatgpt", motivo="servico_indisponivel")
    assert oferta is not None
    for trecho in ("chatgpt", c.MOTIVOS["servico_indisponivel"], MODELO, "gratuito", "OpenRouter"):
        assert trecho in oferta.texto
    sem_preco = c.montar_oferta(_sinal(), MODELO, {"id": MODELO})
    assert sem_preco.custo_estimado == "indisponível"
    assert "indisponível" in sem_preco.texto
    pago = c.montar_oferta(_sinal(), MODELO, {"pricing": {"prompt": "0.000001", "completion": "0.000002"}})
    assert pago.custo_estimado.startswith("pago")


# 4. confirmação incompleta, divergente ou inválida bloqueia (sem chamada)
@pytest.mark.parametrize(
    "respostas, perguntas_feitas",
    [
        ((), 1),  # nenhuma resposta (EOF)
        (("claude",), 2),  # falta modelo
        (("claude", MODELO), 3),  # falta autorização
        (("chatgpt", MODELO, "AUTORIZO"), 1),  # serviço divergente: para na 1ª
        (("claude", "outro/modelo:free", "AUTORIZO"), 2),  # modelo divergente: para na 2ª
        (("claude", MODELO, "sim"), 3),  # autorização inválida
        (("claude", MODELO, "autorizo"), 3),  # exige a palavra exata
    ],
)
def test_confirmacao_incompleta_bloqueia(respostas, perguntas_feitas):
    obter = _respostas(*respostas)
    with patch(ALVO) as chamada:
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo", obter)
    chamada.assert_not_called()
    assert len(obter.perguntas) == perguntas_feitas
    assert registro["autorizado"] is False
    assert registro["chamada_realizada"] is False
    assert registro["numero_chamadas"] == 0
    assert registro["categoria"] == "recusado_pelo_humano"


# 5. confirmação tripla permite exatamente uma chamada, direta, sem o laço do orquestrador
def test_confirmacao_tripla_permite_exatamente_uma_chamada_sem_orquestrar():
    with patch(ALVO, return_value=_real(200, "sucesso", "ok")) as chamada, patch(
        "ponte_openrouter.orquestrador.orquestrar"
    ) as orquestrar:
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo", _tripla())
    assert chamada.call_count == 1
    assert chamada.call_args.args == (MODELO, "contexto mínimo")
    assert chamada.call_args.kwargs == {"confirmar_execucao": True}
    orquestrar.assert_not_called()
    assert registro["autorizado"] is True
    assert registro["categoria"] == "sucesso"
    assert registro["status_http"] == 200
    assert registro["numero_chamadas"] == 1
    assert registro["origem_resultado"] == "openrouter"
    assert registro["resposta_caracteres"] == 2  # só o comprimento, nunca o texto
    assert not any(isinstance(v, str) and v == "ok" for v in registro.values())


# 6. 429 do OpenRouter: resultado final, sem retry
def test_http_429_do_openrouter_nao_provoca_retry():
    with patch(ALVO, return_value=_real(429, "indisponibilidade")) as chamada:
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo", _tripla())
    assert chamada.call_count == 1
    assert registro["status_http"] == 429
    assert registro["categoria"] == "indisponibilidade"
    assert registro["origem_resultado"] == "openrouter"
    assert registro["fonte_sinal"] == "adauto"  # o sinal do serviço é outra coisa
    assert registro["retry"] is False


# 7. 5xx e código desconhecido: sem troca de modelo, resultado final
@pytest.mark.parametrize("codigo, categoria", [(503, "indisponibilidade"), (418, "nao_classificado")])
def test_5xx_e_codigo_desconhecido_nao_trocam_de_modelo(codigo, categoria):
    with patch(ALVO, return_value=_real(codigo, categoria)) as chamada:
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo", _tripla())
    assert chamada.call_count == 1
    assert chamada.call_args.args[0] == MODELO
    assert registro["modelo"] == MODELO
    assert registro["troca_de_modelo"] is False
    assert registro["fallback_utilizado"] is False
    assert registro["categoria"] == categoria


# 8. segredo não aparece na saída nem no registro
def test_segredo_nao_aparece_na_saida_nem_no_registro(capsys):
    oferta = c.montar_oferta(_sinal(motivo=SEGREDO), MODELO, {"id": MODELO, "pricing": {"prompt": "0", "completion": "0"}})  # motivo livre é descartado
    assert SEGREDO not in oferta.texto

    resultado = _real(200, "sucesso", texto=f"resposta com {SEGREDO}", mensagem=f"Bearer {SEGREDO}")
    with patch(ALVO, return_value=resultado):
        r1 = c.executar_oferta_confirmada(oferta, f"prompt com {SEGREDO}", _tripla())
    with patch(ALVO, side_effect=RuntimeError(f"falha Bearer {SEGREDO}")):
        r2 = c.executar_oferta_confirmada(oferta, "contexto mínimo", _tripla())
    with patch(ALVO) as chamada:
        r3 = c.executar_oferta_confirmada(oferta, "contexto mínimo", _respostas(SEGREDO))
    chamada.assert_not_called()

    for registro in (r1, r2, r3):
        assert SEGREDO not in json.dumps(registro, ensure_ascii=False)
    assert r2["categoria"] == "falha_execucao"
    assert r2["tipo_erro"] == "RuntimeError"
    assert r2["numero_chamadas"] == 1  # a tentativa ocorreu; nada foi repetido
    assert SEGREDO not in capsys.readouterr().out


# 9. Oferta forjada à mão (não produzida por montar_oferta) é rejeitada antes de qualquer pergunta ou chamada
@pytest.mark.parametrize(
    "campo, valor",
    [
        ("estado", "disponivel"),  # estado não ofertável
        ("servico", SEGREDO),  # serviço fora do conjunto fechado (e não pode ecoar)
        ("fonte", "alguem_qualquer"),
        ("modelo_id", "modelo com espaço"),
        ("custo_estimado", "grátis, confie"),
        ("texto", "texto adulterado que esconde o custo"),
    ],
)
def test_oferta_forjada_e_rejeitada_sem_perguntar_nem_chamar(campo, valor):
    import dataclasses

    forjada = dataclasses.replace(_oferta(), **{campo: valor})
    obter = _tripla()
    with patch(ALVO) as chamada, pytest.raises(ValueError) as erro:
        c.executar_oferta_confirmada(forjada, "contexto mínimo", obter)
    chamada.assert_not_called()
    assert obter.perguntas == []
    assert SEGREDO not in str(erro.value)


# 10. Respostas pré-gravadas (JSON/lista/pipe) não são confirmação humana: recusa antes de perguntar
def test_respostas_nao_interativas_sao_recusadas_sem_perguntar_nem_chamar():
    fila = ["claude", MODELO, "AUTORIZO"]
    perguntas = []

    def pre_gravado(pergunta):
        perguntas.append(pergunta)
        return fila.pop(0)

    with patch(ALVO) as chamada:
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo", pre_gravado)
    chamada.assert_not_called()
    assert perguntas == []
    assert registro["autorizado"] is False and registro["numero_chamadas"] == 0
    assert registro["motivo_decisao"] == "confirmacao_nao_interativa"
    assert registro["categoria"] == "recusado_pelo_humano"


# 11. Sem terminal real (sem leitor), recusa; com terminal falso mas tty, funciona
class _Falso:
    def __init__(self, tty, linhas=()):
        self._tty, self._linhas, self.escrito = tty, list(linhas), []

    def isatty(self):
        return self._tty

    def readline(self):
        return self._linhas.pop(0) + "\n" if self._linhas else ""

    def write(self, t):
        self.escrito.append(t)

    def flush(self):
        pass


def test_leitor_interativo_exige_terminal_real():
    with pytest.raises(c.SemTerminalInterativoError):
        c.leitor_interativo(lambda: (_Falso(False), _Falso(False)))
    with pytest.raises(c.SemTerminalInterativoError):
        c.leitor_interativo(lambda: (_ for _ in ()).throw(OSError("detalhe do sistema")))
    leitor = c.leitor_interativo(lambda: (_Falso(True, ["abc"]), _Falso(True)))
    assert leitor.origem_interativa is True and leitor("pergunta") == "abc"
    with pytest.raises(EOFError):
        leitor("outra")


def test_sem_leitor_e_sem_terminal_recusa_sem_chamada():
    with patch(ALVO) as chamada, patch.object(c, "_abrir_terminal", side_effect=OSError):
        registro = c.executar_oferta_confirmada(_oferta(), "contexto mínimo")
    chamada.assert_not_called()
    assert registro["motivo_decisao"] == "sem_terminal_interativo" and registro["numero_chamadas"] == 0


# 12. Modelo pago (ou custo indisponível) exige QUARTA confirmação, separada da execução
PAGO = {"id": MODELO, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}


def test_modelo_pago_exige_quarta_confirmacao_de_custo():
    oferta = c.montar_oferta(_sinal(), MODELO, PAGO)
    assert oferta.custo_estimado.startswith("pago")
    # sem a 4ª: recusa, sem chamada
    with patch(ALVO) as chamada:
        r = c.executar_oferta_confirmada(oferta, "contexto mínimo", _tripla())
    chamada.assert_not_called()
    assert r["autorizado"] is False and r["motivo_decisao"] == "resposta_ausente_custo"
    # 4ª errada
    with patch(ALVO) as chamada:
        r = c.executar_oferta_confirmada(oferta, "contexto mínimo", _respostas("claude", MODELO, "AUTORIZO", "AUTORIZO"))
    chamada.assert_not_called()
    assert r["motivo_decisao"] == "confirmacao_divergente_custo"
    # 4ª correta: exatamente uma chamada
    obter = _respostas("claude", MODELO, "AUTORIZO", "ACEITO O CUSTO")
    with patch(ALVO, return_value=_real(200, "sucesso", "ok")) as chamada:
        r = c.executar_oferta_confirmada(oferta, "contexto mínimo", obter)
    assert chamada.call_count == 1 and len(obter.perguntas) == 4 and r["autorizado"] is True
    # custo indisponível também conta como não gratuito
    sem_preco = c.montar_oferta(_sinal(), MODELO, {"id": MODELO})
    with patch(ALVO) as chamada:
        r = c.executar_oferta_confirmada(sem_preco, "contexto mínimo", _tripla())
    chamada.assert_not_called()
    # gratuito continua com 3
    obter = _tripla()
    with patch(ALVO, return_value=_real(200, "sucesso", "ok")):
        c.executar_oferta_confirmada(_oferta(), "contexto mínimo", obter)
    assert len(obter.perguntas) == 3
