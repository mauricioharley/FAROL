# Referência de API

O Swagger/OpenAPI gerado automaticamente pelo FastAPI (`/docs` em cada serviço) cobre o schema
exato de cada campo - esta página narra o **papel** de cada endpoint e como eles se encaixam, o
que o Swagger sozinho não conta.

## `pii-engine` - o motor

Serviço sem estado. Nunca chama o CKAN de volta, nunca persiste nada - recebe conteúdo, devolve
um veredito.

### `POST /v1/scan`

Para um recurso já acessível por URL ou já em disco.

```json
{
  "dataset_id": "meu-dataset",
  "recurso_url": "https://portal.example.org/dataset/x/resource/y/download/arquivo.csv",
  "nome_arquivo": "arquivo.csv"
}
```

`caminho_local` substitui `recurso_url` quando o chamador tem acesso a um mount local
read-only do próprio CKAN (otimização que só faz sentido pro seu próprio portal, quando
`scanner` e CKAN compartilham o mesmo host - nunca disponível pra catálogo de terceiro, que
sempre baixa via `recurso_url`). Não exposto na tela `/scan` do painel hoje - só via chamada
direta ao `pii-engine`.

### `POST /v1/scan-upload`

Para bytes que ainda não têm URL pública - o caso do plugin preventivo (ver
[Plugin preventivo](../guia-do-administrador/plugin-ckan.md)): um upload em andamento não foi
salvo em disco nem publicado ainda. `multipart/form-data`, campos `dataset_id` e `arquivo`.

### Resposta, os dois casos

```json
{
  "score_risco": 0,
  "achados": [
    {"campo": "cpf", "categoria": "identificador", "confianca": 0.95, "camada": 1}
  ],
  "veredito": "bloquear",
  "motivo_nao_analisado": null,
  "hash_arquivo": "sha256..."
}
```

`achados` nunca carrega o valor bruto encontrado - só `campo`/`categoria`/`confiança`/`camada`
(mais `justificativa`, opcional, quando a Camada 3 roda).

**Cálculo do veredito** - pela maior confiança entre todos os achados das três camadas:

| Confiança máxima | Veredito |
|---|---|
| ≥ 0,9 | `bloquear` |
| ≥ 0,6 e < 0,9 | `alertar` |
| < 0,6 | `liberar` |
| (extração abortada, nenhuma camada rodou) | `nao_analisado` |

A Camada 3 tem um teto de confiança embutido (0,89) - mesmo um achado de altíssima confiança
vindo só dela nunca sozinho decide `bloquear`, só reforça `alertar`. Ver
[índice - arquitetura](../index.md#arquitetura-em-uma-pagina) para o porquê.

`motivo_nao_analisado` só é preenchido quando `veredito = "nao_analisado"` - valores observados na
prática: `formato_nao_suportado`, `cabecalho_csv_malformado`, `cabecalho_ods_malformado`,
`arquivo_corrompido_ou_extensao_incorreta`, `erro_download: ...`, `profundidade_maxima_excedida`,
`tamanho_maximo_excedido`, `shapefile_incompleto`.

## `painel` - ingestão e consulta

O painel técnico é também quem grava achados vindos de qualquer chamador que não seja o
`scanner` (que grava direto no Postgres, por rodar como job em lote no mesmo host).

### `POST /v1/achados`

Ingestão máquina-a-máquina - usada pelo [plugin preventivo](../guia-do-administrador/plugin-ckan.md)
(`ckanext-farol-guard`) para registrar todo achado, inclusive `liberar`, mantendo a trilha de
auditoria completa mesmo quando o upload não é bloqueado. Autenticação por
header `X-Farol-Token`, valor igual a `FAROL_INGEST_TOKEN` - **deliberadamente separado** do login
humano (`FAROL_TECNICO_USER`/`PASSWORD`) do painel: dois públicos, dois níveis de confiança, sem
misturar a senha que autentica um humano no navegador com a credencial de um serviço.

```json
{
  "org": "minha-org",
  "dataset_id": "meu-dataset",
  "recurso": "id-do-recurso",
  "recurso_nome": "arquivo.csv",
  "executado_por": "ckanext-farol-guard",
  "ambiente": "producao",
  "resultado": { "...": "mesmo formato devolvido por /v1/scan(-upload) acima" }
}
```

### `GET /health`

Sem autenticação - checagem de vivacidade simples, usada por orquestradores/monitoramento.

As rotas que servem o HTML/dado do painel (`GET /`, `POST /revisar/{achado_id}`, `GET /scan` e
`POST /api/scan/*`, `GET /api/gerencial/*`) exigem login por sessão (nunca HTTP Basic - dois
painéis, duas credenciais desde 2026-08-22) e estão documentadas em
[Guia do usuário - painel técnico](../guia-do-usuario/painel-tecnico.md) e
[Guia do usuário - painel gerencial](../guia-do-usuario/painel-gerencial.md), não aqui - são
interface, não API de integração.
