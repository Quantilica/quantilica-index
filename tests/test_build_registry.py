"""`scripts/build_registry.py` com o export mockado (nada de instalar 25 pacotes)."""

from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import build_registry as br
import pytest

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures"
REGISTRO_TOML = RAIZ / "registro.toml"
# Amostra do export v2 (b3 e ibge-sidra) feita pelo core: fixa o algoritmo do sha256.
AMOSTRA = json.loads((FIXTURES / "registry_v2_amostra.json").read_text("utf-8"))
IDS_AMOSTRA = ["b3", "ibge-sidra"]
NOTA_B3 = "Termos de uso da B3 vedam coleta automatizada"


def amostra() -> dict:
    return copy.deepcopy(AMOSTRA)


def com_sha(doc: dict) -> dict:
    doc["sha256"] = br.sha256_do_conteudo(doc)
    return doc


# --- sha256 ----------------------------------------------------------------


def test_sha256_igual_ao_do_core():
    assert br.sha256_do_conteudo(AMOSTRA) == AMOSTRA["sha256"]


def test_sha256_ignora_a_propria_chave_e_depende_do_conteudo():
    doc = amostra()
    doc["sha256"] = "x"
    assert br.sha256_do_conteudo(doc) == AMOSTRA["sha256"]
    doc["fetchers"][0]["nome"] = "outro"
    assert br.sha256_do_conteudo(doc) != AMOSTRA["sha256"]


# --- registro.toml x export ------------------------------------------------


def _ids_publicados_14_11() -> set[str]:
    v1 = json.loads(
        (FIXTURES / "referencia_2026_11_14" / "registry.json").read_text("utf-8")
    )
    return {f["id"] for f in v1["fetchers"]}


def test_retrato_de_14_11_fecha_com_o_registro_toml_de_14_11():
    """O retrato congelado e o `registro.toml` de então têm os mesmos 25 ids."""
    declarados = set(
        br.ids_do_registro(FIXTURES / "referencia_2026_11_14" / "registro.toml")
    )
    publicados = _ids_publicados_14_11()
    assert declarados - publicados == set(), "no registro.toml e fora do registro"
    assert publicados - declarados == set(), "no registro e fora do registro.toml"
    assert len(declarados) == 25


def test_registro_toml_vivo_nao_perde_id_de_14_11():
    """Fetcher novo e renome não quebram o teste; sumir um id de 14/11 quebra.

    Cada id do retrato de 14/11 continua no `registro.toml` vivo, direto ou como
    id anterior de alguma seção (`historico`).
    """
    vivo = tomllib.loads(REGISTRO_TOML.read_text("utf-8"))
    conhecidos = set(vivo)
    for secao in vivo.values():
        for h in secao.get("historico", []):
            conhecidos.add(h["id"])
    assert _ids_publicados_14_11() - conhecidos == set()


def test_registro_toml_valido_para_o_core():
    """Com o core v2 à mão, o `registro.toml` passa na validação dele."""
    core = pytest.importorskip("quantilica.core.registry")
    if not hasattr(core, "carrega_registro_ecossistema"):
        pytest.skip("quantilica-core sem o registro v2")
    ids = br.ids_do_registro(REGISTRO_TOML)
    eco = core.carrega_registro_ecossistema(REGISTRO_TOML, ids)
    assert sorted(eco) == ids


@pytest.mark.skipif(
    "REGISTRO_PYTHON" not in os.environ,
    reason="defina REGISTRO_PYTHON com um python que tem os 25 fetchers e o cli v2",
)
def test_export_real_cobre_exatamente_o_registro_toml(tmp_path):
    """Com o ambiente de verdade (opt-in): ids iguais nos dois sentidos."""
    extra = [
        Path(p)
        for p in os.environ.get("REGISTRO_EXTRA_PATH", "").split(os.pathsep)
        if p
    ]
    pub = br.monta(
        REGISTRO_TOML,
        tmp_path,
        python=os.environ["REGISTRO_PYTHON"],
        extra_paths=extra,
    )
    assert sorted(f["id"] for f in pub["fetchers"]) == br.ids_do_registro(REGISTRO_TOML)


# --- confere ---------------------------------------------------------------


def test_confere_aceita_o_export_completo():
    br.confere(amostra(), IDS_AMOSTRA)


