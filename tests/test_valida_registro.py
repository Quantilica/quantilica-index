"""`scripts/valida_registro.py` e a tolerância do gerador a `historico` malformado."""

from __future__ import annotations

import tomllib
from pathlib import Path

import gen_pip_index as gen
import valida_registro as vr

RAIZ = Path(__file__).resolve().parents[1]


def erros(texto: str) -> list[str]:
    return vr.erros_estruturais(tomllib.loads(texto))


def test_registro_toml_do_repositorio_e_valido():
    dados = tomllib.loads((RAIZ / "registro.toml").read_text(encoding="utf-8"))
    assert vr.erros_estruturais(dados) == []
    assert vr.valida(RAIZ / "registro.toml") == []


def test_historico_sem_chave_e_reprovado():
    texto = (
        '[a]\ndocs_pasta = "x"\n[[a.historico]]\ndistribution = "b-fetcher"\n'
        'repo = "Q/b-fetcher"\ndata = 2026-11-13\n'
    )
    assert erros(texto) == ["[a].historico[0] sem id"]


def test_campo_desconhecido_tipo_errado_e_sem_docs_pasta():
    texto = '[a]\nvitrine = "sim"\nlixo = 1\n'
    achados = erros(texto)
    assert "[a] campo desconhecido 'lixo'" in achados
    assert "[a] vitrine deve ser true ou false" in achados
    assert "[a] docs_pasta é obrigatório (texto)" in achados


def test_toml_invalido_e_arquivo_ausente(tmp_path):
    ruim = tmp_path / "r.toml"
    ruim.write_text("[a\n", encoding="utf-8")
    assert vr.valida(ruim)
    assert vr.valida(tmp_path / "nao-existe.toml")
    assert vr.main([str(ruim)]) == 1


def test_gerador_pula_historico_malformado_sem_cair(tmp_path, capsys):
    p = tmp_path / "r.toml"
    p.write_text(
        '[a]\ndocs_pasta = "x"\n[[a.historico]]\ndistribution = "b-fetcher"\n'
        'repo = "Q/b-fetcher"\ndata = 2026-11-13\n',
        encoding="utf-8",
    )
    registro = gen.carrega_registro(p, tmp_path / "sem.json")
    assert registro.fetchers[0].historico == ()
    assert "historico[0] ignorado" in capsys.readouterr().out
    assert registro.pacotes[0] == "a-fetcher"
