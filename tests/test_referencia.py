"""O índice derivado do registro gera o mesmo `simple/` e `sources.json` de antes.

A referência é uma geração com releases determinísticas feita pelo gerador de
14/11 (listas escritas à mão em `gen_pip_index.py`), guardada em
`fixtures/referencia_2026_11_14/esperado.json`, junto com o registro publicado
naquela data, e o `registro.toml` de então (`fixtures/referencia_2026_11_14/
registro.toml`, uma cópia congelada). Rodar o gerador novo sobre essa cópia e o mesmo
registro tem de reproduzir cada arquivo. A cópia é congelada de propósito: o
`registro.toml` vivo muda a cada renome ou fetcher novo, e esta paridade não pode
depender dele.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import gen_pip_index as gen
import pytest
import releases_falsas

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures" / "referencia_2026_11_14"
REGISTRO_TOML_14_11 = FIXTURES / "registro.toml"


# As listas que o gerador de 14/11 trazia escritas à mão.
FETCHERS_14_11 = {
    "anac-fetcher", "anp-fetcher", "antt-fetcher", "b3-fetcher",
    "bcb-microdados-fetcher", "bcb-sgs-fetcher", "bcb-sgs-sql", "capes-fetcher",
    "comex-fetcher", "cvm-fetcher", "datasus-fetcher", "inep-fetcher",
    "infosiga-fetcher", "inmet-fetcher", "ipeadata-fetcher", "loterias-fetcher",
    "ons-fetcher", "pdet-fetcher", "pgfn-fetcher", "rfb-cnpj-fetcher",
    "rtn-fetcher", "ibge-sidra-fetcher", "sidra-fetcher", "sidra-sql",
    "sigtap-fetcher", "tesouro-direto-fetcher", "transparencia-sp-fetcher",
    "tse-fetcher", "quantilica-analytics", "quantilica-catalog", "quantilica-sql",
}  # fmt: skip
REPOS_DO_PACOTE_14_11 = {"ibge-sidra-fetcher": ["ibge-sidra-fetcher", "sidra-fetcher"]}
PREFIXO_14_11 = {
    "ibge-sidra-fetcher": "ibge_sidra_fetcher-",
    "sidra-fetcher": "sidra_fetcher-",
}
APELIDOS_14_11 = {"sidra": "ibge-sidra-fetcher", "ibge": "ibge-sidra-fetcher"}


@pytest.fixture(params=["registro_publicado", "so_o_toml"])
def registro(request, tmp_path):
    """O registro do ecossistema com e sem o registry.json publicado em 14/11."""
    publicado = tmp_path / "registry.json"
    if request.param == "registro_publicado":
        shutil.copy(FIXTURES / "registry.json", publicado)
    return gen.carrega_registro(REGISTRO_TOML_14_11, publicado)


def test_listas_derivadas_iguais_as_escritas_a_mao(registro):
    assert set(registro.pacotes) == FETCHERS_14_11
    assert len(registro.pacotes) == len(FETCHERS_14_11)
    assert registro.repos_do_pacote == REPOS_DO_PACOTE_14_11
    assert registro.prefixo_de_arquivo == PREFIXO_14_11


def test_apelidos_de_fonte_so_dos_renomeados(tmp_path):
    # Só com o registro publicado se conhece o apelido `ibge`; sem ele, o id
    # anterior do `historico` basta para o `sidra`.
    publicado = tmp_path / "registry.json"
    shutil.copy(FIXTURES / "registry.json", publicado)
    com = gen.carrega_registro(REGISTRO_TOML_14_11, publicado)
    assert com.apelidos_de_fonte == APELIDOS_14_11
    sem = gen.carrega_registro(REGISTRO_TOML_14_11, tmp_path / "nao-existe.json")
    assert sem.apelidos_de_fonte == {"sidra": "ibge-sidra-fetcher"}


def test_geracao_de_referencia_identica(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "public").mkdir()
    shutil.copy(FIXTURES / "registry.json", tmp_path / "public" / "registry.json")
    monkeypatch.setattr(gen, "fetch_releases", releases_falsas.releases_do_repo)
    gen.generate_index(
        gen.carrega_registro(REGISTRO_TOML_14_11, tmp_path / "public" / "registry.json")
    )

    esperado = json.loads((FIXTURES / "esperado.json").read_text(encoding="utf-8"))
    gerado = {
        str(p.relative_to(tmp_path / "public")): p.read_text(encoding="utf-8")
        for p in sorted((tmp_path / "public").rglob("*"))
        if p.is_file() and p.name != "registry.json"
    }
    assert set(gerado) == set(esperado)
    # `sources.json` é um objeto: a ordem das chaves não é contrato.
    assert json.loads(gerado.pop("sources.json")) == json.loads(
        esperado.pop("sources.json")
    )
    diferentes = sorted(k for k in esperado if gerado[k] != esperado[k])
    assert not diferentes, f"arquivos do simple/ diferentes da referência: {diferentes}"