def test_confere_recusa_id_que_falta_no_export():
    with pytest.raises(br.BuildError, match="fora do export: rtn"):
        br.confere(amostra(), [*IDS_AMOSTRA, "rtn"])


def test_confere_recusa_id_que_sobra_no_export():
    with pytest.raises(br.BuildError, match="fora do registro.toml: b3"):
        br.confere(amostra(), ["ibge-sidra"])


def test_confere_recusa_versao_antiga():
    doc = com_sha({**amostra(), "version": 1})
    with pytest.raises(br.BuildError, match="versão 1"):
        br.confere(doc, IDS_AMOSTRA)


def test_confere_recusa_sha256_que_nao_bate():
    doc = amostra()
    doc["fetchers"][0]["nome"] = "adulterado"
    with pytest.raises(br.BuildError, match="sha256"):
        br.confere(doc, IDS_AMOSTRA)


@pytest.mark.parametrize(
    "campo", ["distribution", "module", "repo", "version", "docs_pasta"]
)
def test_confere_recusa_campo_de_identidade_vazio(campo):
    doc = amostra()
    doc["fetchers"][0][campo] = None
    with pytest.raises(br.BuildError, match=f"campo {campo} vazio"):
        br.confere(com_sha(doc), IDS_AMOSTRA)


def test_confere_recusa_fetcher_que_nao_carregou():
    doc = amostra()
    doc["fetchers"][0]["error"] = "ImportError: x"
    with pytest.raises(br.BuildError, match="não carregou"):
        br.confere(com_sha(doc), IDS_AMOSTRA)


# --- stderr ----------------------------------------------------------------


@pytest.mark.parametrize(
    "linha",
    [
        "Aviso: anac-fetcher: sem [project.urls] Repository/Source; repo assumido",
        "Duplicidade: id repetido",
        "Falha ao carregar anac: ImportError",
        "Identidade: x: distribuição 'y' foge da regra",
        "1 fetcher(s) sem seção no registro do ecossistema: rtn",
        "1 fetcher(s) sem info declarada: rtn",
    ],
)
def test_problemas_do_stderr_pega_o_que_o_cli_avisa(linha):
    assert br.problemas_do_stderr(f"ruído\n{linha}\n") == [linha]


def test_problemas_do_stderr_ignora_ruido():
    ruido = "/x/y.py:3: DeprecationWarning: algo\n  warnings.warn(...)\n"
    assert br.problemas_do_stderr(ruido) == []


# --- publicação ------------------------------------------------------------


CHAVES_PUBLICAS = {
    "id", "nome", "aliases", "orgao", "licenca", "homepage", "cadencia", "dominio",
    "redistribuicao", "restricao_nota", "entry_point",
    "distribution", "module", "repo", "lake_entry_point", "source_id",
    "lake_source_id", "version", "docs_pasta", "vitrine", "ci_integracao",
    "json_leve", "mascote", "health_url", "historico",
}  # fmt: skip
NAO_PUBLICAS = {
    "groups", "default_output", "freshness_policy", "lake", "error",
    "info_declared", "ops",
}  # fmt: skip


def test_publica_so_com_as_chaves_permitidas():
    doc = amostra()
    for f in doc["fetchers"]:
        f["ops"] = {"pool": "x"}
    assert NAO_PUBLICAS <= set(doc["fetchers"][0]), "a amostra tem de ter os extras"
    pub = br.publica(doc)
    assert set(pub) == {"version", "fetchers", "sha256"}
    for f in pub["fetchers"]:
        assert set(f) == CHAVES_PUBLICAS
    assert set(br.CAMPOS_PUBLICOS) == CHAVES_PUBLICAS


def test_publica_as_chaves_do_v1_publicado_estao_na_lista():
    v1 = json.loads(
        (FIXTURES / "referencia_2026_11_14" / "registry.json").read_text("utf-8")
    )
    assert set(v1["fetchers"][0]) <= set(br.CAMPOS_PUBLICOS)


def test_publica_zera_restricao_nota_e_recalcula_o_sha256():
    doc = amostra()
    b3 = next(f for f in doc["fetchers"] if f["id"] == "b3")
    assert NOTA_B3 in b3["restricao_nota"]
    pub = br.publica(doc)
    assert all(f["restricao_nota"] is None for f in pub["fetchers"])
    assert pub["sha256"] == br.sha256_do_conteudo(pub) != doc["sha256"]
    # `redistribuicao` continua; o original não é alterado.
    assert {f["id"]: f["redistribuicao"] for f in pub["fetchers"]} == {
        f["id"]: f["redistribuicao"] for f in doc["fetchers"]
    }
    assert NOTA_B3 in b3["restricao_nota"]


