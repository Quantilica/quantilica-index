#!/usr/bin/env python3
"""Monta o registro público de fetchers (`registry.json`, versão 2).

Instala do próprio índice as últimas versões dos fetchers declarados no
`registro.toml`, mais o `quantilica-cli`, num venv temporário; roda
`quantilica registry export --strict --json --ecossistema registro.toml` e grava
`public/registry.json` e `public/registry.json.sha256`.

Falha alto (e não escreve nada) se faltar algum id, se sobrar algum, se o
export avisar de qualquer coisa ou se o `sha256` do registro não bater. Uso:

    python scripts/build_registry.py
    python scripts/build_registry.py --index http://127.0.0.1:8000/simple/
    # sem instalar nada: um python que já tem os fetchers e o cli novo
    python scripts/build_registry.py --python .venv/bin/python \\
        --extra-path ../quantilica-cli/src --extra-path ../quantilica-core/src

Códigos de saída: 0 ok; 1 falha; 3 o `quantilica-cli` instalado ainda não tem
`registry export --ecossistema` (o chamador pode manter o registro anterior).
Só stdlib (usa `uv` para o venv).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
INDEX_PADRAO = "https://index.quantilica.com/simple/"
REGISTRY_VERSION_MINIMA = 2
EXIT_CLI_SEM_SUPORTE = 3

# O que o export imprime no stderr e que, aqui, é falha (não só aviso). O cli
# só falha sozinho com `--strict` para parte disso; um repositório assumido
# no lugar do declarado, por exemplo, sai como "Aviso:" e o registro seguiria
# com o dado errado. Só vale o prefixo exato que o cli emite, no começo da
# linha e com a caixa certa: um `print` de fetcher na importação (que o cli
# desvia para o stderr) não casa com "aviso", "AVISO" ou texto indentado. Um
# `print` que imite o prefixo exato derruba o build, o lado seguro.
_LINHA_DE_PROBLEMA = re.compile(
    r"^(Aviso: |Duplicidade: |Falha ao carregar |Identidade: "
    r"|Registro do ecossistema: "
    r"|\d+ fetcher\(s\) sem (seção no registro do ecossistema|info declarada):)"
)


class BuildError(Exception):
    """Falha da montagem do registro (a mensagem vai para o stderr)."""


class CliSemSuporte(BuildError):
    """O cli instalado não conhece `registry export --ecossistema`."""


def ids_do_registro(registro_toml: Path) -> list[str]:
    """Os ids declarados no `registro.toml` (uma seção por id), em ordem."""
    try:
        dados = tomllib.loads(registro_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"{registro_toml}: {exc}") from exc
    if not dados:
        raise BuildError(f"{registro_toml} não declara nenhum fetcher")
    return sorted(dados)


def distribuicao_de(fetcher_id: str) -> str:
    """Distribuição de um fetcher pela regra `<id>-fetcher`."""
    return f"{fetcher_id}-fetcher"


def _normaliza(nome: str) -> str:
    """Nome de projeto normalizado (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nome).lower()


def no_indice(simple_dir: Path, dist: str) -> bool:
    """A distribuição tem página com arquivos em `simple/<dist>/index.html`."""
    pagina = simple_dir / _normaliza(dist) / "index.html"
    try:
        return "href=" in pagina.read_text(encoding="utf-8")
    except OSError:
        return False


