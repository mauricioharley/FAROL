# Variáveis de ambiente

## Do FAROL propriamente dito

Consumidas pelos serviços `painel`, `pii-engine` e `scanner` (`docker-compose.yml`):

| Variável | Serviço | Obrigatória | Descrição |
|---|---|---|---|
| `FAROL_DB_NAME` / `FAROL_DB_USER` / `FAROL_DB_PASSWORD` | `farol-db` | Sim | Credencial que o próprio Postgres do compose usa para se inicializar |
| `FAROL_DB_DSN` | `painel`, `scanner` | Sim | DSN do Postgres, formato `postgresql://usuario:senha@host:porta/banco` - precisa bater com os três valores acima |
| `FAROL_TECNICO_USER` / `FAROL_TECNICO_PASSWORD` | `painel` | Sim | Credencial de login do **painel técnico** (`/login`) |
| `FAROL_GERENCIAL_USER` / `FAROL_GERENCIAL_PASSWORD` | `painel` | Sim | Credencial **separada** do **painel gerencial** (`/login-gerencial`, desde 2026-08-22) - sessão independente da do técnico, uma nunca abre a rota da outra |
| `FAROL_SESSION_SECRET` | `painel` | Sim | Assina o cookie de sessão de login (dos dois painéis) - sem ela o serviço nem sobe |
| `FAROL_INGEST_TOKEN` | `painel` | Sim, para o endpoint `POST /v1/achados` | Token estático para autenticação máquina-a-máquina (ver [Referência de API](../referencia-api/pii-engine.md)) - **separado** do login humano de propósito |
| `FAROL_PORTAL_PRODUCAO` | `painel` | Não | URL base do portal CKAN de produção - usada só para montar o link "ver recurso original"; sem ela, o link simplesmente não aparece |
| `FAROL_PORTAL_SINTETICO` | `painel` | Não | Mesma coisa, para o ambiente sintético |
| `FAROL_SCANNER_URL` | `painel` | Não (default `http://scanner:8000`) | URL interna do serviço `scanner`, usada pela tela `/scan` (disparar/cancelar/acompanhar scan pelo navegador) |
| `FAROL_PII_ENGINE_URL` | `painel`, `ckanext-farol-guard` | Não (default `http://pii-engine:8000`) | URL interna do `pii-engine` |
| `FAROL_VERIFY_TLS` | `pii-engine` | Não (default `true`) | Verificação de certificado ao baixar recurso de terceiro - só desligue globalmente se souber exatamente por quê |
| `FAROL_HOSTS_TLS_INSEGURO` | `pii-engine` | Não (default vazio) | Lista de hosts (separados por vírgula) com certificado autoassinado conhecido - a única exceção aceitável ao `FAROL_VERIFY_TLS`, feita por host, nunca globalmente |
| `FAROL_LLM_URL` | `pii-engine` | Não (default `http://llm:8080`) | Onde a Camada 3 encontra o serviço `llm` |
| `FAROL_LLM_TIMEOUT_SECONDS` | `pii-engine` | Não (default `60`) | Timeout em segundos para a chamada à Camada 3/LLM |
| `FAROL_CKAN_STORAGE_PATH` | `pii-engine`, `scanner` | Não (default `/mnt/ckan/storage/resources`) | Diretório base para leitura direta de disco quando o `pii-engine`/`scanner` roda no mesmo host que tem o storage do CKAN montado (ver seção "Volume de dados de produção" do guia de instalação) |
| `MODEL_REPO` / `MODEL_FILE` | `model-downloader`, `llm` | Não (têm default: Qwen3-4B-GGUF) | Repositório e arquivo GGUF a baixar para a Camada 3 |
| `LLM_MODEL` | `llm`, `pii-engine` | Não (default `qwen3-4b`) | Alias do modelo servido pelo llama.cpp |
| `LLAMA_THREADS` | `llm` | Não (default `4`) | Threads de CPU para inferência da Camada 3 |

!!! note "Cada credencial é config, não código"
    Nenhuma URL de portal, senha ou token vive hardcoded no código-fonte - sempre variável de
    ambiente. Isso é deliberado: o motor (`pii-engine`) e o scanner são genéricos, reaproveitáveis
    por qualquer instalação CKAN; só a configuração é específica do órgão que roda o FAROL.

## Se você também estiver subindo um CKAN de teste do zero

O FAROL em si não exige nenhuma variável `CKAN_*` - elas pertencem ao `ckan-docker` (o CKAN em
si), não ao FAROL. Mas se o seu fluxo de instalação inclui subir um CKAN de teste (`ckan/ckan-docker`)
para praticar antes de apontar o scanner a um catálogo real, três convenções de nome coexistem
nesse `.env` e não são a mesma coisa - confundir uma com a outra faz a configuração ser
silenciosamente ignorada:

| Convenção | Exemplo | Mecanismo |
|---|---|---|
| `CKAN_<CHAVE>` - um underscore | `CKAN_SYSADMIN_PASSWORD` | Lista fixa e pequena, embutida no núcleo do CKAN. Só funciona para as poucas chaves que essa lista conhece. |
| `CKAN__<CHAVE>` - dois underscores | `CKAN__UPLOADS_ENABLED` | Mecanismo genérico do plugin `envvars`: converte `__` em `.`, então vira `ckan.uploads_enabled`. Use para qualquer config fora da lista fixa. |
| `CKAN___<NAMESPACE>__<CHAVE>` - três underscores no início | `CKAN___BEAKER__SESSION__SECRET` | Mesmo plugin, para configs fora do namespace `ckan.` (vira `beaker.session.secret`). |

Se uma variável nova não tiver efeito nenhum depois de `docker compose up -d`, essa tabela é o
primeiro lugar a checar antes de suspeitar de outra coisa.
