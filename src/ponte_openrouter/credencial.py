"""Leitura segura da chave de API a partir do Windows Credential Manager.

REGRA NÃO NEGOCIÁVEL: a chave nunca é escrita em disco, log, variável de
ambiente persistente, ou output de teste. Esta função devolve a chave em
memória, para uso imediato pelo chamador, que deve descartá-la assim que
possível.

Esta versão NÃO é chamada por nenhum teste automatizado com uma chave
real - os testes usam um "FakeCredentialReader" que nunca toca no
Credential Manager de verdade (ver tests/test_executor_mock.py).
"""

from __future__ import annotations

import subprocess
from typing import Protocol


class LeitorDeCredencial(Protocol):
    def obter_chave(self, target: str) -> str: ...


class CredentialManagerReader:
    """Leitor real, via PowerShell + módulo CredentialManager.

    Não é exercitado pelos testes unitários (que usam um dublê/fake) -
    exige o ambiente Windows real do usuário e o Credential Manager já
    configurado (Target 'ProjetoAlfa-OpenRouter', como usado nos testes
    manuais F.4-F.7).
    """

    def obter_chave(self, target: str = "ProjetoAlfa-OpenRouter") -> str:
        comando = (
            f"$cred = Get-StoredCredential -Target '{target}'; "
            "$cred.GetNetworkCredential().Password"
        )
        resultado = subprocess.run(
            ["powershell", "-NoProfile", "-Command", comando],
            capture_output=True,
            text=True,
            check=True,
        )
        chave = resultado.stdout.strip()
        if not chave:
            raise RuntimeError(
                "Credencial vazia ou não encontrada no Credential Manager "
                f"(target={target}). Nenhuma chave foi exposta nesta mensagem."
            )
        return chave
