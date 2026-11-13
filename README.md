# `quantilica-index`

Índice estático de pacotes Python PEP 503/658 do ecossistema **Quantilica**.

Este repositório é acionado automaticamente a cada nova release publicada nos repositórios `*-fetcher`, `quantilica-analytics` e `quantilica-catalog`. O script `scripts/gen_pip_index.py` varre as releases da organização no GitHub e publica o índice estático no **GitHub Pages**:

- **URL Base PEP 503:** `https://index.quantilica.com/simple/`
- **Mapeamento de Fontes:** `https://index.quantilica.com/sources.json`
- **Registro de fetchers:** `https://index.quantilica.com/registry.json` (id, nome, apelidos, órgão, licença, frequência e domínio de cada coletor). É a cópia de `registry.json` deste repositório (versão pública do registro, sem dados de operação).

## Pacotes renomeados

`sidra-fetcher` virou `ibge-sidra-fetcher` (13/11/2026), sem módulo de compatibilidade. O índice serve os dois: `/simple/sidra-fetcher/` guarda só as wheels antigas (`sidra_fetcher-*`, congeladas) e `/simple/ibge-sidra-fetcher/` as novas (`ibge_sidra_fetcher-*`). As releases moram no mesmo repositório do GitHub; o gerador separa os pacotes pelo nome do arquivo. No `sources.json`, as chaves `sidra` e `ibge` apontam para `ibge-sidra-fetcher` (junto de `ibge-sidra`).