def test_publica_recusa_fetcher_sem_campo_publico():
    doc = amostra()
    del doc["fetchers"][0]["docs_pasta"]
    with pytest.raises(br.BuildError, match="docs_pasta"):
        br.publica(doc)


# --- monta -----------------------------------------------------------------


def export_ok(doc: dict, stderr: str = ""):
    def fake(python, registro_toml, extra_paths):
        return json.dumps(doc, ensure_ascii=False, indent=2) + "\n", stderr

    return fake


@pytest.fixture
def registro_toml(tmp_path):
    p = tmp_path / "registro.toml"
    p.write_text(
        '[b3]\ndocs_pasta = "mercado-capitais"\n\n[ibge-sidra]\ndocs_pasta = "ibge"\n',
        encoding="utf-8",
    )
    return p


def test_monta_grava_registry_json_e_sha256(tmp_path, registro_toml, monkeypatch):
    monkeypatch.setattr(br, "roda_export", export_ok(amostra()))
    saida = tmp_path / "public"
    pub = br.monta(registro_toml, saida, python="python-falso")
    gravado = json.loads((saida / "registry.json").read_text("utf-8"))
    assert gravado == pub
    assert gravado["version"] == 2
    assert all(f["restricao_nota"] is None for f in gravado["fetchers"])
    assert all(set(f) == CHAVES_PUBLICAS for f in gravado["fetchers"])
    sha = (saida / "registry.json.sha256").read_text("utf-8").strip()
    assert sha == gravado["sha256"] == br.sha256_do_conteudo(gravado)
    assert not list(saida.glob("*.tmp"))


def test_monta_falha_com_aviso_do_export_e_nao_escreve(
    tmp_path, registro_toml, monkeypatch
):
    aviso = "Aviso: b3-fetcher: sem [project.urls] Repository/Source"
    monkeypatch.setattr(br, "roda_export", export_ok(amostra(), aviso))
    saida = tmp_path / "public"
    with pytest.raises(br.BuildError, match="avisou"):
        br.monta(registro_toml, saida, python="python-falso")
    assert not saida.exists()


def test_monta_falha_com_id_faltando_e_nao_escreve(
    tmp_path, registro_toml, monkeypatch
):
    doc = amostra()
    doc["fetchers"] = [f for f in doc["fetchers"] if f["id"] != "b3"]
    monkeypatch.setattr(br, "roda_export", export_ok(com_sha(doc)))
    with pytest.raises(br.BuildError, match="fora do export: b3"):
        br.monta(registro_toml, tmp_path / "public", python="python-falso")
    assert not (tmp_path / "public").exists()


def test_monta_falha_com_json_invalido(tmp_path, registro_toml, monkeypatch):
    monkeypatch.setattr(br, "roda_export", lambda *a: ("não é json", ""))
    with pytest.raises(br.BuildError, match="JSON inválido"):
        br.monta(registro_toml, tmp_path / "public", python="python-falso")


def test_monta_tolera_ruido_no_stderr(tmp_path, registro_toml, monkeypatch):
    monkeypatch.setattr(
        br, "roda_export", export_ok(amostra(), "DeprecationWarning: algo")
    )
    br.monta(registro_toml, tmp_path / "public", python="python-falso")
    assert (tmp_path / "public" / "registry.json").is_file()


def test_registro_toml_vazio_ou_ausente(tmp_path):
    vazio = tmp_path / "vazio.toml"
    vazio.write_text("", encoding="utf-8")
    with pytest.raises(br.BuildError, match="nenhum fetcher"):
        br.ids_do_registro(vazio)
    with pytest.raises(br.BuildError):
        br.ids_do_registro(tmp_path / "nao-existe.toml")


# --- processos (com executáveis falsos) -------------------------------------


def executavel(caminho: Path, corpo: str) -> Path:
    caminho.write_text("#!/bin/sh\n" + corpo, encoding="utf-8")
    caminho.chmod(caminho.stat().st_mode | stat.S_IEXEC)
    return caminho


