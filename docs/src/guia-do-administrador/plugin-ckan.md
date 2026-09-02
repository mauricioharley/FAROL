# Plugin preventivo (`ckanext-farol-guard`)

**Construído e em funcionamento** - intercepta a criação de um recurso dentro do próprio CKAN,
antes de publicar, e decide `liberar`/`alertar`/`bloquear` chamando o mesmo `pii-engine` que o
scanner usa. É a única peça do FAROL que age de forma automática sobre um recurso - e só porque,
no momento em que o hook roda (`before_resource_create`), nada foi publicado ainda. Depois de
publicado, quem audita é o `scanner` ([Rodar o scanner](rodar-o-scanner.md)), e ele nunca marca
nada como privado sozinho - só notifica.

## Como funciona

1. `before_resource_create` intercepta o recurso antes de ele ser salvo.
2. Upload de arquivo → `POST /v1/scan-upload` do `pii-engine` (o arquivo ainda não tem URL nem
   foi salvo em disco neste momento). Link externo → `POST /v1/scan` com a URL. Ver
   [Referência de API](../referencia-api/pii-engine.md).
3. Registra o achado via `POST /v1/achados` do painel, **sempre** - inclusive quando o veredito é
   `liberar`, para manter a trilha de auditoria completa.
4. Se o veredito for `bloquear` (ou `nao_analisado`, só quando configurado para isso), levanta
   `ValidationError` - o upload nunca chega a ser salvo, com uma mensagem sem jargão técnico
   mostrada a quem tentou publicar. Nos outros casos, o upload segue normalmente e fica marcado
   como pendente de revisão no painel.

Se o `pii-engine` estiver inalcançável, o plugin **não trava o CKAN** - trata como
`nao_analisado` (mesma política permissiva do resto do FAROL), nunca bloqueia por erro de rede
nem libera silenciosamente sem registrar.

## Instalar

**Não pode ser bind mount + `pip install -e` em runtime** (mesmo padrão documentado no README
do plugin). O `prerun.py` do CKAN (`ckan db init`, geração do token do datapusher)
carrega todos os plugins listados em `CKAN__PLUGINS` antes de qualquer script de
`docker-entrypoint.d` rodar - um plugin só instalado depois disso quebra o boot inteiro assim que
aparece em `CKAN__PLUGINS`. A instalação precisa acontecer em **build time**, dentro do
`Dockerfile` do CKAN, como root, antes de trocar para o usuário `ckan` (que não tem permissão de
escrita em site-packages):

```dockerfile
# dentro de ckan-docker/ckan/Dockerfile, ainda como USER root
COPY --chown=ckan-sys:ckan-sys ckanext-farol-guard /srv/app/src/ckanext-farol-guard
RUN pip3 install --no-cache-dir --no-deps -e /srv/app/src/ckanext-farol-guard
```

O código do plugin fica num repositório próprio (`ckanext-farol-guard/`, fora do clone do
`ckan-docker`) e **precisa estar sincronizado** dentro de `ckan-docker/ckan/ckanext-farol-guard/`
antes de cada build - não é mais editável ao vivo via bind mount:

```bash
rsync -a --delete ckanext-farol-guard/ ckan-docker/ckan/ckanext-farol-guard/ \
    --exclude .git --exclude .gitignore
cd ckan-docker && docker compose build ckan && docker compose up -d ckan
```

Depois de instalado, adicione `lgpd_guard` a `CKAN__PLUGINS` no `.env` do `ckan-docker`.

## Variáveis de ambiente (do container do CKAN, não do resto do FAROL)

Lidas direto de `os.environ` - **não** passam pelo mecanismo `CKAN___` do `ckanext-envvars`
(essas variáveis são do FAROL, não do núcleo do CKAN):

| Variável | Default | Descrição |
|---|---|---|
| `FAROL_PII_ENGINE_URL` | `http://pii-engine:8000` | onde chamar o motor de detecção |
| `FAROL_PAINEL_URL` | `http://painel:8080` | onde registrar o achado |
| `FAROL_INGEST_TOKEN` | (nenhum) | token de serviço exigido pelo painel; sem ele, o achado só é logado, não persistido |
| `FAROL_AMBIENTE` | `sintetico` | rótulo gravado no achado (`sintetico`/`producao`) |
| `FAROL_BLOQUEIA_NAO_ANALISADO` | `false` | se `true`, trata `nao_analisado` como bloqueio - padrão é o mais permissivo |
| `FAROL_CONTATO_SUPORTE` | (vazio) | e-mail/canal mostrado a quem teve o upload bloqueado |

## Contrato com o backend - não é acoplado ao FAROL especificamente

O plugin fala só HTTP contra os endpoints acima - qualquer serviço que implemente o mesmo
contrato (`/v1/scan`, `/v1/scan-upload`, opcionalmente `/v1/achados`) funciona no lugar do
`pii-engine`/painel do FAROL, sem alterar uma linha do plugin.

## Limitação conhecida

O achado gravado quando o veredito é `alertar`/`nao_analisado` usa um UUID pré-atribuído ao
recurso neste mesmo hook. Se, por outro motivo, a criação do recurso falhar depois deste hook
(outra validação do CKAN), o achado registrado fica órfão - descreve corretamente o que foi
escaneado, mas o link "ver recurso original" do painel não resolve. Caso raro, aceitável no
estágio atual do projeto.
