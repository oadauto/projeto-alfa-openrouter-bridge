import pytest

from ponte_openrouter import executor


@pytest.mark.parametrize(
    "codigo,esperado",
    [
        (200, "sucesso"),
        (401, "problema_de_credencial"),
        (403, "restricao_de_acesso"),
        (429, "indisponibilidade"),
        (500, "indisponibilidade"),
        (503, "indisponibilidade"),
        (418, "nao_classificado"),  # código não mapeado - nunca inventa categoria
    ],
)
def test_classificar_http(codigo, esperado):
    assert executor.classificar_http(codigo) == esperado


def test_executar_dryrun_nunca_faz_chamada_real():
    resultado = executor.executar_dryrun("modelo-ficticio/teste:free", "resumo de teste, sem dados reais")
    assert resultado.modo == "dry-run"
    assert "SIMULAÇÃO" in resultado.mensagem
    assert "modelo-ficticio/teste:free" in resultado.mensagem


def test_executar_dryrun_exige_contexto_nao_vazio():
    with pytest.raises(ValueError):
        executor.executar_dryrun("modelo-ficticio/teste:free", "")


def test_modulo_executor_nao_importa_biblioteca_http_de_producao():
    """Confirma que, nesta versão dry-run, o módulo não importa nenhuma
    biblioteca de chamada HTTP real (requests, urllib, httpx) - garantindo
    que nenhuma chamada de rede é sequer possível a partir deste código."""
    import inspect

    codigo_fonte = inspect.getsource(executor)
    for biblioteca_proibida in ("import requests", "import urllib", "import httpx", "urlopen("):
        assert biblioteca_proibida not in codigo_fonte
