# `quantilica-index`

Índice estático de pacotes Python PEP 503/658 do ecossistema **Quantilica**.

Este repositório é acionado automaticamente a cada nova release publicada nos repositórios `*-fetcher`, `quantilica-analytics` e `quantilica-catalog`, todo dia às 04:00 UTC e a cada mudança em `registro.toml`. O script `scripts/gen_pip_index.py` varre as releases da organização no GitHub e publica o índice estático no **GitHub Pages**; `scripts/build_registry.py` monta o registro de fetchers:

- **URL Base PEP 503:** `https://index.quantilica.com/simple/`
- **Mapeamento de Fontes:** `https://index.quantilica.com/sources.json`
- **Registro de fetchers:** `https://index.quantilica.com/registry.json` (versão 2), com o `sha256` do conteúdo em `https://index.quantilica.com/registry.json.sha256`. Reúne, por fetcher, três camadas: os fatos da fonte (id, nome, apelidos, órgão, licença, cadência, domínio), a identidade do pacote (distribuição, módulo, repositório, versão), lida do próprio pacote instalado, e os fatos do ecossistema declarados em `registro.toml` (seção do docs, vitrine, CI de integração, JSON leve, mascote, sonda de saúde e `historico` de renomes). Não é versionado aqui: o CI instala do índice a última versão de cada fetcher do `registro.toml` e roda `quantilica registry export --strict --json --ecossistema registro.toml`. Falta de id, aviso do export ou `sha256` que não bate faz o build falhar; o índice PEP 503 sai do mesmo jeito e o `registry.json` anterior continua no ar.

## `registro.toml`

Uma seção por fetcher, pelo `id` do `FetcherInfo` (não pela distribuição). Acrescentar um fetcher é acrescentar a seção; renomear é manter a seção do id novo e acrescentar a entrada em `historico` (distribuição, repositório, id e data anteriores). `gen_pip_index.py` deriva daí a lista de pacotes do índice, os repositórios a consultar, o prefixo dos arquivos de cada nome e os apelidos do `sources.json`; só os pacotes que não são fetcher (`OUTROS_PACOTES`) ficam escritos no script.

Para montar o registro sem instalar nada, com um python que já tem os fetchers e o cli: `python scripts/build_registry.py --python .venv/bin/python [--extra-path <src do cli>] [--extra-path <src do core>]`. Os testes (`pytest tests`) não instalam pacotes; com `REGISTRO_PYTHON` definido, um deles roda o export de verdade.

## Pacotes renomeados

`sidra-fetcher` virou `ibge-sidra-fetcher` (13/11/2026), sem módulo de compatibilidade. O índice serve os dois: `/simple/sidra-fetcher/` guarda só as wheels antigas (`sidra_fetcher-*`, congeladas) e `/simple/ibge-sidra-fetcher/` as novas (`ibge_sidra_fetcher-*`). As releases moram no mesmo repositório do GitHub; o gerador separa os pacotes pelo nome do arquivo. No `sources.json`, as chaves `sidra` e `ibge` apontam para `ibge-sidra-fetcher` (junto de `ibge-sidra`).