def test_roda_export_cli_sem_a_opcao_ecossistema(tmp_path):
    py = executavel(
        tmp_path / "python",
        'echo "Error: No such option: --ecossistema" >&2\nexit 2\n',
    )
    with pytest.raises(br.CliSemSuporte):
        br.roda_export(py, tmp_path / "registro.toml", [])


def test_roda_export_falha_do_cli_vira_build_error(tmp_path):
    py = executavel(tmp_path / "python", 'echo "boom" >&2\nexit 1\n')
    with pytest.raises(br.BuildError, match="boom") as exc:
        br.roda_export(py, tmp_path / "registro.toml", [])
    assert not isinstance(exc.value, br.CliSemSuporte)


def test_roda_export_passa_os_argumentos_e_o_pythonpath(tmp_path):
    py = executavel(
        tmp_path / "python",
        'echo "$@" > "$0.args"\necho "$PYTHONPATH" > "$0.path"\necho \'{"a": 1}\'\n',
    )
    out, err = br.roda_export(
        py, tmp_path / "r.toml", [Path("/x/cli"), Path("/x/core")]
    )
    assert json.loads(out) == {"a": 1}
    args = (tmp_path / "python.args").read_text().split()
    assert args[:3] == ["-m", "quantilica.cli.cli", "registry"]
    assert "--strict" in args and "--json" in args
    assert args[args.index("--ecossistema") + 1] == str(tmp_path / "r.toml")
    assert (tmp_path / "python.path").read_text().startswith("/x/cli:/x/core")


