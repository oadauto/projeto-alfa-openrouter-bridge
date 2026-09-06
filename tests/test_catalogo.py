from ponte_openrouter import catalogo


MODELOS_BRUTOS_FICTICIOS = [
    {
        "id": "provedor-ficticio/modelo-a:free",
        "name": "Modelo Fictício A",
        "context_length": 128000,
        "description": "Modelo de teste, texto apenas.",
        "pricing": {"prompt": "0", "completion": "0"},
    },
    {
        "id": "provedor-ficticio/modelo-b:free",
        "name": "Modelo Fictício B (multimodal)",
        "context_length": 300000,
        "description": "Modelo de teste com suporte a image e texto.",
        "pricing": {"prompt": "0", "completion": "0"},
    },
    {
        "id": "provedor-ficticio/modelo-pago",
        "name": "Modelo Fictício Pago",
        "context_length": 100000,
        "description": "Modelo de teste pago.",
        "pricing": {"prompt": "0.001", "completion": "0.002"},
    },
    {
        "id": "provedor-ficticio/modelo-free-mas-pago:free",
        "name": "Modelo com sufixo :free mas preço não-zero (dado inconsistente de teste)",
        "context_length": 50000,
        "description": "Caso de borda.",
        "pricing": {"prompt": "0.0005", "completion": "0"},
    },
]


def test_filtra_apenas_free_e_preco_zero():
    resultado = catalogo.filtrar_gratuitos(MODELOS_BRUTOS_FICTICIOS)
    ids = {m.id for m in resultado}
    assert ids == {"provedor-ficticio/modelo-a:free", "provedor-ficticio/modelo-b:free"}


def test_exclui_ids_informados():
    resultado = catalogo.filtrar_gratuitos(
        MODELOS_BRUTOS_FICTICIOS,
        excluir_ids=["provedor-ficticio/modelo-a:free"],
    )
    ids = {m.id for m in resultado}
    assert ids == {"provedor-ficticio/modelo-b:free"}


def test_detecta_multimodal_pela_descricao():
    resultado = catalogo.filtrar_gratuitos(MODELOS_BRUTOS_FICTICIOS)
    por_id = {m.id: m for m in resultado}
    assert por_id["provedor-ficticio/modelo-b:free"].multimodal is True
    assert por_id["provedor-ficticio/modelo-a:free"].multimodal is False


def test_provedor_extraido_do_id():
    resultado = catalogo.filtrar_gratuitos(MODELOS_BRUTOS_FICTICIOS)
    assert all(m.provedor == "provedor-ficticio" for m in resultado)


def test_preco_ausente_nao_quebra():
    modelos = [{"id": "x/y:free", "name": "Y", "context_length": 1000, "description": "", "pricing": {}}]
    resultado = catalogo.filtrar_gratuitos(modelos)
    assert resultado == []
