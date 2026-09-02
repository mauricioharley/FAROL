# painel

Backend do FAROL para os dois painéis: o técnico (server-rendered aqui mesmo, Jinja2)
responde "por que isso foi sinalizado?"; a API JSON deste mesmo serviço (`/api/gerencial/*`)
alimenta o painel gerencial (`painel-gerencial/`, React/Vite), que responde "estamos
melhorando? quem precisa de atenção?". Os dois leem a mesma base de achados que o `scanner`
grava e que o `ckanext-farol-guard` alimenta via API - nunca o valor bruto de PII, só campo,
categoria, confiança, camada, veredito e uma trilha de quem/quando revisou.

## Como subir

Parte do compose da raiz do repositório, nunca sozinho:

```bash
cp .env.example .env   # na raiz do repo, preencha antes
docker compose up -d painel painel-gerencial painel-nginx
```

Nem `painel` nem `painel-gerencial` publicam porta pro host - só são alcançáveis pelo
sidecar `painel-nginx`, que termina TLS com um certificado autoassinado (gerado a cada start
do container, ver `nginx/Dockerfile`) e faz proxy interno pros dois. Acesse em
`https://<host>:8080` (painel técnico) e `https://<host>:8080/gerencial` (painel gerencial) -
o aviso de certificado autoassinado é esperado no ambiente de teste, troque por um
certificado real num deploy em produção. Sem esse terminador, a credencial de login
trafegaria em claro na rede.

**Depois de rebuildar `painel` ou `painel-gerencial`, reinicie `painel-nginx` também**
(`docker compose restart painel-nginx`) - o nginx resolve o IP dos serviços upstream uma
vez, no start do worker, e não atualiza sozinho quando o container é recriado com um IP
novo. Sem esse restart, a próxima requisição vira `502 Bad Gateway` com
`connect() failed (111: Connection refused)` no log, mesmo com o serviço de verdade
saudável e respondendo.

## Autenticação

Três mecanismos, três públicos - nenhum é HTTP Basic:

- **Login humano do painel técnico** (`FAROL_TECNICO_USER`/`FAROL_TECNICO_PASSWORD`) - formulário
  em `/login`, sessão guardada num cookie assinado (`itsdangerous`, via `SessionMiddleware` do
  Starlette), nunca a credencial em si indo em todo request. Cookie `Secure` + `HttpOnly` +
  `SameSite=Lax`, expira em 12h (`_SESSION_MAX_AGE_SEGUNDOS`, `main.py`). Ainda é uma credencial
  única compartilhada, não uma conta por pessoa (ver limitação abaixo) - isso é sobre múltiplas
  pessoas revisando achado, diferente da separação abaixo.
- **Login humano do painel gerencial** (`FAROL_GERENCIAL_USER`/`FAROL_GERENCIAL_PASSWORD`,
  desde 2026-08-22) - formulário próprio em `/login-gerencial`, sessão independente da do
  técnico (`papel` no cookie distingue as duas - `_exigir_login`/`_exigir_login_gerencial` em
  `main.py`). **Uma sessão nunca abre a rota da outra**, mesmo com os dois cookies válidos ao
  mesmo tempo no navegador - técnico e gerencial são públicos diferentes (quem opera/revisa o
  motor vs. quem decide), não a mesma pessoa logada em duas telas. O SPA do gerencial
  (`painel-gerencial/`) continua sem tela de login própria - só redireciona pra
  `/login-gerencial` se a API devolver `401`.
- **Token de serviço** (`FAROL_INGEST_TOKEN`, header `X-Farol-Token`) - usado só pelo
  `ckanext-farol-guard` para registrar achado via `POST /v1/achados`. Deliberadamente separado
  do login humano - o CKAN não precisa guardar a mesma sessão que autentica uma pessoa no
  navegador. O `scanner` não usa este endpoint - grava direto no Postgres, porque roda como
  job em lote no mesmo host.

`FAROL_SESSION_SECRET` assina o cookie de sessão - sem ele o serviço nem sobe (`RuntimeError`
na importação, mesmo padrão de `FAROL_DB_DSN`). Gere com `openssl rand -hex 32`; trocar o
valor invalida toda sessão ativa (força relogin geral).

## Endpoints

- `GET /login`, `POST /login` - sessão do painel técnico. `GET /login-gerencial`,
  `POST /login-gerencial` - sessão própria do painel gerencial, desde 2026-08-22. `GET /logout`
  encerra a sessão ativa (qualquer uma das duas) e manda de volta pra tela de login certa,
  conforme o `papel` guardado na sessão.
