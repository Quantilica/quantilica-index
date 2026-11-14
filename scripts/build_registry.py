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
# com o dado errado.
_LINHA_DE_PROBLEMA = re.compile(
    r"^\s*(Aviso|Duplicidade|Falha ao carregar|Identidade|Registro do ecossistema)\b"
    r"|sem seção no registro do ecossistema|sem info declarada",
    re.IGNORECASE,
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
        if _LINHA_DE_PROBLEMA.search(linha)
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


def publica(doc: dict) -> dict:
    """Tira do registro o que não é público e recalcula o `sha256`.

    O texto de `restricao_nota` (a justificativa interna de uma restrição de
    redistribuição) não sai no registro público; `redistribuicao` continua.
    """
    pub = {
        **doc,
        "fetchers": [{**f, "restricao_nota": None} for f in doc["fetchers"]],
    }
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
) -> dict:
    """Instala, exporta, confere e grava. Devolve o registro publicado."""
    ids = ids_do_registro(registro_toml)
    extra_paths = extra_paths or []
    with tempfile.TemporaryDirectory(prefix="registry-", dir=workdir) as tmp:
        if python is None:
            dists = [distribuicao_de(i) for i in ids]
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
