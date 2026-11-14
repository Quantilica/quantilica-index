"""Releases determinísticas do GitHub, para comparar duas gerações do índice."""

from __future__ import annotations

import re

# Repositórios sem nenhuma release (o gerador os pula).
SEM_RELEASE = {"b3-fetcher", "antt-fetcher", "bcb-sgs-sql", "sidra-sql", "ons-fetcher"}

# Repositório que mudou de nome no GitHub: os dois nomes devolvem as mesmas releases.
RENOMEADOS = {"ibge-sidra-fetcher", "sidra-fetcher"}


def _release(*arquivos: str) -> dict:
    return {
        "assets": [
            {"name": n, "browser_download_url": f"https://exemplo/{n}"}
            for n in arquivos
        ]
    }


def arquivo(distribution: str, versao: str) -> list[str]:
    base = re.sub(r"[-_.]+", "_", distribution)
    return [f"{base}-{versao}-py3-none-any.whl", f"{base}-{versao}.tar.gz"]


def releases_do_repo(repo: str, token: str | None = None) -> list[dict]:
    if repo in SEM_RELEASE:
        return []
    if repo in RENOMEADOS:
        return [
            _release(*arquivo("ibge-sidra-fetcher", "0.12.0")),
            _release(*arquivo("sidra-fetcher", "0.11.0")),
        ]
    return [
        _release(*arquivo(repo, "1.2.3"), "checksums.txt"),
        _release(*arquivo(repo, "1.2.2")),
    ]