- `GET /` - tabela de achados do painel técnico (filtro por ambiente `sintetico`/`producao`,
  ordenação por coluna via whitelist fixa - nunca interpola o parâmetro da URL na query SQL).
- `POST /revisar/{achado_id}` - marca `confirmado_positivo`/`falso_positivo`; autor vem da
  sessão autenticada, nunca de campo de texto livre.
- `GET /scan` - tela de novo scan (organização, formato de arquivo, modo incremental,
  progresso em tempo real, cancelar). Proxy autenticado pro serviço `scanner` (ver abaixo) -
  antes de 2026-08-22 isso só existia via `docker compose run` por linha de comando; decisão
  explícita do Mauricio de não exigir isso, nem de administrador técnico.
- `POST /api/scan/organizacoes`, `POST /api/scan/iniciar`, `POST /api/scan/cancelar/{id}`,
  `GET /api/scan/execucoes` - repassam pro `scanner` (nunca exposto direto pro host), injetando
  `executado_por` da sessão autenticada - o corpo que o navegador manda nem tem esse campo.
- `GET /api/gerencial/resumo`, `GET /api/gerencial/por-orgao`, `GET /api/gerencial/tendencia`
  - dado agregado para o painel gerencial (ver `painel-gerencial/README.md`).
- `POST /v1/achados` - ingestão máquina-a-máquina (token de serviço), usada pelo plugin.
- `GET /health`.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `FAROL_DB_DSN` | Sim | string de conexão Postgres (mesmo banco que o `scanner` usa) |
| `FAROL_TECNICO_USER` / `FAROL_TECNICO_PASSWORD` | Sim | credencial de login do painel técnico; gere a senha com `openssl rand -hex 16` |
| `FAROL_GERENCIAL_USER` / `FAROL_GERENCIAL_PASSWORD` | Sim | credencial própria do painel gerencial (desde 2026-08-22), separada da do técnico |
| `FAROL_SESSION_SECRET` | Sim | assina o cookie de sessão; gere com `openssl rand -hex 32` |
| `FAROL_INGEST_TOKEN` | Não | token de serviço para `POST /v1/achados`; sem ele, o plugin só loga aviso e não persiste (ver `ckanext-farol-guard/README.md`) |
| `FAROL_PORTAL_PRODUCAO` / `FAROL_PORTAL_SINTETICO` | Não | URL pública de cada portal, só para montar o link "ver recurso original" - nunca usada para autenticar nem baixar nada |
| `FAROL_SCANNER_URL` | Não | URL interna do serviço `scanner`; default `http://scanner:8000`, só muda em topologia não padrão |
| `FAROL_PII_ENGINE_URL` | Não | URL interna do `pii-engine`, repassada pro `scanner` ao disparar um scan pela tela `/scan`; default `http://pii-engine:8000` |

## Testes

```bash
docker compose run --rm -e PYTHONPATH=/app \
  -v $(pwd)/painel/tests:/app/tests \
  -v $(pwd)/painel/requirements-test.txt:/app/requirements-test.txt \
  --entrypoint sh painel \
  -c "pip install --no-cache-dir -r requirements-test.txt -q && pytest -q tests"
```

Cria um banco Postgres descartável no mesmo servidor (`farol_test_<hash>`, apagado no fim da
rodada via `pytest_sessionfinish`) - nunca toca no banco `farol` de verdade, mesmo rodando
`docker compose run` com a rede/credencial reais. Cobre o fluxo de login/logout, a proteção
contra open redirect em `proximo`, a aritmética de score/cobertura do painel gerencial, os
três endpoints `/api/gerencial/*` (exigem sessão *gerencial*, nunca devolvem valor bruto), as
rotas `/api/scan/*` (chamada ao `scanner` mockada, `executado_por` vindo da sessão, erro de rede
virando `502`) e o isolamento entre as duas sessões (uma credencial nunca abre a rota da outra,
`/login-gerencial` rejeita a credencial técnica e vice-versa).

## Limitações conhecidas

- **Cada painel tem credencial única compartilhada, não uma conta por pessoa.** Técnico e
  gerencial já são separados um do outro (desde 2026-08-22) - a limitação que resta é dentro de
  cada um: enquanto só uma pessoa por painel revisa achado/consulta indicador, aceitável; se
  isso mudar, o próximo passo é credencial por pessoa (tabela de usuário) em cada painel, nunca
  voltar a um campo de texto livre para autoria.
