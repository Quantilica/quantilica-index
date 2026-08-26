# `quantilica-index`

Índice estático de pacotes Python PEP 503/658 do ecossistema **Quantilica**.

Este repositório é acionado automaticamente a cada nova release publicada nos repositórios `*-fetcher`, `quantilica-analytics` e `quantilica-catalog`. O script `scripts/gen_pip_index.py` varre as releases da organização no GitHub e publica o índice estático no **GitHub Pages**:

- **URL Base PEP 503:** `https://index.quantilica.com/simple/`
- **Mapeamento de Fontes:** `https://index.quantilica.com/sources.json`