def distribuicoes_a_instalar(
    registro_toml: Path,
    *,
    anterior: Path | None = None,
    simple_dir: Path | None = None,
) -> list[str]:
    """A distribuição a instalar para cada id do `registro.toml`, em ordem.

    Para cada id, em ordem de preferência: a `distribution` do registro
    anterior (quando é v2), a regra `<id>-fetcher` e as distribuições do
    `historico`, da mais recente para a mais antiga (o id mudou e a
    distribuição ficou, caso que o core aceita em `check_identidade`). Com
    `simple_dir` (o índice que vai servir a instalação), vale a primeira que
    existe nele: assim nenhuma instalação cai no PyPI por falta de página no
    índice (confusão de dependências). Sem `simple_dir`, vale a primeira.

    Raises:
        BuildError: com `simple_dir`, id sem nenhuma distribuição no índice.
    """
    try:
        dados = tomllib.loads(registro_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BuildError(f"{registro_toml}: {exc}") from exc
    do_anterior: dict[str, str] = {}
    if anterior is not None and anterior.is_file():
        try:
            for f in json.loads(anterior.read_text(encoding="utf-8"))["fetchers"]:
                if f.get("distribution"):
                    do_anterior[f["id"]] = f["distribution"]
        except (ValueError, KeyError, TypeError) as exc:
            print(f"::warning::registro anterior ilegível ({exc!r}); vale a regra")
    dists: list[str] = []
    ausentes: list[str] = []
    for fid in sorted(dados):
        secao = dados[fid] if isinstance(dados[fid], dict) else {}
        candidatas = [do_anterior.get(fid), distribuicao_de(fid)]
        for h in reversed(secao.get("historico") or []):
            if isinstance(h, dict):
                candidatas.append(h.get("distribution"))
        candidatas = list(dict.fromkeys(c for c in candidatas if c))
        if simple_dir is None:
            dists.append(candidatas[0])
            continue
        achada = next((c for c in candidatas if no_indice(simple_dir, c)), None)
        if achada is None:
            ausentes.append(f"{fid} (tentei {', '.join(candidatas)})")
        else:
            dists.append(achada)
    if ausentes:
        raise BuildError(
            f"sem página em {simple_dir} para: {'; '.join(ausentes)}; "
            "não instalo o que o índice não serve (cairia no PyPI)"
        )
    return dists


def sha256_do_conteudo(doc: dict) -> str:
    """SHA-256 de `{version, fetchers}` em JSON canônico (o mesmo do core).

    Chaves ordenadas, sem espaços, UTF-8, sem a chave `sha256`: quem recebe o
    registro recalcula e compara.
    """
    conteudo = {"version": doc["version"], "fetchers": doc["fetchers"]}
    canon = json.dumps(
        conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _rodar(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    except OSError as exc:
        raise BuildError(f"não consegui rodar {cmd[0]}: {exc}") from exc


def prepara_venv(workdir: Path, dists: list[str], index: str, cli_spec: str) -> Path:
    """Cria o venv em `workdir` e instala o cli e as últimas versões dos fetchers.

    Os fetchers vêm do índice (`--index` soma o índice ao PyPI, de onde vêm o
    `quantilica-cli` e as dependências). Devolve o python do venv.
    """
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv não está no PATH")
    venv = workdir / "venv"
    proc = _rodar([uv, "venv", "--quiet", str(venv)])
    if proc.returncode != 0:
        raise BuildError(f"uv venv falhou:\n{proc.stderr}")
    python = venv / "bin" / "python"
    proc = _rodar(
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--python",
            str(python),
            "--index",
            index,
            cli_spec,
            *dists,
        ]
    )
    if proc.returncode != 0:
        raise BuildError(
            f"não instalei o cli e os {len(dists)} fetchers do índice {index}:\n"
            f"{proc.stderr.strip()}"
        )
    return python


def roda_export(
    python: Path | str, registro_toml: Path, extra_paths: list[Path]
) -> tuple[str, str]:
    """Roda `quantilica registry export` e devolve (stdout, stderr).

    Raises:
        CliSemSuporte: o cli não tem a opção `--ecossistema` (release anterior à v2).
        BuildError: o export falhou (`--strict` recusa o que está incompleto).
    """
    env = dict(os.environ)
    if extra_paths:
        antes = env.get("PYTHONPATH")
        caminhos = [str(p) for p in extra_paths] + ([antes] if antes else [])
        env["PYTHONPATH"] = os.pathsep.join(caminhos)
    proc = _rodar(
        [
            str(python),
            "-m",
            "quantilica.cli.cli",
            "registry",
            "export",
            "--strict",
            "--json",
            "--ecossistema",
            str(registro_toml),
        ],
        env=env,
    )
    if proc.returncode == 2 and "--ecossistema" in proc.stderr:
        raise CliSemSuporte(
            "o quantilica-cli instalado não tem `registry export --ecossistema` "
            "(falta a release do cli com o registro v2)"
        )
    if proc.returncode != 0:
        raise BuildError(
            f"quantilica registry export saiu com {proc.returncode}:\n"
            f"{proc.stderr.strip()}"
        )
    return proc.stdout, proc.stderr


def problemas_do_stderr(stderr: str) -> list[str]:
    """As linhas do stderr do export que o build trata como falha."""
    return [
        linha.strip()
        for linha in stderr.splitlines()
        if _LINHA_DE_PROBLEMA.match(linha)
    ]


def confere(doc: dict, ids: list[str]) -> None:
    """Valida o registro exportado contra o `registro.toml` (ids nos dois sentidos).

    Raises:
        BuildError: versão antiga, ids a mais ou a menos, campo do ecossistema
            ausente, fetcher que não carregou ou `sha256` que não bate.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("fetchers"), list):
        raise BuildError("export sem a lista `fetchers`")
    if doc.get("version", 0) < REGISTRY_VERSION_MINIMA:
        raise BuildError(
            f"export na versão {doc.get('version')!r}; preciso da "
            f"{REGISTRY_VERSION_MINIMA} (cli sem o registro v2)"
        )
    exportados = [f.get("id") for f in doc["fetchers"]]
    faltam = sorted(set(ids) - set(exportados))
    sobram = sorted(set(exportados) - set(ids))
    repetidos = sorted({i for i in exportados if exportados.count(i) > 1})
    erros = []
    if faltam:
        erros.append(f"no registro.toml e fora do export: {', '.join(faltam)}")
    if sobram:
        erros.append(f"no export e fora do registro.toml: {', '.join(sobram)}")
    if repetidos:
        erros.append(f"ids repetidos no export: {', '.join(repetidos)}")
    for f in doc["fetchers"]:
        if f.get("error") or f.get("info_declared") is False:
            erros.append(f"{f.get('id')}: fetcher não carregou ou sem info declarada")
        for campo in ("distribution", "module", "repo", "version", "docs_pasta"):
            if not f.get(campo):
                erros.append(f"{f.get('id')}: campo {campo} vazio")
    if erros:
        raise BuildError("; ".join(erros))
    if doc.get("sha256") != sha256_do_conteudo(doc):
        raise BuildError("o sha256 do export não bate com o conteúdo")


# Campos públicos de cada fetcher: os do registro v1 publicado (os mesmos que o
# `PUBLIC_FIELDS` de `infra/registry_build.py` leva ao site aberto) e os da v2.
# Lista fechada: campo novo do export (de execução ou de operação, como `groups`,
# `default_output` ou `ops`) só chega ao público se entrar aqui.
CAMPOS_V1 = (
    "id",
    "nome",
    "aliases",
    "orgao",
    "licenca",
    "homepage",
    "cadencia",
    "dominio",
    "redistribuicao",
    "restricao_nota",
    "entry_point",
)
CAMPOS_V2 = (
    "distribution",
    "module",
    "repo",
    "lake_entry_point",
    "source_id",
    "lake_source_id",
    "version",
    "docs_pasta",
    "vitrine",
    "ci_integracao",
    "json_leve",
    "mascote",
    "health_url",
    "historico",
)
CAMPOS_PUBLICOS = CAMPOS_V1 + CAMPOS_V2


def publica(doc: dict) -> dict:
    """Reduz o export ao registro público e recalcula o `sha256`.

    Cada fetcher fica só com `CAMPOS_PUBLICOS`. O texto de `restricao_nota` (a
    justificativa interna de uma restrição de redistribuição) vai como `null`,
    como no v1 público; `redistribuicao` continua. No topo ficam `version`,
    `fetchers` e `sha256`.

    Raises:
        BuildError: falta algum campo público em um fetcher.
    """
    fetchers = []
    for f in doc["fetchers"]:
        faltam = [k for k in CAMPOS_PUBLICOS if k not in f]
        if faltam:
            raise BuildError(f"{f.get('id')}: campos ausentes no export: {faltam}")
        item = {k: f[k] for k in CAMPOS_PUBLICOS}
        item["restricao_nota"] = None
        fetchers.append(item)
    pub = {"version": doc["version"], "fetchers": fetchers}
    pub["sha256"] = sha256_do_conteudo(pub)
    return pub


def grava(doc: dict, saida: Path) -> tuple[Path, Path]:
    """Grava `registry.json` e `registry.json.sha256` em `saida`, juntos."""
    saida.mkdir(parents=True, exist_ok=True)
    registry = saida / "registry.json"
    checksum = saida / "registry.json.sha256"
    tmp_r = registry.with_name(registry.name + ".tmp")
    tmp_c = checksum.with_name(checksum.name + ".tmp")
    tmp_r.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp_c.write_text(doc["sha256"] + "\n", encoding="utf-8")
    tmp_r.replace(registry)
    tmp_c.replace(checksum)
    return registry, checksum


def monta(
    registro_toml: Path,
    saida: Path,
    *,
    index: str = INDEX_PADRAO,
    cli_spec: str = "quantilica-cli",
    python: Path | str | None = None,
    extra_paths: list[Path] | None = None,
    workdir: Path | None = None,
    simple_dir: Path | None = None,
    anterior: Path | None = None,
) -> dict:
    """Instala, exporta, confere e grava. Devolve o registro publicado."""
    ids = ids_do_registro(registro_toml)
    extra_paths = extra_paths or []
    with tempfile.TemporaryDirectory(prefix="registry-", dir=workdir) as tmp:
        if python is None:
            if simple_dir is None:
                print(
                    "::warning::sem --simple-dir: não confiro que o índice serve "
                    "cada fetcher antes de instalar",
                    file=sys.stderr,
                )
            dists = distribuicoes_a_instalar(
                registro_toml, anterior=anterior, simple_dir=simple_dir
            )
            python = prepara_venv(Path(tmp), dists, index, cli_spec)
        stdout, stderr = roda_export(python, registro_toml, extra_paths)
    if stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    problemas = problemas_do_stderr(stderr)
    if problemas:
        raise BuildError(
            "o export avisou; o registro não é publicado com aviso:\n  "
            + "\n  ".join(problemas)
        )
    try:
        doc, _ = json.JSONDecoder().raw_decode(stdout.lstrip())
    except ValueError as exc:
        raise BuildError(f"export com JSON inválido: {exc}") from exc
    confere(doc, ids)
    pub = publica(doc)
    grava(pub, saida)
    return pub


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--registro", type=Path, default=RAIZ / "registro.toml")
    ap.add_argument("--saida", type=Path, default=Path("public"))
    ap.add_argument("--index", default=INDEX_PADRAO, help="índice PEP 503 dos fetchers")
    ap.add_argument(
        "--simple-dir",
        type=Path,
        help="pasta `simple/` que o --index serve; antes de instalar, exige uma "
        "página para cada fetcher (sem isso a instalação cairia no PyPI)",
    )
    ap.add_argument(
        "--registry-anterior",
        type=Path,
        help="registry.json anterior: a `distribution` dele vale para o id que "
        "foge da regra <id>-fetcher",
    )
    ap.add_argument(
        "--cli-spec",
        default="quantilica-cli",
        help="o que instalar como cli (ex.: 'quantilica-cli>=0.22' ou um caminho)",
    )
    ap.add_argument(
        "--python",
        help="usa este python, que já tem os fetchers e o cli (não cria venv "
        "nem instala nada)",
    )
    ap.add_argument(
        "--extra-path",
        action="append",
        type=Path,
        default=[],
        help="soma ao PYTHONPATH (o cli e o core de um worktree); repetível",
    )
    args = ap.parse_args(argv)
    try:
        pub = monta(
            args.registro,
            args.saida,
            index=args.index,
            cli_spec=args.cli_spec,
            python=args.python,
            extra_paths=args.extra_path,
            simple_dir=args.simple_dir,
            anterior=args.registry_anterior,
        )
    except CliSemSuporte as exc:
        print(f"::warning::{exc}", file=sys.stderr)
        return EXIT_CLI_SEM_SUPORTE
    except BuildError as exc:
        print(f"::error::registry.json não foi montado: {exc}", file=sys.stderr)
        return 1
    print(
        f"registry.json v{pub['version']} com {len(pub['fetchers'])} fetchers "
        f"(sha256 {pub['sha256']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
