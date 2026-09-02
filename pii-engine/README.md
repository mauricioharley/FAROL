# pii-engine

Motor de detecção de PII/dado sensível do FAROL. Recebe o conteúdo de um recurso (CSV, XLSX,
PDF, GeoJSON, ZIP etc.) e devolve um veredito - `liberar` / `alertar` / `bloquear` /
`nao_analisado` - sem nunca chamar o CKAN de volta e sem persistir nada. Quem interpreta e
age sobre o veredito é sempre o chamador: o `scanner` (auditoria em lote) ou o
`ckanext-farol-guard` (bloqueio preventivo no upload).

Três camadas de detecção, em ordem crescente de custo, cada uma só entrando em campo sobre
o que a anterior já sinalizou:

1. **Camada 1** - heurística de nome de coluna + regex de valor (CPF, CNPJ, e-mail, telefone,
   CEP). Roda sobre todo campo.
2. **Camada 2** - NER via Presidio + spaCy (`pt_core_news_lg`), mais reconhecedores
   customizados para categoria sensível (ex. termos de saúde). Roda sobre texto livre que a
   Camada 1 não resolveu.
3. **Camada 3** - classificador LLM local (Qwen3, via llama.cpp), só sobre trecho que a
   Camada 2 já sinalizou. Nunca decide `bloquear` sozinha - teto de confiança (0,89) garante
   que um achado só dela vira no máximo `alertar`, até o recall real medido contra dado
   real passar de 85% de forma consistente.

**Nunca sai texto original de PII do processo** - nem em log, nem em resposta de API. Achado
carrega campo, categoria, confiança, camada e uma justificativa curta e genérica (Camada 3);
o `hash_arquivo` (SHA-256) identifica o recurso sem guardar o conteúdo.

## Como subir

Parte do compose da raiz do repositório, nunca sozinho:

```bash
cp .env.example .env   # na raiz do repo, preencha antes
docker compose up -d pii-engine
```

Depende do serviço `llm` (Camada 3) e, opcionalmente, de um mount read-only do storage do
CKAN de produção (ex. `/mnt/ckan/storage/resources`), usado só quando o chamador manda
`caminho_local` em vez de `recurso_url` - uma otimização válida quando o `pii-engine` roda no
mesmo host que já tem esse volume montado, evitando repetir via HTTP um download que já está
em disco local. Sem esse mount, o motor funciona normalmente só com `recurso_url` (download
HTTP) - é o caminho padrão contra qualquer portal, local ou de terceiro.

Documentação interativa da API (gerada pelo FastAPI): `http://localhost:8000/docs`.

## Endpoints

- `POST /v1/scan` - `{"dataset_id", "recurso_url"}` ou `{"dataset_id", "caminho_local"}`.
- `POST /v1/scan-upload` - multipart (`dataset_id`, `arquivo`), para o caminho do plugin
  preventivo (upload ainda não tem URL nem foi salvo em disco nesse momento).
- `GET /health`.

Resposta dos dois primeiros:

```json
{
  "score_risco": 0,
  "achados": [{"campo": "...", "categoria": "...", "confianca": 0.0, "camada": 1, "justificativa": null}],
  "veredito": "liberar | alertar | bloquear | nao_analisado",
  "motivo_nao_analisado": "formato_nao_suportado | erro_download | cabecalho_csv_malformado | ... | null",
  "hash_arquivo": "sha256 em hex, ou null",
  "dataset_id": "..."
}
```

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `FAROL_LLM_URL` | `http://llm:8080` | endpoint OpenAI-compatible do serviço `llm` (Camada 3) |
| `FAROL_LLM_MODEL` | `qwen3-4b` | apelido do modelo, tem que bater com `--alias` do serviço `llm` |
| `FAROL_VERIFY_TLS` | `true` | verificação de certificado no download de `recurso_url` - só desligue globalmente se souber por quê |
| `FAROL_HOSTS_TLS_INSEGURO` | (vazio) | lista de hosts (separados por vírgula) com certificado autoassinado conhecido - exceção por host, nunca global; use para o CKAN de teste local, nunca para portal de terceiro real |
| `FAROL_CKAN_STORAGE_PATH` | `/mnt/ckan/storage/resources` | diretório base permitido para leitura direta de disco via `caminho_local`; precisa bater com o lado direito do mount no compose |

