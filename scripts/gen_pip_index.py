#!/usr/bin/env python3
"""Gera índice estático de pacotes Python PEP 503/658 a partir do GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ORG_NAME = "Quantilica"
RAIZ = Path(__file__).resolve().parents[1]
PUBLIC_DIR = Path("public")
SIMPLE_DIR = PUBLIC_DIR / "simple"
# Fatos do ecossistema (um id por seção). É dele que sai a lista de fetchers.
REGISTRO_TOML = RAIZ / "registro.toml"

# Pacotes que não são fetcher, logo não têm seção no `registro.toml`, mas moram
# no índice. `bcb-sgs-sql` e `sidra-sql` estão depreciados (substituídos por
# `quantilica-sql`), mas continuam aqui: o índice é montado a partir das
# releases de cada repositório, e tirá-los da lista apagaria do índice as
# versões já publicadas.
OUTROS_PACOTES = [
    "bcb-sgs-sql",
    "quantilica-analytics",
    "quantilica-catalog",
    "quantilica-sql",
    "sidra-sql",
]

# Renome `sidra-fetcher` -> `ibge-sidra-fetcher` (13/11/2026), sem módulo de
# compatibilidade. Os dois nomes ficam no índice:
# - `sidra-fetcher` é congelado: só as wheels antigas (`sidra_fetcher-*`);
# - `ibge-sidra-fetcher` recebe as novas (`ibge_sidra_fetcher-*`).
# As releases moram no mesmo repositório. Enquanto o GitHub não o renomeia, ele
# se chama `sidra-fetcher`; depois, `sidra-fetcher` redireciona para o nome novo
# e devolve as mesmas releases, por isso o filtro pelo nome do arquivo (PEP 427)
# é o que separa os dois pacotes.
#
# Nada disso é escrito à mão: o `historico` do `registro.toml` diz quais
# distribuições e repositórios o fetcher já teve, e `Registro` deriva daí os
# repositórios a consultar, o prefixo dos arquivos de cada nome e os apelidos
# do `sources.json`.


@dataclass(frozen=True)
class Fetcher:
    """Um fetcher do registro: o que o índice precisa saber dele."""

    id: str
    distribution: str
    repo: str  # nome do repositório atual (sem o dono)
    aliases: tuple[str, ...] = ()
    # (distribuição, repositório, id) anteriores, do mais antigo ao mais recente.
    historico: tuple[tuple[str, str, str], ...] = ()


def normaliza_arquivo(distribution: str) -> str:
    """Prefixo do nome de arquivo (PEP 427) de uma distribuição: `a-b` vira `a_b`."""
    return re.sub(r"[-_.]+", "_", distribution).lower()


@dataclass(frozen=True)
class Registro:
    """Os fetchers do `registro.toml`, com o que o registro publicado acrescenta."""

    fetchers: tuple[Fetcher, ...]
    outros: tuple[str, ...] = tuple(OUTROS_PACOTES)

    @property
    def fetchers_por_distribuicao(self) -> list[str]:
        """Distribuições atuais e anteriores dos fetchers, sem repetir, em ordem."""
        nomes: set[str] = set()
        for f in self.fetchers:
            nomes.add(f.distribution)
            nomes.update(d for d, _, _ in f.historico)
        return sorted(nomes)

    @property
    def pacotes(self) -> list[str]:
        """Todo pacote do índice: fetchers (atuais e do histórico) e os demais."""
        pacotes = self.fetchers_por_distribuicao
        return pacotes + sorted(set(self.outros) - set(pacotes))

    @property
    def repos_do_pacote(self) -> dict[str, list[str]]:
        """Repositórios a consultar por pacote, o atual primeiro e depois os antigos."""
        out: dict[str, list[str]] = {}
        for f in self.fetchers:
            candidatos = [f.repo]
            candidatos += [r for _, r, _ in reversed(f.historico)]
            candidatos = list(dict.fromkeys(candidatos))
            if candidatos != [f.distribution]:
                out[f.distribution] = candidatos
        return out

    @property
    def prefixo_de_arquivo(self) -> dict[str, str]:
        """Prefixo do arquivo de cada nome de um fetcher cuja distribuição mudou."""
        out: dict[str, str] = {}
        for f in self.fetchers:
            antigas = [d for d, _, _ in f.historico if d != f.distribution]
            if not antigas:
                continue
            for dist in (f.distribution, *antigas):
                out[dist] = normaliza_arquivo(dist) + "-"
        return out

    @property
    def apelidos_de_fonte(self) -> dict[str, str]:
        """Apelidos do `sources.json` que não saem do nome do repositório.

        Só os fetchers renomeados: um `quantilica install sidra` (ou `ibge`) de
        um cli antigo, que lê este arquivo, passa a instalar o pacote renomeado
        em vez de congelar na última wheel antiga. Os ids anteriores (`historico`)
        e os apelidos do registro apontam para a distribuição atual.
        """
        out: dict[str, str] = {}
        for f in self.fetchers:
            if not f.historico:
                continue
            nomes = [i for _, _, i in f.historico] + list(f.aliases)
            for nome in nomes:
                if nome != f.id:
                    out.setdefault(nome, f.distribution)
        return out


def _nome_do_repo(repo: str) -> str:
    """`Quantilica/sidra-fetcher` ou a URL do GitHub -> `sidra-fetcher`."""
    return repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def carrega_registro(
    toml_path: Path | None = None, registry_path: Path | None = None
) -> Registro:
    """Lê o `registro.toml` e, se existir, o `registry.json` publicado.

    Os ids vêm só do TOML. O registro publicado (a saída de `build_registry.py`,
    ou a versão anterior dele) acrescenta o que o TOML não sabe: a distribuição
    e o repositório atuais e os apelidos. Sem ele, vale a regra
    `<id>-fetcher` para a distribuição e o repositório.

    Raises:
        OSError, tomllib.TOMLDecodeError: `registro.toml` ilegível ou inválido.
    """
    toml_path = toml_path or REGISTRO_TOML
    registry_path = registry_path or (PUBLIC_DIR / "registry.json")
    declarado = tomllib.loads(toml_path.read_text(encoding="utf-8"))

    publicado: dict[str, dict] = {}
    if registry_path.is_file():
        try:
            doc = json.loads(registry_path.read_text(encoding="utf-8"))
            publicado = {f["id"]: f for f in doc["fetchers"]}
        except (ValueError, KeyError, TypeError) as exc:
            print(
                f"::warning::{registry_path} inválido ({exc}); "
                "valem a regra <id>-fetcher e o historico."
            )

    fetchers = []
    for fid in sorted(declarado):
        secao = declarado[fid]
        pub = publicado.get(fid, {})
        dist = pub.get("distribution") or f"{fid}-fetcher"
        repo = _nome_do_repo(pub["repo"]) if pub.get("repo") else dist
        historico = tuple(
            (h["distribution"].lower(), _nome_do_repo(h["repo"]), h["id"])
            for h in secao.get("historico", [])
        )
        fetchers.append(
            Fetcher(
                id=fid,
                distribution=dist.lower(),
                repo=repo,
                aliases=tuple(pub.get("aliases") or ()),
                historico=historico,
            )
        )
    return Registro(tuple(fetchers))


def asset_do_pacote(
    pkg_name: str, asset_name: str, prefixos: dict[str, str] | None = None
) -> bool:
    """Diz se o arquivo pertence ao pacote (só filtra os pacotes renomeados)."""
    prefixo = (prefixos or {}).get(pkg_name)
    return prefixo is None or asset_name.startswith(prefixo)


def fetch_releases(repo: str, token: str | None = None) -> list[dict]:
    url = f"https://api.github.com/repos/{ORG_NAME}/{repo}/releases"
    headers = {"User-Agent": "quantilica-index-builder"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"Aviso: Não foi possível obter releases de {repo}: {exc}")
    return []


def generate_index(registro: Registro | None = None) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    registro = registro or carrega_registro()
    repos_do_pacote = registro.repos_do_pacote
    prefixos = registro.prefixo_de_arquivo
    SIMPLE_DIR.mkdir(parents=True, exist_ok=True)

    sources_map: dict[str, str] = {}
    packages_found: list[str] = []

    for repo in registro.pacotes:
        pkg_name = repo.lower()
        releases: list[dict] = []
        for candidato in repos_do_pacote.get(pkg_name, [repo]):
            releases = fetch_releases(candidato, token)
            if releases:
                break
        if not releases:
            continue

        links: list[str] = []
        for release in releases:
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                download_url = asset.get("browser_download_url", "")

                is_pkg = (
                    name.endswith(".whl")
                    or name.endswith(".tar.gz")
                    or name.endswith(".zip")
                )
                if is_pkg and asset_do_pacote(pkg_name, name, prefixos):
                    links.append(f'    <a href="{download_url}">{name}</a><br/>')

        # Pacote renomeado sem nenhum arquivo (ainda sem release com o nome
        # novo) não entra no índice: o cli trata o que o índice lista como
        # instalável.
        if pkg_name in prefixos and not links:
            continue

        packages_found.append(pkg_name)

        short_name = pkg_name.replace("-fetcher", "")
        sources_map[short_name] = repo

        pkg_dir = SIMPLE_DIR / pkg_name
        pkg_dir.mkdir(parents=True, exist_ok=True)

        html_content = f"""<!DOCTYPE html>
<html>
  <head>
    <title>Links for {pkg_name}</title>
  </head>
  <body>
    <h1>Links for {pkg_name}</h1>
{"\n".join(links)}
  </body>
</html>
"""
        (pkg_dir / "index.html").write_text(html_content, encoding="utf-8")

    for apelido, repo in registro.apelidos_de_fonte.items():
        if repo in packages_found:
            sources_map[apelido] = repo

    root_links = [
        f'    <a href="{pkg}/">{pkg}</a><br/>' for pkg in sorted(packages_found)
    ]
    root_html = f"""<!DOCTYPE html>
<html>
  <head>
    <title>Simple Index</title>
  </head>
  <body>
    <h1>Simple Index</h1>
{"\n".join(root_links)}
  </body>
</html>
"""
    (SIMPLE_DIR / "index.html").write_text(root_html, encoding="utf-8")

    (PUBLIC_DIR / "sources.json").write_text(
        json.dumps(sources_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Índice gerado com sucesso para {len(packages_found)} pacotes.")


if __name__ == "__main__":
    generate_index()
