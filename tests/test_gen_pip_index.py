"""O índice serve `sidra-fetcher` (congelado) e `ibge-sidra-fetcher` (novo)."""

from __future__ import annotations

import json
import re
import urllib.error
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


# --- Consulta das releases (sem rede: urlopen falso) --------------------------


class _RespostaFalsa:
    """Uma resposta da API: corpo JSON, status e o cabeçalho `Link`."""

    def __init__(self, pagina: object, link: str | None = None, status: int = 200):
        self._corpo = json.dumps(pagina).encode("utf-8")
        self.status = status
        self.headers = {"Link": link} if link else {}

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _falsifica_urlopen(monkeypatch, respostas: dict[str, object]):
    """Substitui `urlopen` por um roteador por URL.

    O valor por URL é um `_RespostaFalsa` ou uma exceção, para simular falha.
    Devolve a lista de URLs chamadas.
    """
    chamadas: list[str] = []

    def falso_urlopen(req, timeout=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        chamadas.append(url)
        resposta = respostas[url]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(gen.urllib.request, "urlopen", falso_urlopen)
    respostas["__chamadas__"] = chamadas  # type: ignore[assignment]
    return chamadas


def test_consulta_segue_a_paginacao_da_api(monkeypatch):
    pagina1 = [{"tag_name": "v1"}]
    pagina2 = [{"tag_name": "v2"}, {"tag_name": "v3"}]
    url1 = f"https://api.github.com/repos/{gen.ORG_NAME}/anac-fetcher/releases?per_page=100"
    url2 = "https://api.github.com/repos/Quantilica/anac-fetcher/releases?per_page=100&page=2"
    respostas: dict[str, object] = {
        url1: _RespostaFalsa(pagina1, f'<{url2}>; rel="next", <{url2}>; rel="last"'),
        url2: _RespostaFalsa(pagina2),
    }
    chamadas = _falsifica_urlopen(monkeypatch, respostas)

    releases = gen.fetch_releases("anac-fetcher", token=None)

    assert releases == pagina1 + pagina2
    assert chamadas == [url1, url2]


def test_consulta_falha_eleva_erro_que_aborta_o_build(monkeypatch):
    url = f"https://api.github.com/repos/{gen.ORG_NAME}/anac-fetcher/releases?per_page=100"
    for falha in (
        urllib.error.URLError("fora do ar"),
        _RespostaFalsa([], status=500),
    ):
        _falsifica_urlopen(monkeypatch, {url: falha})
        with pytest.raises(gen.ErroConsultaReleases):
            gen.fetch_releases("anac-fetcher")


def test_consulta_com_json_invalido_eleva_erro(monkeypatch):
    url = f"https://api.github.com/repos/{gen.ORG_NAME}/anac-fetcher/releases?per_page=100"

    class CorpoRuim(_RespostaFalsa):
        def read(self):
            return b"<!doctype html> Gateway Timeout"

    _falsifica_urlopen(monkeypatch, {url: CorpoRuim([])})
    with pytest.raises(gen.ErroConsultaReleases):
        gen.fetch_releases("anac-fetcher")


# --- Fragmente sha256 e data-requires-python nos links ------------------------


def test_falha_ao_consultar_releases_aborta_o_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "public").mkdir()
    monkeypatch.setattr(gen, "OUTROS_PACOTES", [])
    monkeypatch.setattr(gen, "REGISTRO_TOML", tmp_path / "registro.toml")
    (tmp_path / "registro.toml").write_text(REGISTRO_ANAC, encoding="utf-8")

    def falha(repo, token=None):
        raise gen.ErroConsultaReleases("anac-fetcher: HTTP 500")

    monkeypatch.setattr(gen, "fetch_releases", falha)
    with pytest.raises(gen.ErroConsultaReleases, match="HTTP 500"):
        gen.generate_index()
    # Nada é publicado: nem página de pacote, nem raiz, nem sources.json.
    simple = tmp_path / "public" / "simple"
    assert not (simple / "anac-fetcher" / "index.html").exists()
    assert not (simple / "index.html").exists()
    assert not (tmp_path / "public" / "sources.json").exists()


