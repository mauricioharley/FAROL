# painel-gerencial

Painel gerencial do FAROL: responde "estamos melhorando? quem precisa de atenção?" - para
secretário, DPO, coordenação de dados abertos, diferente do painel técnico (nível recurso,
"por que isso foi sinalizado?"). Lê a mesma base de achados via a API JSON exposta pelo
`painel` (backend FastAPI, `/api/gerencial/*`) - nunca acessa o Postgres nem exibe achado
individual ou valor de PII, só agregado.

React + Vite, build estático servido por um nginx próprio. Sem tela de login própria dentro
do app React, mas com sessão e credencial próprias (`FAROL_GERENCIAL_USER`/
`FAROL_GERENCIAL_PASSWORD`, ver `_exigir_login_gerencial` em `painel/main.py`) - uma sessão do
painel técnico não abre a API do gerencial, e vice-versa. Se a chamada a `/api/gerencial/*`
voltar `401`, o app redireciona para `/login-gerencial`.

## Como subir

Parte do compose da raiz do repositório, nunca sozinho:

```bash
cp .env.example .env   # na raiz do repo, preencha antes
docker compose up -d painel painel-gerencial painel-nginx
```

`docker compose build painel-gerencial` roda `npm install` + `npm run build` dentro da
imagem (multi-stage, ver `Dockerfile`) - nada de Node instalado no host. Acesse via
`https://<host>:8080/gerencial` (o painel técnico continua em `https://<host>:8080/`, mesmo
domínio, mesmo certificado).

## Desenvolvimento local (fora do compose)

```bash
npm install
npm run dev   # http://localhost:5173, mas as chamadas a /api/gerencial/* vão falhar
              # sem um painel de verdade rodando por trás - use docker compose pra testar
              # o fluxo completo (auth + dado real)
```

## Testes

```bash
npm install
npm test
```

Roda com `vitest` + `@testing-library/react` (ambiente `jsdom`), local mesmo, fora do
container - o estágio final da imagem Docker é só nginx servindo `dist/` estático, não tem
Node pra rodar teste dentro dele. Cobre o estado de carregamento inicial (nada quebra nem
aparece antes das três chamadas a `/api/gerencial/*` resolverem), o caminho feliz (cards de
"Visão geral" com os valores retornados pela API), o redirecionamento para
`/login-gerencial` quando uma chamada volta `401` (sessão expirada), e o estado vazio de
`GraficoTendencia.jsx` (mensagem de dado insuficiente em vez do SVG).

## Rotas consumidas

| Rota | Descrição |
|---|---|
| `GET /api/gerencial/resumo?ambiente=` | contadores agregados (liberado/alertado/bloqueado/nao_analisado), score de conformidade, cobertura |
| `GET /api/gerencial/por-orgao?ambiente=` | ranking por organização (achado de alto risco, pendente de revisão, não analisado) |
| `GET /api/gerencial/tendencia?ambiente=&dias=` | contagem diária dos últimos N dias (padrão 30), para o gráfico de tendência |

Todas exigem sessão gerencial autenticada (`_exigir_login_gerencial` em `painel/main.py`),
independente da sessão do painel técnico.

## Decisões de projeto

- **Sem biblioteca de gráfico.** `GraficoTendencia.jsx` desenha um gráfico de barra simples
  em SVG puro - o volume de dado (no máximo um ponto por dia) é pequeno demais para
  justificar uma dependência só para isso. Se o painel crescer para mais tipos de
  visualização, vale reavaliar.
- **Score de conformidade definido de forma simples e explicável**, não um índice composto
  opaco: `liberados / (liberados + alertados + bloqueados)`. Recurso `nao_analisado` fica de
  fora dessa conta e aparece à parte, no campo `cobertura` - "não olhamos" e "olhamos e não
  achamos nada" são informações diferentes, mesmo princípio já aplicado no painel técnico.
- **`base: '/gerencial/'` no `vite.config.js`** - o app é servido sob esse prefixo pelo
  `painel-nginx` (terminador TLS), não na raiz do domínio (que continua sendo o painel
  técnico).

## Limitações conhecidas

Gráfico de tendência mostra sempre os últimos 30 dias corridos - sem seleção de período
customizado ainda. Ranking por órgão limitado aos 30 primeiros (ver `LIMIT 30` em
`painel/main.py`, `api_por_orgao`).
