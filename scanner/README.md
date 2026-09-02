# scanner

Auditoria em lote do FAROL: varre um portal CKAN via API (`organization_list` ->
`organization_show` -> `package_show`), chama o `pii-engine` por recurso, grava achado no
Postgres.

Diferente do `ckanext-farol-guard` (que age antes de um recurso ser publicado), o scanner
**nunca marca nada como privado sozinho** - só registra achado para revisão humana. A
credencial que ele usa para ler (listar metadados, baixar recurso) não precisa nem deveria
ter permissão de escrita sobre dataset de outra organização.

## Serviço HTTP, não linha de comando

Desde 2026-08-22 o scanner é um serviço permanente (`main.py`, FastAPI) - decisão explícita
do Mauricio de não exigir interação por CLI, nem de administrador técnico. Disparar, cancelar
e acompanhar um scan acontece pelo **painel técnico** (`/scan`), que fala com este serviço
internamente. O serviço nunca é exposto direto pro host - só o `painel` fala com ele.

### Endpoints

| Rota | Método | Descrição |
|---|---|---|
| `/health` | GET | liveness |
| `/organizacoes` | POST | proxy fino do `organization_list` do CKAN alvo (corpo com `base_url`, `api_key?`, `verify?`) - popula o seletor de organização antes de disparar um scan |
| `/iniciar` | POST | dispara um scan (ver corpo abaixo); devolve `{execucao_id, total_recursos}` de imediato - a parte lenta roda numa thread |
| `/cancelar/{execucao_id}` | POST | pede pra parar entre um recurso e outro (nunca no meio de uma chamada já em andamento ao `pii-engine`) |

Corpo de `POST /iniciar`:

```json
{
  "base_url": "https://meu-ckan.example.gov.br",
  "engine_url": "http://pii-engine:8000",
  "executado_por": "usuario_da_sessao",
  "ambiente": "sintetico",
  "orgs": ["org1", "org2"],
  "formatos": ["csv", "xlsx"],
  "incremental": false,
  "usar_disco": false,
  "api_key": null,
  "verify": true
}
```

`orgs`/`formatos` nulos ou vazios incluem tudo (nenhum filtro). `incremental: true` inclui só
recurso novo ou com metadado de modificação diferente do que já foi visto numa execução
anterior contra o mesmo CKAN (tabela `recursos_conhecidos`, comparando o `metadata_modified`/
`last_modified` que o próprio CKAN já devolve, sem baixar nada a mais pra descobrir isso).

### Por que o progresso não tem endpoint próprio aqui

`execucoes` (Postgres) já é atualizada recurso a recurso pela thread do scan - `painel` lê
essa tabela direto (`GET /api/scan/execucoes`), sem precisar de um segundo lugar de verdade
sobre "quanto já foi processado". Achado também é gravado recurso a recurso, não em lote no
final - um scan cancelado no meio deixa tudo que já processou visível no painel.

## Reprocessando o catálogo (modo incremental)

Sem `incremental`, um novo scan contra o mesmo CKAN reprocessa tudo de novo, do zero. Com
`incremental: true`, só entra recurso novo (nunca visto) ou com data de modificação diferente
da última vez - pensado pra rodar de novo contra um catálogo que já foi auditado antes, sem
custo de reprocessar o que não mudou. Recurso sem data de modificação nenhuma vinda do CKAN é
sempre tratado como mudado (sem sinal confiável, mais seguro reprocessar do que arriscar
pular um achado real).

## Filtro por organização e por formato

`orgs` funciona há mais tempo (filtra antes de qualquer chamada de `package_show`, pra não
gastar requisição em organização fora do escopo). `formatos` filtra pela extensão da URL do
recurso (`.csv`, `.xlsx` etc.) - um recurso sem extensão reconhecível é excluído quando o
filtro está ativo (sem sinal confiável de formato, mais seguro deixar de fora de um escopo
explícito do que incluir às cegas).

## Revisar achado por linha de comando

Ainda existe como alternativa opcional ao formulário do painel (nunca foi obrigatório - o
painel sempre teve `POST /revisar/{achado_id}`):

```bash
docker compose run --rm scanner python revisar.py <id> confirmado_positivo <seu-nome>
docker compose run --rm scanner python revisar.py <id> falso_positivo <seu-nome>
```

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `FAROL_DB_DSN` | Sim | string de conexão Postgres (mesmo banco que o `painel` lê) |

## Testes

```bash
docker compose run --rm -e PYTHONPATH=/app \
  -v $(pwd)/scanner/tests:/app/tests \
  -v $(pwd)/scanner/requirements-test.txt:/app/requirements-test.txt \
  --entrypoint sh scanner \
  -c "pip install --no-cache-dir -r requirements-test.txt -q && pytest -q tests"
```

Cobre `coletor.py` (montagem da lista de recursos, filtro por organização, filtro por
formato, fórmula de sharding do disco) com a rede sempre mockada; `persistencia.py`
(`recurso_mudou`/`marcar_recurso_conhecido`/cancelamento) contra um Postgres descartável real
(mesmo padrão que `painel/tests` já usa); `run.py` (orquestração, cancelamento no meio do
loop, filtro incremental) com rede mockada e persistência real; `main.py` (contrato HTTP dos
três endpoints) com `preparar_execucao`/`rodar_execucao`/`solicitar_cancelamento` mockados.

## Nunca grava o valor bruto

`persistencia.py` só grava org, dataset, recurso, campo, categoria, confiança, camada,
justificativa (frase curta e genérica), veredito, hash SHA-256 do arquivo e a trilha de
quem/quando/onde rodou.
