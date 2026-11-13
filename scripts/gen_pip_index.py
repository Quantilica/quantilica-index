#!/usr/bin/env python3
"""Gera índice estático de pacotes Python PEP 503/658 a partir do GitHub Releases."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ORG_NAME = "Quantilica"
PUBLIC_DIR = Path("public")
# Registro de fetchers: cópia versionada da versão pública (sem dados de operação).
REGISTRY_FILE = Path("registry.json")
SIMPLE_DIR = PUBLIC_DIR / "simple"

# Mapeamento de repositórios conhecidos da organização.
# `bcb-sgs-sql` e `sidra-sql` estão depreciados (substituídos por `quantilica-sql`),
# mas continuam aqui: o índice é montado a partir das releases de cada repositório,
# e tirá-los da lista apagaria do índice as versões já publicadas.
FETCHERS = [
    "anac-fetcher",
    "anp-fetcher",
    "antt-fetcher",
    "b3-fetcher",
    "bcb-microdados-fetcher",
    "bcb-sgs-fetcher",
    "bcb-sgs-sql",
    "capes-fetcher",
    "comex-fetcher",
    "cvm-fetcher",
    "datasus-fetcher",
    "inep-fetcher",
    "infosiga-fetcher",
    "inmet-fetcher",
    "ipeadata-fetcher",
    "loterias-fetcher",
    "ons-fetcher",
    "pdet-fetcher",
    "pgfn-fetcher",
    "rfb-cnpj-fetcher",
    "rtn-fetcher",
    "ibge-sidra-fetcher",
    "sidra-fetcher",
    "sidra-sql",
    "sigtap-fetcher",
    "tesouro-direto-fetcher",
    "transparencia-sp-fetcher",
    "tse-fetcher",
    "quantilica-analytics",
    "quantilica-catalog",
    "quantilica-sql",
]

# Renome `sidra-fetcher` -> `ibge-sidra-fetcher` (13/11/2026), sem módulo de
# compatibilidade. Os dois nomes ficam no índice:
# - `sidra-fetcher` é congelado: só as wheels antigas (`sidra_fetcher-*`);
# - `ibge-sidra-fetcher` recebe as novas (`ibge_sidra_fetcher-*`).
# As releases moram no mesmo repositório. Enquanto o GitHub não o renomeia, ele
# se chama `sidra-fetcher`; depois, `sidra-fetcher` redireciona para o nome novo
# e devolve as mesmas releases, por isso o filtro pelo nome do arquivo (PEP 427)
# é o que separa os dois pacotes.
REPOS_DO_PACOTE: dict[str, list[str]] = {
    "ibge-sidra-fetcher": ["ibge-sidra-fetcher", "sidra-fetcher"],
}
PREFIXO_DE_ARQUIVO: dict[str, str] = {
    "ibge-sidra-fetcher": "ibge_sidra_fetcher-",
    "sidra-fetcher": "sidra_fetcher-",
}

# Apelidos do `sources.json` que não saem do nome do repositório. Um
# `quantilica install sidra` (ou `ibge`) de um cli antigo, que lê este arquivo,
# passa a instalar o pacote renomeado em vez de congelar na última wheel antiga;
# o fetcher novo declara os mesmos apelidos no registro, então o cli o descobre.
APELIDOS_DE_FONTE: dict[str, str] = {
    "sidra": "ibge-sidra-fetcher",
    "ibge": "ibge-sidra-fetcher",
}


def asset_do_pacote(pkg_name: str, asset_name: str) -> bool:
    """Diz se o arquivo pertence ao pacote (só filtra os pacotes renomeados)."""
    prefixo = PREFIXO_DE_ARQUIVO.get(pkg_name)
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


def generate_index():
    token = os.environ.get("GITHUB_TOKEN")
    SIMPLE_DIR.mkdir(parents=True, exist_ok=True)

    sources_map: dict[str, str] = {}
    packages_found: list[str] = []

    for repo in FETCHERS:
        pkg_name = repo.lower()
        releases: list[dict] = []
        for candidato in REPOS_DO_PACOTE.get(pkg_name, [repo]):
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
                if is_pkg and asset_do_pacote(pkg_name, name):
                    links.append(f'    <a href="{download_url}">{name}</a><br/>')

        # Pacote renomeado sem nenhum arquivo (ainda sem release com o nome
        # novo) não entra no índice: o cli trata o que o índice lista como
        # instalável.
        if pkg_name in PREFIXO_DE_ARQUIVO and not links:
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

    for apelido, repo in APELIDOS_DE_FONTE.items():
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
    publish_registry()
    print(f"Índice gerado com sucesso para {len(packages_found)} pacotes.")


def publish_registry() -> None:
    """Copia `registry.json` (registro de fetchers) para o site, se existir."""
    if not REGISTRY_FILE.is_file():
        print("registry.json ausente; o registro de fetchers não foi publicado.")
        return
    # Cópia inválida não derruba o índice de pacotes: avisa e não publica o registro.
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data.get("fetchers"), list):
            raise ValueError("campo 'fetchers' ausente")
    except (ValueError, AttributeError) as exc:
        print(f"::warning::registry.json inválido ({exc}); registro não publicado.")
        return
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "registry.json").write_text(
        REGISTRY_FILE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    print(f"Registro publicado com {len(data.get('fetchers', []))} fetchers.")


if __name__ == "__main__":
    generate_index()
