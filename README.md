# `quantilica-index`

Índice estático de pacotes Python PEP 503/658 do ecossistema **Quantilica**.

Este repositório é acionado automaticamente a cada nova release publicada nos repositórios `*-fetcher`, `quantilica-analytics` e `quantilica-catalog`. O script `scripts/gen_pip_index.py` varre as releases da organização no GitHub e publica o índice estático no **GitHub Pages**:

- **URL Base PEP 503:** `https://index.quantilica.com/simple/`
- **Mapeamento de Fontes:** `https://index.quantilica.com/sources.json`
- **Registro de fetchers:** `https://index.quantilica.com/registry.json` (id, nome, apelidos, órgão, licença, frequência e domínio de cada coletor). É a cópia de `registry.json` deste repositório, gerada no workspace com `python3 infra/registry_build.py --public registry.json`.
