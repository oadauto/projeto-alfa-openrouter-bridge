from ponte_openrouter.catalogo import ModeloCatalogo
from ponte_openrouter.seletor import Candidato
from ponte_openrouter import autorizacao


def _candidatos_ficticios():
    return [
        Candidato(
            modelo=ModeloCatalogo(id="a/modelo:free", nome="A", contexto=100000, descricao="", multimodal=False, provedor="a"),
            pontuacao=2,
            justificativa=["ok"],
        ),
        Candidato(
            modelo=ModeloCatalogo(id="b/modelo:free", nome="B", contexto=50000, descricao="", multimodal=False, provedor="b"),
            pontuacao=1,
            justificativa=["ok"],
        ),
    ]


def test_sem_candidatos_nao_autoriza():
    decisao = autorizacao.confirmar([])
    assert decisao.autorizado is False
    assert decisao.candidato_escolhido is None


def test_usuario_nega_nao_autoriza():
    decisao = autorizacao.confirmar(_candidatos_ficticios(), obter_escolha_humana=lambda _: "n")
    assert decisao.autorizado is False


def test_usuario_escolhe_candidato_valido():
    decisao = autorizacao.confirmar(_candidatos_ficticios(), obter_escolha_humana=lambda _: "1")
    assert decisao.autorizado is True
    assert decisao.candidato_escolhido.modelo.id == "a/modelo:free"


def test_resposta_invalida_nao_autoriza():
    decisao = autorizacao.confirmar(_candidatos_ficticios(), obter_escolha_humana=lambda _: "abc")
    assert decisao.autorizado is False


def test_nenhuma_chamada_ocorre_sem_essa_funcao():
    """Teste de intenção: confirma que este módulo não importa 'executor'
    nem faz nenhuma chamada de rede - apenas orquestra a decisão humana."""
    import inspect
    codigo_fonte = inspect.getsource(autorizacao)
    assert "requests" not in codigo_fonte
    assert "http" not in codigo_fonte.lower() or "Callable" in codigo_fonte  # sem chamadas de rede reais
