#!/usr/bin/env python3
"""Gera índice estático de pacotes Python PEP 503/658 a partir do GitHub Releases."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ORG_NAME = "Quantilica"
PUBLIC_DIR = Path("public")
SIMPLE_DIR = PUBLIC_DIR / "simple"

# Mapeamento de repositórios conhecidos da organização
FETCHERS = [
    "anac-fetcher",
    "anp-fetcher",
    "bcb-sgs-fetcher",
    "comex-fetcher",
    "datasus-fetcher",
    "inep-fetcher",
    "inmet-fetcher",
    "pdet-fetcher",
    "rtn-fetcher",
    "sidra-fetcher",
    "tesouro-direto-fetcher",
    "quantilica-analytics",
    "quantilica-catalog",
]


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
        releases = fetch_releases(repo, token)
        if not releases:
            continue

        pkg_name = repo.lower()
        packages_found.append(pkg_name)

        short_name = pkg_name.replace("-fetcher", "")
        sources_map[short_name] = repo

        pkg_dir = SIMPLE_DIR / pkg_name
        pkg_dir.mkdir(parents=True, exist_ok=True)

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
                if is_pkg:
                    links.append(f'    <a href="{download_url}">{name}</a><br/>')

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
