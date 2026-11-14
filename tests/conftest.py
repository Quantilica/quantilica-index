"""Põe `scripts/` e `tests/` no caminho de importação (os scripts não são um pacote)."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
for pasta in (RAIZ / "scripts", RAIZ / "tests"):
    if str(pasta) not in sys.path:
        sys.path.insert(0, str(pasta))
