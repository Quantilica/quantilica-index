"""O índice serve `sidra-fetcher` (congelado) e `ibge-sidra-fetcher` (novo)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import gen_pip_index as gen
import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _release(*arquivos: str) -> dict:
    return {
        "assets": [
            {"name": n, "browser_download_url": f"https://exemplo/{n}"}
            for n in arquivos
        ]
    }


ANTIGAS = _release(
    "sidra_fetcher-0.11.0-py3-none-any.whl", "sidra_fetcher-0.11.0.tar.gz"
)
NOVAS = _release(
    "ibge_sidra_fetcher-0.12.0-py3-none-any.whl", "ibge_sidra_fetcher-0.12.0.tar.gz"
)


REGISTRO_SIDRA = """
[ibge-sidra]
docs_pasta = "ibge"

[[ibge-sidra.historico]]
distribution = "sidra-fetcher"
repo = "Quantilica/sidra-fetcher"
id = "sidra"
data = 2026-11-13
"""


@pytest.fixture
def indice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # O renome do SIDRA vem do `historico`, não de uma lista escrita no gerador.
    (tmp_path / "registro.toml").write_text(REGISTRO_SIDRA, encoding="utf-8")
    # Registro publicado: traz os apelidos do fetcher (`ibge` não está no TOML).
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "registry.json").write_text(
        json.dumps(
            {
                "version": 2,
                "fetchers": [
                    {
                        "id": "ibge-sidra",
                        "aliases": ["sidra", "ibge"],
                        "distribution": "ibge-sidra-fetcher",
                        "repo": "https://github.com/Quantilica/ibge-sidra-fetcher",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gen, "OUTROS_PACOTES", [])
    monkeypatch.setattr(gen, "REGISTRO_TOML", tmp_path / "registro.toml")

    def gerar(releases_por_repo: dict[str, list[dict]]):
        monkeypatch.setattr(
            gen,
            "fetch_releases",
            lambda repo, token=None: releases_por_repo.get(repo, []),
        )
        gen.generate_index()
        simple = tmp_path / "public" / "simple"
        fontes = json.loads((tmp_path / "public" / "sources.json").read_text())
        return simple, fontes

    return gerar


def _arquivos(simple: Path, pkg: str) -> list[str]:
    html = (simple / pkg / "index.html").read_text()
    return re.findall(r">([^<>]+)</a>", html)


def test_antes_do_renome_no_github_e_antes_da_release_nova(indice):
    simple, fontes = indice({"sidra-fetcher": [ANTIGAS]})
    assert _arquivos(simple, "sidra-fetcher") == [
        "sidra_fetcher-0.11.0-py3-none-any.whl",
        "sidra_fetcher-0.11.0.tar.gz",
    ]
    assert not (simple / "ibge-sidra-fetcher").exists()
    assert fontes["sidra"] == "sidra-fetcher"
    assert "ibge-sidra" not in fontes


def test_release_nova_no_repo_ainda_chamado_sidra_fetcher(indice):
    simple, fontes = indice({"sidra-fetcher": [NOVAS, ANTIGAS]})
    antigo = _arquivos(simple, "sidra-fetcher")
    novo = _arquivos(simple, "ibge-sidra-fetcher")
    assert antigo == [
        "sidra_fetcher-0.11.0-py3-none-any.whl",
        "sidra_fetcher-0.11.0.tar.gz",
    ]
    assert novo == [
        "ibge_sidra_fetcher-0.12.0-py3-none-any.whl",
        "ibge_sidra_fetcher-0.12.0.tar.gz",
    ]
    assert fontes["ibge-sidra"] == "ibge-sidra-fetcher"


def test_depois_do_renome_o_nome_antigo_redireciona_e_nao_vaza_wheel_nova(indice):
    releases = [NOVAS, ANTIGAS]
    simple, fontes = indice({"ibge-sidra-fetcher": releases, "sidra-fetcher": releases})
    assert all(
        f.startswith("sidra_fetcher-") for f in _arquivos(simple, "sidra-fetcher")
    )
    assert all(
        f.startswith("ibge_sidra_fetcher-")
        for f in _arquivos(simple, "ibge-sidra-fetcher")
    )


def test_apelidos_antigos_do_sources_json_levam_ao_pacote_novo(indice):
    _, fontes = indice({"sidra-fetcher": [NOVAS, ANTIGAS]})
    assert fontes["sidra"] == "ibge-sidra-fetcher"
    assert fontes["ibge"] == "ibge-sidra-fetcher"
    assert fontes["ibge-sidra"] == "ibge-sidra-fetcher"
