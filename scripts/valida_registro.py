#!/usr/bin/env python3
"""Valida o `registro.toml`: estrutura (stdlib) e, se houver, o core.

A validação estrutural sempre roda: ids, seções, campos conhecidos, tipos e
`historico` com `distribution`, `repo`, `id` e `data`. Se o `quantilica-core`
instalado já traz `carrega_registro_ecossistema` (registro v2), a validação
completa dele (vocabulário de `docs_pasta`, URLs, datas) roda também; sem ele,
avisa e segue só com a estrutural.

    python scripts/valida_registro.py [registro.toml]

Sai com 1 se o arquivo for inválido.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BOOLS = ("vitrine", "ci_integracao", "json_leve")
_TEXTOS = ("docs_pasta", "mascote", "health_url")
_CAMPOS = {*_BOOLS, *_TEXTOS, "historico"}
_RENOME = ("distribution", "repo", "id", "data")


def erros_estruturais(dados: dict) -> list[str]:
    """Problemas de forma do `registro.toml` já lido (lista vazia se está ok)."""
    erros: list[str] = []
    if not dados:
        return ["nenhuma seção de fetcher"]
    for fid, secao in dados.items():
        if not _ID.match(fid):
            erros.append(f"id inválido {fid!r}")
        if not isinstance(secao, dict):
            erros.append(f"[{fid}] deve ser uma seção")
            continue
        for extra in sorted(set(secao) - _CAMPOS):
            erros.append(f"[{fid}] campo desconhecido {extra!r}")
        if not isinstance(secao.get("docs_pasta"), str):
            erros.append(f"[{fid}] docs_pasta é obrigatório (texto)")
        for campo in _BOOLS:
            if campo in secao and not isinstance(secao[campo], bool):
                erros.append(f"[{fid}] {campo} deve ser true ou false")
        for campo in ("mascote", "health_url"):
            if campo in secao and not isinstance(secao[campo], str):
                erros.append(f"[{fid}] {campo} deve ser texto")
        hist = secao.get("historico", [])
        if not isinstance(hist, list):
            erros.append(f"[{fid}] historico deve ser uma lista de tabelas")
            continue
        for i, h in enumerate(hist):
            if not isinstance(h, dict):
                erros.append(f"[{fid}].historico[{i}] deve ser uma tabela")
                continue
            for campo in _RENOME:
                if campo not in h:
                    erros.append(f"[{fid}].historico[{i}] sem {campo}")
            for extra in sorted(set(h) - set(_RENOME)):
                erros.append(f"[{fid}].historico[{i}] campo desconhecido {extra!r}")
    return erros


def valida(path: Path) -> list[str]:
    """Todos os problemas do arquivo: estruturais e, com o core v2, os dele."""
    try:
        dados = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"{path}: {exc}"]
    erros = erros_estruturais(dados)
    if erros:
        return erros
    try:
        from quantilica.core import registry as core
    except ImportError:
        core = None
    if core is None or not hasattr(core, "carrega_registro_ecossistema"):
        print(
            "::warning::quantilica-core sem o registro v2 (carrega_registro_"
            "ecossistema); só a validação estrutural do registro.toml rodou.",
            file=sys.stderr,
        )
        return []
    try:
        core.carrega_registro_ecossistema(path)
    except core.RegistryError as exc:
        return [str(exc)]
    return []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else RAIZ / "registro.toml"
    erros = valida(path)
    for erro in erros:
        print(f"::error::registro.toml: {erro}", file=sys.stderr)
    if not erros:
        print(f"{path.name} válido.")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
