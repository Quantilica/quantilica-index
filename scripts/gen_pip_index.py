#!/usr/bin/env python3
"""Gera índice estático de pacotes Python PEP 503 a partir do GitHub Releases.

PENDENTE (outro cartão): PEP 658 — publicar um `.metadata.json` ao lado de
cada link com a URL `.../<arquivo>.metadata.json`. Aqui só sai o índice de
links simples.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
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
    # Obrigatório de Python (specifiers PEP 440) dos metadados do pacote, quando
    # conhecido: hoje declarado no `registro.toml` (e aceito do registro
    # publicado, para quando o export passar a trazê-lo do pyproject). O índice
    # o põe em `data-requires-python` de cada link da distribuição atual.
    requires_python: str | None = None


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

    @property
    def requires_python_por_distribuicao(self) -> dict[str, str]:
        """`requires_python` por distribuição atual, quando conhecido.

        Vale só para a distribuição atual de cada id: as distribuições do
        `historico` ficam congeladas e as wheels antigas podem exigir outro
        Python. Primeira declaração vence (ids saem em ordem de `sorted`).
        """
        out: dict[str, str] = {}
        for f in self.fetchers:
            if f.requires_python:
                out.setdefault(f.distribution, f.requires_python)
        return out


def _nome_do_repo(repo: str) -> str:
    """`Quantilica/sidra-fetcher` ou a URL do GitHub -> `sidra-fetcher`."""
    return repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def _historico_de(fid: str, bruto: object) -> tuple[tuple[str, str, str], ...]:
    """`historico` do TOML como (distribuição, repositório, id).

    Entrada malformada (sem chave, tipo errado) é pulada com aviso: o índice de
    pacotes não cai por causa dela. `valida_registro.py` é quem a reprova.
    """
    if bruto is None:
        return ()
    if not isinstance(bruto, list):
        print(f"::warning::[{fid}].historico ignorado: esperava uma lista de tabelas")
        return ()
    out = []
    for i, h in enumerate(bruto):
        try:
            out.append((h["distribution"].lower(), _nome_do_repo(h["repo"]), h["id"]))
        except (KeyError, TypeError, AttributeError) as exc:
            print(f"::warning::[{fid}].historico[{i}] ignorado: {exc!r}")
    return tuple(out)


def _texto_opcional(fid: str, campo: str, bruto: object) -> str | None:
    """Um campo de texto opcional de uma seção, ou None com aviso se inválido."""
    if bruto is None:
        return None
    if isinstance(bruto, str) and bruto.strip():
        return bruto
    print(f"::warning::[{fid}].{campo} ignorado: esperava uma string não vazia")
    return None


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
        secao = declarado[fid] if isinstance(declarado[fid], dict) else {}
        pub = publicado.get(fid, {})
        dist = pub.get("distribution") or f"{fid}-fetcher"
        repo = _nome_do_repo(pub["repo"]) if pub.get("repo") else dist
        historico = _historico_de(fid, secao.get("historico"))
        requires_python = _texto_opcional(
            fid, "requires_python", secao.get("requires_python")
        )
        if requires_python is None:
            # Fallback: o registro publicado pode um dia trazer o que ele lê
            # do pyproject do fetcher (specifiers reais dos metadados).
            requires_python = _texto_opcional(
                fid, "requires_python", pub.get("requires_python")
            )
        fetchers.append(
            Fetcher(
                id=fid,
                distribution=dist.lower(),
                repo=repo,
                aliases=tuple(pub.get("aliases") or ()),
                historico=historico,
                requires_python=requires_python,
            )
        )
    return Registro(tuple(fetchers))


def asset_do_pacote(
    pkg_name: str, asset_name: str, prefixos: dict[str, str] | None = None
) -> bool:
    """Diz se o arquivo pertence ao pacote (só filtra os pacotes renomeados)."""
    prefixo = (prefixos or {}).get(pkg_name)
    return prefixo is None or asset_name.startswith(prefixo)


class ErroConsultaReleases(Exception):
    """Falha ao consultar as releases de um repositório na API do GitHub.

    O chamador deve abortar o build: um índice publicado sem os arquivos de um
    pacote seria pior que nenhum (o cli trataria o pacote como desatualizado).
    """


_LINK_PROXIMA = re.compile(r'<(?P<url>[^>]*)>;\s*rel=?"?next"?')


def _proxima_pagina(link: str | None) -> str | None:
    """A URL do `rel="next"` no cabeçalho `Link` da resposta, ou None."""
    if not link:
        return None
    for parte in link.split(","):
        m = _LINK_PROXIMA.search(parte.strip())
        if m:
            return m.group("url")
    return None


def fetch_releases(repo: str, token: str | None = None) -> list[dict]:
    """Todas as releases do repositório, seguindo a paginação da API.

    Pede 100 por página (`per_page=100`) e segue o cabeçalho `Link`
    (`rel="next"`) até a última.

    Raises:
        ErroConsultaReleases: resposta fora do 200, JSON inválido ou falha de
            rede — o índice não se monta com dados incompletos.
    """
    url = f"https://api.github.com/repos/{ORG_NAME}/{repo}/releases?per_page=100"
    headers = {"User-Agent": "quantilica-index-builder"}
    if token:
        headers["Authorization"] = f"token {token}"

    releases: list[dict] = []
    visitadas: set[str] = set()
    while url and url not in visitadas:
        visitadas.add(url)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                proxima = _proxima_pagina(resp.headers.get("Link"))
                corpo = resp.read()
            if status != 200:
                raise ErroConsultaReleases(f"{repo}: HTTP {status} em {url}")
            pagina = json.loads(corpo.decode("utf-8"))
        except ErroConsultaReleases:
            raise
        except Exception as exc:
            raise ErroConsultaReleases(
                f"{repo}: falha ao consultar {url}: {exc}"
            ) from exc
        if not isinstance(pagina, list):
            raise ErroConsultaReleases(f"{repo}: resposta inesperada da API em {url}")
        releases.extend(pagina)
        url = proxima
    return releases


def fragmento_sha256(digest: str | None) -> str:
    """O fragmento `#sha256=<hex>` do link PEP 503, ou vazio se não houver.

    A API das releases traz o campo `digest` como `<algoritmo>:<hex>` (hoje só
    `sha256`). Outro algoritmo, prefixo ausente ou hex que não tenha 64 dígitos
    não vira fragmento: pip compara o fragmento com o arquivo baixado, e um
    valor errado quebraria toda a instalação.
    """
    valor = (digest or "").strip()
    if valor.lower().startswith("sha256:"):
        valor = valor[len("sha256:") :]
    if re.fullmatch(r"[0-9a-fA-F]{64}", valor):
        return f"#sha256={valor.lower()}"
    return ""


def generate_index(registro: Registro | None = None) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    registro = registro or carrega_registro()
    repos_do_pacote = registro.repos_do_pacote
    prefixos = registro.prefixo_de_arquivo
    requires_python = registro.requires_python_por_distribuicao
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
        reqpy = requires_python.get(pkg_name)
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
                    sha = fragmento_sha256(asset.get("digest"))
                    attr = (
                        f' data-requires-python="{html.escape(reqpy)}"' if reqpy else ""
                    )
                    links.append(
                        f'    <a href="{download_url}{sha}"{attr}>{name}</a><br/>'
                    )

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
    try:
        generate_index()
    except ErroConsultaReleases as exc:
        print(f"::error::build abortado: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