Esses são os nomes lidos pelo código Python dentro do container. Rodando via `docker compose`
da raiz do repositório (o caso normal), o `docker-compose.yml` traduz alguns nomes: defina
`LLM_MODEL` (não `FAROL_LLM_MODEL`) no `.env` da raiz para configurar o modelo - o compose faz
`FAROL_LLM_MODEL: ${LLM_MODEL:-qwen3-4b}`. Definir `FAROL_LLM_MODEL` direto nesse `.env` não
tem efeito nenhum. `FAROL_LLM_MODEL` só é o nome direto a usar se o `pii-engine` rodar isolado,
fora do compose raiz.

## Formatos suportados

CSV, XLSX, ODS, JSON, GeoJSON, YAML, XML, KML, TXT, DOCX, ODT, PDF (com fallback de OCR para
escaneado), ZIP/7Z/RAR (recursivo, com limite de profundidade e tamanho contra zip bomb),
KMZ, SHZ. Formato sem extrator registrado, ou compactado que estoura o limite, vira
`nao_analisado` com motivo específico - nunca um `liberar` silencioso. Lista completa e o
raciocínio de cada extrator: `app/core/extracao.py`.

## Testes

```bash
docker compose run --rm \
  -v $(pwd)/pii-engine/tests:/app/tests \
  -v $(pwd)/pii-engine/requirements-test.txt:/app/requirements-test.txt \
  --entrypoint sh pii-engine \
  -c "pip install --no-cache-dir -r requirements-test.txt -q && pytest -q tests"
```

`tests/` não entra na imagem de produção (só `app/` é copiado no `Dockerfile`) - o comando
acima monta o diretório de teste por cima do container na hora, sem alterar a imagem.
Cobre a Camada 0 (extração - inclusive casos reais de robustez: cabeçalho malformado,
extensão que não bate com o conteúdo, limite de profundidade de zip propagando de dentro de
zip aninhado), a Camada 1 (heurística de coluna) e o agregador (`motor.py`, sobretudo o teto
de confiança da Camada 3). Camada 2 (NER) e Camada 3 (LLM) não têm teste automatizado direto
- dependem de modelo/serviço externo (spaCy, `llm`) e são melhor validadas por um conjunto
rotulado de avaliação do que por teste unitário - ver `eval/` e `scripts/avaliar_camada3.py`.

## Limitações conhecidas

- Recall da Camada 3 medido contra dado real (30 itens adversariais de uma varredura ampla
  no catálogo): 75% nas categorias sensíveis do Art. 5º, II da LGPD (meta de projeto era
  85%) - por isso o teto de confiança continua ativo. Uma segunda rodada de few-shot,
  ajustada contra um conjunto sintético adversarial dedicado (`eval/`, nunca usado para gerar
  o few-shot original), mediu recall de 88,9% num conjunto de validação nunca inspecionado
  durante o ajuste - acima da meta, mas ainda não é o mesmo tipo de evidência que o número de
  75%, que veio de dado real de produção. O teto de confiança segue ativo até uma nova medição
  contra dado real confirmar o ganho.
- Camada 2 (NER) tem falso positivo recorrente confundindo nome de instituição/curso/região
  com nome de pessoa, em dado institucional (ex. `NM_INSTITUICAO_ENSINO`) - registrado como
  limitação conhecida, candidato a refinamento pela Camada 3 no futuro.
- SHP avulso (sem os arquivos irmãos `.dbf`/`.shx`) só permite ler geometria, não o dado que
  interessa para PII - vira `nao_analisado`/`shapefile_incompleto`; o caminho correto é o
  pacote completo via `.shz`.
