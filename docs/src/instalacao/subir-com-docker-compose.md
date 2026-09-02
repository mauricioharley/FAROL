# Subir com Docker Compose

O FAROL é um `docker-compose.yml` único na raiz do repositório, com nove serviços:

| Serviço | Papel | Porta publicada |
|---|---|---|
| `farol-db` | Postgres - achados e execuções | interna (`5432`, não publicada) |
| `model-downloader` | Baixa o modelo GGUF da Camada 3 uma vez, sai (`service_completed_successfully`) | - |
| `llm` | `llama.cpp` servindo o modelo baixado - Camada 3 | interna (`8080`, não publicada) |
| `pii-engine` | O motor - único serviço que expõe `/v1/scan` | interna (`8000`, não publicada - só alcançável de dentro da rede do compose, exige header `X-Farol-Token`) |
| `painel` | Painel técnico (FastAPI + Jinja2) + API do gerencial, autenticado | interna (`8080`, não publicada - só alcançável via `painel-nginx`) |
| `painel-nginx` | Terminador TLS na frente de `painel` e `painel-gerencial` (certificado autoassinado gerado no start) | `8080` (HTTPS) |
| `painel-gerencial` | Painel gerencial (React/Vite, estático, servido sob `/gerencial`) | interna (`8080`, não publicada) |
| `scanner` | Auditoria em lote - serviço HTTP permanente desde 2026-08-22, disparado pela tela `/scan` do painel (nunca por linha de comando) | interna (`8000`, não publicada - só o `painel` fala com ele) |

## 1. Configurar o `.env`

Crie um `.env` na raiz do repositório com, no mínimo:

```dotenv
FAROL_DB_NAME=farol
FAROL_DB_USER=farol
FAROL_DB_PASSWORD=troque-esta-senha
FAROL_DB_DSN=postgresql://farol:troque-esta-senha@farol-db:5432/farol

FAROL_TECNICO_USER=troque-este-usuario
FAROL_TECNICO_PASSWORD=troque-esta-senha
FAROL_GERENCIAL_USER=troque-este-usuario-tambem
FAROL_GERENCIAL_PASSWORD=troque-esta-senha-tambem
FAROL_SESSION_SECRET=gere-com-openssl-rand--hex-32
FAROL_INGEST_TOKEN=um-token-longo-aleatorio

# Opcionais: sem eles, o link "ver recurso original" simplesmente não aparece no painel
FAROL_PORTAL_PRODUCAO=https://seu-ckan-de-producao.example.org
FAROL_PORTAL_SINTETICO=https://seu-ckan-de-teste.example.org

# Opcionais, Camada 3 (têm default embutido no compose se omitidos)
MODEL_REPO=Qwen/Qwen3-4B-GGUF
MODEL_FILE=Qwen3-4B-Q4_K_M.gguf
LLM_MODEL=qwen3-4b
LLAMA_THREADS=4
```

Detalhe de cada variável em [Variáveis de ambiente](variaveis-de-ambiente.md).

!!! warning "Nunca versione o `.env`"
    Ele carrega credenciais reais (senhas dos dois painéis, token de ingestão, segredo de
    sessão). Confirme que está no `.gitignore` antes do primeiro commit do repositório.

## 2. Build e subida

```bash
docker compose build
docker compose up -d
docker compose ps    # confirma os nove serviços de pé (model-downloader aparece "completo", não "rodando" - é esperado)
```

O `model-downloader` baixa o modelo da Camada 3 (alguns GB, só na primeira subida) e sai - isso é
esperado, não é um serviço que fica rodando. O `llm` só fica `healthy` depois que o download
termina (`depends_on: condition: service_completed_successfully`).

## 3. Confirmar que está de pé

```bash
curl -k https://localhost:8080/health            # painel, atrás do painel-nginx (-k: certificado autoassinado em teste)
```

`GET /health` não exige login - é o único endpoint do painel sem sessão. O FAROL nunca usou
HTTP Basic (nem antes, nem agora) - login é sempre por sessão de cookie assinado, via
formulário (`/login` para o painel técnico, `/login-gerencial` para o gerencial - credenciais
separadas desde 2026-08-22).

O Swagger do `pii-engine` (`/docs`) não é mais alcançável direto do host - o serviço usa
`expose` em vez de `ports` no compose, só alcançável de dentro da rede interna (e os
endpoints de fato, `/v1/scan` e `/v1/scan-upload`, ainda exigem o header `X-Farol-Token`).
Para conferir de dentro da rede, um exemplo é rodar de outro container do mesmo compose, ex.
`docker compose exec painel curl http://pii-engine:8000/docs`.

## 4. Rodar uma auditoria de teste

Pelo navegador, em `https://<host>:8080/scan` - ver [Rodar o scanner](../guia-do-administrador/rodar-o-scanner.md).
Nenhuma linha de comando é necessária: o `scanner` é um serviço permanente desde 2026-08-22,
disparado/cancelado/acompanhado pela tela, nunca por `docker compose run`.

## Volume de dados de produção (opcional, avançado)

O serviço `pii-engine` já vem com um exemplo de mount read-only comentado no
`docker-compose.yml` (`/mnt/ckan/storage/resources`) - só faz sentido se o `scanner` rodar no
mesmo host que já tem esse volume montado, como otimização para não baixar via HTTP recursos que
já estão em disco local. Não é um requisito: sem esse mount, o scanner baixa tudo via
`resource["url"]` normalmente. O caminho é configurável via `FAROL_CKAN_STORAGE_PATH` (padrão
`/mnt/ckan/storage/resources`), caso o host use outro layout de diretório.
