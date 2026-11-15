# `quantilica-index`

Índice estático de pacotes Python PEP 503 do ecossistema **Quantilica**.

Este repositório é acionado automaticamente a cada nova release publicada nos repositórios `*-fetcher`, `quantilica-analytics` e `quantilica-catalog`, todo dia às 04:00 UTC e a cada mudança em `registro.toml`. O script `scripts/gen_pip_index.py` varre as releases da organização no GitHub e publica o índice estático no **GitHub Pages**; `scripts/build_registry.py` monta o registro de fetchers:

- **URL Base PEP 503:** `https://index.quantilica.com/simple/`
- **Mapeamento de Fontes:** `https://index.quantilica.com/sources.json`
- **Registro de fetchers:** `https://index.quantilica.com/registry.json` (versão 2), com o `sha256` do conteúdo em `https://index.quantilica.com/registry.json.sha256`. Reúne, por fetcher, três camadas: os fatos da fonte (id, nome, apelidos, órgão, licença, cadência, domínio), a identidade do pacote (distribuição, módulo, repositório, versão), lida do próprio pacote instalado, e os fatos do ecossistema declarados em `registro.toml` (seção do docs, vitrine, CI de integração, JSON leve, mascote, sonda de saúde e `historico` de renomes). O arquivo `registry.json.sha256` traz o mesmo hash do campo `sha256` do documento: o SHA-256 de `{version, fetchers}` em JSON canônico (chaves ordenadas, sem espaços, UTF-8), não o dos bytes do arquivo. Por isso `sha256sum -c` não funciona com ele; quem consome recalcula o hash do conteúdo e compara. Não é versionado aqui: o CI instala do índice a última versão de cada fetcher do `registro.toml` e roda `quantilica registry export --strict --json --ecossistema registro.toml`. Falta de id, aviso do export ou `sha256` que não bate faz o build falhar; o índice PEP 503 sai do mesmo jeito e o `registry.json` anterior continua no ar.

## `registro.toml`

Uma seção por fetcher, pelo `id` do `FetcherInfo` (não pela distribuição). Acrescentar um fetcher é acrescentar a seção; renomear é manter a seção do id novo e acrescentar a entrada em `historico` (distribuição, repositório, id e data anteriores). `gen_pip_index.py` deriva daí a lista de pacotes do índice, os repositórios a consultar, o prefixo dos arquivos de cada nome e os apelidos do `sources.json`; só os pacotes que não são fetcher (`OUTROS_PACOTES`) ficam escritos no script.

Opcionalmente, a seção pode declarar `requires_python = ">=3.12"` (specifiers PEP 440): o gerador o põe escapado em `data-requires-python` de cada link da distribuição atual do id (as distribuições do `historico` não o recebem). O gerador consulta a API de releases com `per_page=100` e segue o cabeçalho `Link` (`rel="next"`); quando o asset traz o campo `digest` como `sha256:<hex>`, o link ganha o fragmento `#sha256=<hex>`. Falha ao consultar as releases de um repositório (rede, HTTP fora do 200, JSON inválido) aborta o build com erro — o índice sai incompleto nunca. PEP 658 (`.metadata.json` ao lado de cada link) fica pendente.

O workflow tem três jobs: `indice` (gera o PEP 503, só leitura), `registro` (instala os fetchers e roda o export, só leitura) e `deploy` (única etapa com escrita, que só baixa artefatos). O registro lê do índice recém-gerado, então uma release nova entra na mesma execução. O `gen_pip_index.py` usa o registro anterior (o do `gh-pages`) para a distribuição e os apelidos atuais; por isso um apelido novo de fetcher renomeado chega ao `sources.json` com um ciclo de atraso (a execução seguinte, no máximo um dia).

Para montar o registro sem instalar nada, com um python que já tem os fetchers e o cli: `python scripts/build_registry.py --python .venv/bin/python [--extra-path <src do cli>] [--extra-path <src do core>]`. Os testes (`pytest tests`) não instalam pacotes; com `REGISTRO_PYTHON` definido, um deles roda o export de verdade.

## Pacotes renomeados

`sidra-fetcher` virou `ibge-sidra-fetcher` (13/11/2026), sem módulo de compatibilidade. O índice serve os dois: `/simple/sidra-fetcher/` guarda só as wheels antigas (`sidra_fetcher-*`, congeladas) e `/simple/ibge-sidra-fetcher/` as novas (`ibge_sidra_fetcher-*`). As releases moram no mesmo repositório do GitHub; o gerador separa os pacotes pelo nome do arquivo. No `sources.json`, as chaves `sidra` e `ibge` apontam para `ibge-sidra-fetcher` (junto de `ibge-sidra`).