def test_prepara_venv_instala_cli_e_um_fetcher_por_id_do_indice(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    executavel(bin_ / "uv", 'echo "$@" >> "' + str(tmp_path / "uv.log") + '"\n')
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    py = br.prepara_venv(
        tmp_path / "w",
        ["b3-fetcher", "ibge-sidra-fetcher"],
        "http://127.0.0.1:1/simple/",
        "quantilica-cli>=0.22",
    )
    assert py == tmp_path / "w" / "venv" / "bin" / "python"
    venv_cmd, install_cmd = (tmp_path / "uv.log").read_text().splitlines()
    assert venv_cmd.startswith("venv")
    assert install_cmd.startswith("pip install")
    assert "--index http://127.0.0.1:1/simple/" in install_cmd
    assert install_cmd.endswith("quantilica-cli>=0.22 b3-fetcher ibge-sidra-fetcher")


def test_prepara_venv_falha_se_a_instalacao_falhar(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    executavel(
        bin_ / "uv",
        'case "$1" in pip) echo "No solution found" >&2; exit 1;; esac\n',
    )
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(br.BuildError, match="No solution found"):
        br.prepara_venv(
            tmp_path / "w", ["b3-fetcher"], "http://x/simple/", "quantilica-cli"
        )


def test_prepara_venv_sem_uv(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(br.BuildError, match="uv"):
        br.prepara_venv(tmp_path / "w", ["b3-fetcher"], "http://x/simple/", "q")


# --- linha de comando --------------------------------------------------------


def roda_script(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "build_registry.py"), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_main_devolve_3_com_cli_sem_suporte(tmp_path, registro_toml):
    py = executavel(
        tmp_path / "python", 'echo "No such option: --ecossistema" >&2\nexit 2\n'
    )
    proc = roda_script(
        "--registro", str(registro_toml), "--python", str(py), cwd=tmp_path
    )
    assert proc.returncode == br.EXIT_CLI_SEM_SUPORTE
    assert "::warning::" in proc.stderr
    assert not (tmp_path / "public").exists()


def test_main_devolve_1_com_falha(tmp_path, registro_toml):
    py = executavel(tmp_path / "python", "echo boom >&2\nexit 1\n")
    proc = roda_script(
        "--registro", str(registro_toml), "--python", str(py), cwd=tmp_path
    )
    assert proc.returncode == 1
    assert "::error::" in proc.stderr
    assert not (tmp_path / "public").exists()


# --- stderr: só o prefixo exato do cli ---------------------------------------


@pytest.mark.parametrize(
    "linha",
    [
        "aviso: do fetcher ao importar",
        "AVISO: do fetcher",
        "  Aviso: texto indentado (continuação)",
        "Avisos recebidos",
        "Identidade confirmada",
        "Duplicidade",
    ],
)
def test_problemas_do_stderr_nao_casa_com_texto_de_fetcher(linha):
    assert br.problemas_do_stderr(linha + "\n") == []


# --- distribuição a instalar (M5, M6) ----------------------------------------


def pagina(simple: Path, dist: str, com_arquivos: bool = True) -> None:
    pasta = simple / dist
    pasta.mkdir(parents=True)
    link = '<a href="https://x/y.whl">y.whl</a>' if com_arquivos else ""
    (pasta / "index.html").write_text(f"<html>{link}</html>", encoding="utf-8")


def toml_de(tmp_path: Path, texto: str) -> Path:
    p = tmp_path / "r.toml"
    p.write_text(texto, encoding="utf-8")
    return p


def test_distribuicoes_pela_regra_sem_indice(tmp_path):
    p = toml_de(tmp_path, '[b3]\ndocs_pasta = "x"\n[ons]\ndocs_pasta = "x"\n')
    assert br.distribuicoes_a_instalar(p) == ["b3-fetcher", "ons-fetcher"]


def test_distribuicoes_prefere_a_do_registro_anterior(tmp_path):
    p = toml_de(tmp_path, '[novo-id]\ndocs_pasta = "x"\n')
    anterior = tmp_path / "anterior.json"
    anterior.write_text(
        json.dumps(
            {"fetchers": [{"id": "novo-id", "distribution": "antigo-nome-fetcher"}]}
        ),
        encoding="utf-8",
    )
    assert br.distribuicoes_a_instalar(p, anterior=anterior) == ["antigo-nome-fetcher"]


def test_distribuicoes_com_id_fora_da_regra_usa_o_historico(tmp_path):
    """O id mudou e a distribuição ficou: só ela existe no índice."""
    p = toml_de(
        tmp_path,
        '[novo-id]\ndocs_pasta = "x"\n[[novo-id.historico]]\n'
        'distribution = "velho-fetcher"\nrepo = "Q/velho-fetcher"\n'
        'id = "velho"\ndata = 2026-11-13\n',
    )
    simple = tmp_path / "simple"
    pagina(simple, "velho-fetcher")
    assert br.distribuicoes_a_instalar(p, simple_dir=simple) == ["velho-fetcher"]


def test_distribuicoes_com_indice_fica_com_a_regra_quando_existe(tmp_path):
    p = toml_de(
        tmp_path,
        '[ibge-sidra]\ndocs_pasta = "ibge"\n[[ibge-sidra.historico]]\n'
        'distribution = "sidra-fetcher"\nrepo = "Q/sidra-fetcher"\n'
        'id = "sidra"\ndata = 2026-11-13\n',
    )
    simple = tmp_path / "simple"
    pagina(simple, "ibge-sidra-fetcher")
    pagina(simple, "sidra-fetcher")
    assert br.distribuicoes_a_instalar(p, simple_dir=simple) == ["ibge-sidra-fetcher"]


def test_distribuicoes_falha_se_o_indice_nao_serve_o_fetcher(tmp_path):
    p = toml_de(tmp_path, '[b3]\ndocs_pasta = "x"\n[ons]\ndocs_pasta = "x"\n')
    simple = tmp_path / "simple"
    pagina(simple, "b3-fetcher")
    pagina(simple, "ons-fetcher", com_arquivos=False)  # página vazia não conta
    with pytest.raises(br.BuildError, match="PyPI") as exc:
        br.distribuicoes_a_instalar(p, simple_dir=simple)
    assert "ons" in str(exc.value) and "b3 (" not in str(exc.value)


def test_monta_instala_so_o_que_o_indice_serve(tmp_path, registro_toml, monkeypatch):
    instaladas = []

    def venv_falso(workdir, dists, index, cli_spec):
        instaladas.extend(dists)
        return "python-falso"

    monkeypatch.setattr(br, "prepara_venv", venv_falso)
    monkeypatch.setattr(br, "roda_export", export_ok(amostra()))
    simple = tmp_path / "simple"
    pagina(simple, "b3-fetcher")
    with pytest.raises(br.BuildError, match="ibge-sidra"):
        br.monta(registro_toml, tmp_path / "public", simple_dir=simple)
    assert instaladas == []  # falhou antes de instalar
    pagina(simple, "ibge-sidra-fetcher")
    br.monta(registro_toml, tmp_path / "public", simple_dir=simple)
    assert instaladas == ["b3-fetcher", "ibge-sidra-fetcher"]
