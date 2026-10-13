"""Testes do verificador de segredos (scripts/verificar_segredos.py).

Nenhuma rede, nenhuma credencial real. Os valores "segredo" abaixo são
FICTÍCIOS e montados em tempo de execução (concatenação), para que este
próprio arquivo não contenha nenhum literal que o verificador reconheça.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verificar_segredos as vs  # noqa: E402

CORPO = "A1b2C3d4" * 6  # 48 caracteres alfanuméricos fictícios


def _chave_openrouter() -> str:
    return "sk-" + "or-v1-" + CORPO


def _token_github() -> str:
    return "gh" + "p_" + CORPO[:40]


def _bearer() -> str:
    return "Bearer" + " " + CORPO[:30]


def _ambiente_git_isolado() -> dict[str, str]:
    """Ambiente hermético para os repositórios temporários: ignora a
    configuração global/do sistema do Git da máquina (gitignore global que
    esconda `.env` ou `*.pem`, assinatura de commit, hooks, autocrlf...). Não
    altera nenhuma configuração global: só vale para estes subprocessos."""
    ambiente = dict(os.environ)
    ambiente["GIT_CONFIG_GLOBAL"] = os.devnull
    ambiente["GIT_CONFIG_NOSYSTEM"] = "1"
    ambiente["GIT_TERMINAL_PROMPT"] = "0"
    return ambiente


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_ambiente_git_isolado(),
    )


def _repo(tmp_path: Path, arquivos: dict[str, str]) -> Path:
    """Cria um repositório temporário com identidade local própria (nunca a
    identidade global do usuário) e commita todos os arquivos, inclusive os
    que um gitignore global esconderia (`add -f`)."""
    _git(tmp_path, "init", "-q")
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "ALFA test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "alfa-test@example.invalid"], check=True)
    _git(tmp_path, "config", "commit.gpgsign", "false")
    for nome, conteudo in arquivos.items():
        destino = tmp_path / nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")
    _git(tmp_path, "add", "-f", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _rodar(raiz: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "verificar_segredos.py"), "--raiz", str(raiz), *extra],
        capture_output=True,
        text=True,
        timeout=60,
        env=_ambiente_git_isolado(),
    )


@pytest.mark.parametrize(
    "texto, padrao",
    [
        (f"x = '{_chave_openrouter()}'", "chave_openrouter"),
        (f"token {_token_github()}", "token_github"),
        (f"Authorization: {_bearer()}", "bearer_literal"),
        ("api_key = '" + CORPO[:24] + "'", "atribuicao_de_segredo"),
        ("-----BEGIN " + "PRIVATE KEY-----", "chave_privada"),
    ],
)
def test_padroes_conhecidos_sao_detectados(texto, padrao):
    assert (1, padrao) in vs.escanear_texto(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "texto comum sem credencial",
        "SEGREDO = 'valor-ficticio-curto'",  # nome não reconhecido
        "Bearer {SEGREDO}",  # placeholder de f-string, não um token
        "sk-or-abc123",  # curto demais para ser uma chave
        "token = os.environ['X']",  # sem literal
        "api_key = 'curta'",
    ],
)
def test_texto_inocente_nao_gera_achado(texto):
    assert vs.escanear_texto(texto) == []


def test_marcador_de_permissao_ignora_a_linha():
    assert vs.escanear_texto(f"x = '{_chave_openrouter()}'  # {vs.MARCADOR_PERMITIDO}") == []


def test_saida_nunca_imprime_o_valor_encontrado(tmp_path):
    chave = _chave_openrouter()
    raiz = _repo(tmp_path, {"cfg.py": f"CHAVE = '{chave}'\n", "ok.py": "x = 1\n"})
    processo = _rodar(raiz)
    saida = processo.stdout + processo.stderr
    assert processo.returncode == 1
    assert "cfg.py:1 [chave_openrouter]" in saida
    assert chave not in saida and CORPO not in saida
    assert "ok.py" not in saida


def test_repositorio_limpo_retorna_zero(tmp_path):
    raiz = _repo(tmp_path, {"a.py": "x = 1\n", "docs/n.md": "texto\n"})
    processo = _rodar(raiz)
    assert processo.returncode == 0 and "OK:" in processo.stdout


@pytest.mark.parametrize("nome", ["catalogo.json", "catalogo_novo.json", "logs/continuidade.jsonl", ".env", "chave.pem"])
def test_caminho_proibido_rastreado_falha(tmp_path, nome):
    raiz = _repo(tmp_path, {nome: "{}\n"})
    processo = _rodar(raiz)
    assert processo.returncode == 1
    assert f"PROIBIDO-RASTREADO: {nome}" in processo.stdout


def test_arquivo_nao_rastreado_nunca_e_lido(tmp_path):
    raiz = _repo(tmp_path, {"a.py": "x = 1\n"})
    (raiz / "local.py").write_text(f"CHAVE = '{_chave_openrouter()}'\n", encoding="utf-8")  # não adicionado ao git
    processo = _rodar(raiz)
    assert processo.returncode == 0 and "local.py" not in processo.stdout


def test_executar_orquestrador_e_catalogo_nao_sao_abertos_mesmo_se_rastreados(tmp_path):
    conteudo = f"CHAVE = '{_chave_openrouter()}'\n"
    raiz = _repo(tmp_path, {"scripts/executar_orquestrador.py": conteudo})
    achados = vs.escanear_arvore(raiz, vs.arquivos_rastreados(raiz))
    assert achados == []  # excluído por caminho: o conteúdo nem é lido


def test_historico_pega_segredo_inserido_e_removido_no_mesmo_intervalo(tmp_path):
    raiz = _repo(tmp_path, {"a.py": "x = 1\n"})

    def git(*args: str) -> None:
        _git(raiz, *args)

    git("branch", "-M", "main")
    git("switch", "-q", "-c", "feature")
    (raiz / "a.py").write_text(f"x = '{_chave_openrouter()}'\n", encoding="utf-8")
    git("commit", "-q", "-am", "adiciona")
    (raiz / "a.py").write_text("x = 1\n", encoding="utf-8")  # removido no commit seguinte
    git("commit", "-q", "-am", "remove")

    assert _rodar(raiz).returncode == 0  # a árvore final está limpa
    processo = _rodar(raiz, "--historico", "main")
    assert processo.returncode == 1
    assert "SEGREDO-SUSPEITO-NO-HISTORICO" in processo.stdout and "a.py [chave_openrouter]" in processo.stdout
    assert _chave_openrouter() not in processo.stdout + processo.stderr


def test_erro_de_uso_e_de_git_retornam_2_sem_vazar(tmp_path):
    assert _rodar(tmp_path / "inexistente").returncode == 2
    assert subprocess.run(
        [sys.executable, str(SCRIPTS / "verificar_segredos.py"), "--opcao-invalida"],
        capture_output=True, text=True, timeout=60,
    ).returncode == 2


def test_repositorio_real_nao_tem_segredo_nem_caminho_proibido():
    # Roda sobre o próprio repositório (somente arquivos rastreados). Em um
    # checkout sem .git (ex.: zip), o teste é ignorado.
    raiz = SCRIPTS.parent
    if not (raiz / ".git").exists():
        pytest.skip("sem .git")
    processo = _rodar(raiz)
    assert processo.returncode == 0, processo.stdout