def test_fragmento_sha256_so_com_hex_de_64_digitos():
    hex_ok = "a" * 64
    assert gen.fragmento_sha256(f"sha256:{hex_ok}") == f"#sha256={hex_ok}"
    assert gen.fragmento_sha256(hex_ok.upper()) == f"#sha256={hex_ok}"
    for digest in (None, "", "md5:" + hex_ok, f"sha256:z{'b' * 62}", "sha256:abc"):
        assert gen.fragmento_sha256(digest) == ""


REGISTRO_ANAC = """
[anac]
docs_pasta = "aviacao"
"""

REGISTRO_COM_PYTHON = REGISTRO_ANAC + 'requires_python = ">=3.12"\n'


@pytest.fixture
def gerador(tmp_path, monkeypatch):
    """Gera o índice para um `registro.toml` dado, com releases falsas (sem rede)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(gen, "OUTROS_PACOTES", [])
    monkeypatch.setattr(gen, "REGISTRO_TOML", tmp_path / "registro.toml")
    (tmp_path / "public").mkdir()

    def gerar(registro_toml: str, releases: list[dict]) -> Path:
        (tmp_path / "registro.toml").write_text(registro_toml, encoding="utf-8")
        monkeypatch.setattr(gen, "fetch_releases", lambda repo, token=None: releases)
        gen.generate_index()
        return tmp_path / "public" / "simple"

    return gerar


def test_links_com_e_sem_digest_sha256(gerador):
    digeste = _release("anac_fetcher-1.2.3-py3-none-any.whl")
    digeste["assets"][0]["digest"] = "sha256:" + "ab" * 32
    simple = gerador(REGISTRO_ANAC, [digeste, _release("anac_fetcher-1.2.2.tar.gz")])
    html = (simple / "anac-fetcher" / "index.html").read_text()
    assert (
        f'href="https://exemplo/anac_fetcher-1.2.3-py3-none-any.whl#sha256={"ab" * 32}"'
    ) in html
    # Sem `digest`, o link fica como antes (a paridade da referência cobre isso).
    assert 'href="https://exemplo/anac_fetcher-1.2.2.tar.gz"' in html


def test_requires_python_escapado_no_atributo_do_link(gerador):
    simple = gerador(REGISTRO_COM_PYTHON, [_release("anac_fetcher-1.2.3.tar.gz")])
    html = (simple / "anac-fetcher" / "index.html").read_text()
    assert 'data-requires-python="&gt;=3.12"' in html


def test_requires_python_nao_vaza_para_a_distribuicao_do_historico(gerador):
    toml = REGISTRO_COM_PYTHON.replace("[anac]", "[ibge-sidra]")
    historico = """
[[ibge-sidra.historico]]
distribution = "sidra-fetcher"
repo = "Quantilica/sidra-fetcher"
id = "sidra"
data = 2026-11-13
"""
    releases = [
        _release("ibge_sidra_fetcher-0.12.0.tar.gz"),
        _release("sidra_fetcher-0.11.0.tar.gz"),
    ]
    simple = gerador(toml + historico, releases)
    novo = (simple / "ibge-sidra-fetcher" / "index.html").read_text()
    antigo = (simple / "sidra-fetcher" / "index.html").read_text()
    assert 'data-requires-python="&gt;=3.12"' in novo
    assert "data-requires-python" not in antigo


def test_requires_python_invalido_no_toml_e_ignorado_com_aviso(tmp_path, capsys):
    toml = REGISTRO_COM_PYTHON.replace(
        'requires_python = ">=3.12"', "requires_python = 3.12"
    )
    (tmp_path / "registro.toml").write_text(toml, encoding="utf-8")
    registro = gen.carrega_registro(
        tmp_path / "registro.toml", tmp_path / "nao-existe.json"
    )
    assert registro.requires_python_por_distribuicao == {}
    assert "[anac].requires_python ignorado" in capsys.readouterr().out
