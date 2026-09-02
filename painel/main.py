"""
Painel tecnico e API do painel gerencial: o tecnico responde "por que
isso foi sinalizado?", o gerencial responde "estamos melhorando? quem
precisa de atencao?". Os dois leem a mesma base de achados que o scanner
grava, nunca o valor bruto de PII.

Login por sessao (cookie assinado), nunca HTTP Basic - credencial so' vai
na rede uma vez, no POST /login, nao em todo request. Ver login().
"""

import os
import secrets
from contextlib import asynccontextmanager

import httpx
import psycopg
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from psycopg.rows import dict_row
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

DSN = os.environ.get('FAROL_DB_DSN')
if not DSN:
    raise RuntimeError('FAROL_DB_DSN nao configurado')

# Mesma DDL de scanner/persistencia.py (_SCHEMA), duplicada aqui de proposito:
# painel e scanner sao imagens/servicos separados, sem PYTHONPATH
# compartilhado, entao o painel nao pode importar o modulo do scanner so'
# pra isso. Extrair um pacote compartilhado e' trabalho futuro, fora do
# escopo desta correcao - o que resolve aqui e' so' a corrida de startup
# (docker-compose nao tem `condition` no depends_on do scanner, entao numa
# subida limpa o painel podia responder antes do scanner criar o schema);
# a duplicacao do INSERT que ja existe entre os dois arquivos continua
# sendo outro achado, tambem fora deste lote.
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS achados (
    id SERIAL PRIMARY KEY,
    ambiente TEXT NOT NULL DEFAULT 'producao',
    org TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    recurso TEXT NOT NULL,
    recurso_nome TEXT,
    campo TEXT,
    categoria TEXT,
    confianca REAL,
    camada INT,
    veredito TEXT NOT NULL,
    motivo_nao_analisado TEXT,
    hash_arquivo TEXT,
    executado_por TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE achados ADD COLUMN IF NOT EXISTS hash_arquivo TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS recurso_nome TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS ambiente TEXT NOT NULL DEFAULT 'producao';
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisao TEXT NOT NULL DEFAULT 'pendente';
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisado_por TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisado_em TIMESTAMPTZ;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS justificativa TEXT;

CREATE TABLE IF NOT EXISTS execucoes (
    id SERIAL PRIMARY KEY,
    iniciado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em TIMESTAMPTZ,
    total_recursos INT,
    processados INT NOT NULL DEFAULT 0,
    recurso_atual TEXT,
    status TEXT NOT NULL DEFAULT 'rodando',
    executado_por TEXT NOT NULL,
    ambiente TEXT NOT NULL,
    orgs TEXT
);
ALTER TABLE execucoes ADD COLUMN IF NOT EXISTS formatos TEXT;
ALTER TABLE execucoes ADD COLUMN IF NOT EXISTS cancelar_solicitado BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS recursos_conhecidos (
    org TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    recurso TEXT NOT NULL,
    modificado_em TEXT,
    ultima_execucao_id INT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org, dataset_id, recurso)
);
'''


def _preparar_schema() -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(_SCHEMA)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _preparar_schema()
    yield

# Servico interno do scanner - nunca exposto direto pro host (ver
# docker-compose.yml). O painel autentica o humano (sessao) e repassa a
# chamada; o scanner em si so' confia em quem ja esta na rede interna do
# compose. Mesmo padrao do pii-engine, so' que o scanner nao tinha essa URL
# antes porque nunca precisou ser chamado por HTTP - so' rodava via CLI.
_SCANNER_URL = os.environ.get('FAROL_SCANNER_URL', 'http://scanner:8000')
_PII_ENGINE_URL = os.environ.get('FAROL_PII_ENGINE_URL', 'http://pii-engine:8000')

_SESSION_SECRET = os.environ.get('FAROL_SESSION_SECRET')
if not _SESSION_SECRET:
    raise RuntimeError('FAROL_SESSION_SECRET nao configurado - gere com: openssl rand -hex 32')

_SESSION_MAX_AGE_SEGUNDOS = 12 * 60 * 60  # reloga a cada 12h - equilibrio entre nao incomodar
                                            # quem esta revisando achado e nao deixar sessao eterna

app = FastAPI(title='FAROL - Painel', lifespan=_lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_SESSION_SECRET,
    max_age=_SESSION_MAX_AGE_SEGUNDOS,
    same_site='lax',
    https_only=True,  # o painel so' e' alcancavel via o sidecar TLS (painel-nginx) - ver docker-compose.yml
)
templates = Jinja2Templates(directory='templates')

_STATUS_VALIDOS = {'confirmado_positivo', 'falso_positivo'}

# Whitelist explicita: nunca interpolar o parametro `ordenar` vindo da URL
# direto na query SQL. Cada chave aqui e' um valor aceito na querystring;
# o valor e' a coluna SQL real, escrita por nos, nunca pelo usuario.
_COLUNAS_ORDENAVEIS = {
    'org': 'org', 'dataset': 'dataset_id', 'recurso': 'recurso',
    'campo': 'campo', 'categoria': 'categoria', 'confianca': 'confianca',
    'veredito': 'veredito',
}

# Base do portal onde o recurso de fato foi publicado, por ambiente. O painel
# nunca guarda nem exibe o valor de PII encontrado - em vez disso, monta um
# link direto para o recurso original no portal real, onde o revisor ve o
# dado no contexto de origem (ja e' dado aberto publicado) sem o FAROL
# precisar renderizar PII bruta na propria tela.
#
# Vem de variavel de ambiente, nao hardcoded aqui: dominio do portal e IP
# interno de rede sao dado especifico de cada instalacao, nao do motor
# generico - mesmo principio de "config por orgao, nao no codigo" que ja
# vale para FAROL_DB_DSN/FAROL_TECNICO_USER acima. Se a variavel nao
# existir, o link "ver recurso original" simplesmente nao aparece
# (index.html so' o mostra quando portal_base nao e' vazio) - nao e' erro
# fatal.
_PORTAL_URL = {
    'producao': os.environ.get('FAROL_PORTAL_PRODUCAO', ''),
    'sintetico': os.environ.get('FAROL_PORTAL_SINTETICO', ''),
}


def _proximo_seguro(proximo: str | None) -> str:
    """So aceita caminho relativo local como destino de pos-login.

    `proximo` chega via querystring/form, controlada por quem monta o link -
    sem essa checagem, um `/login?proximo=https://site-malicioso` levaria a
    um redirect pra fora do dominio depois do login (open redirect). `//`
    tambem e' rejeitado - navegador trata como protocol-relative URL, que
    tambem sai do dominio.
    """
    if not proximo or not proximo.startswith('/') or proximo.startswith('//'):
        return '/'
    return proximo


def _exigir_login(request: Request) -> str:
    """Devolve o usuario da sessao autenticada com papel 'tecnico', ou levanta 401.

    Tecnico e gerencial sao publicos diferentes (quem opera/revisa achado vs
    quem decide) - desde 2026-08-22 tem credencial propria cada um
    (FAROL_TECNICO_USER/PASSWORD aqui, FAROL_GERENCIAL_USER/PASSWORD em
    _exigir_login_gerencial), sessoes independentes (`papel` no cookie
    distingue as duas, mesmo mecanismo de sessao). Continua sendo uma
    credencial unica por publico, nao uma conta por pessoa - se um dia mais
    de uma pessoa revisar achado tecnico, o proximo passo e' credencial por
    pessoa (tabela de usuario), nao voltar a um campo de texto livre.

    O 401 levantado aqui vira redirect para /login em requisicao de
    navegador (ver o exception handler abaixo) e fica como 401 puro pra
    chamada via fetch/API.
    """
    if request.session.get('papel') != 'tecnico':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='login necessario')
    return request.session['usuario']


def _exigir_login_gerencial(request: Request) -> str:
    """Equivalente gerencial de _exigir_login - sessao propria (papel
    'gerencial'), credencial propria (FAROL_GERENCIAL_USER/PASSWORD). Uma
    sessao tecnica nao abre rota gerencial, e vice-versa."""
    if request.session.get('papel') != 'gerencial':
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='login necessario')
    return request.session['usuario']


@app.exception_handler(StarletteHTTPException)
async def _redireciona_login_se_navegador(request: Request, exc: StarletteHTTPException):
    eh_navegador = 'text/html' in (request.headers.get('accept') or '')
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and eh_navegador:
        destino = _proximo_seguro(request.url.path)
        # /api/gerencial/* e' a unica superficie protegida por
        # _exigir_login_gerencial - qualquer outra rota 401 pertence ao
        # publico tecnico, manda pro login certo em cada caso.
        pagina_login = '/login-gerencial' if request.url.path.startswith('/api/gerencial/') else '/login'
        return RedirectResponse(url=f'{pagina_login}?proximo={destino}', status_code=status.HTTP_303_SEE_OTHER)
    return await http_exception_handler(request, exc)


def _exigir_token_servico(x_farol_token: str = Header(...)) -> None:
    """Autentica chamada maquina-a-maquina (ex: ckanext-farol-guard), nao pessoa.

    Deliberadamente separado do login humano (cookie de sessao, usado no
    navegador): sao dois publicos e dois niveis de confianca diferentes -
    misturar os dois faria o plugin do CKAN precisar guardar a mesma sessao
    que autentica um humano no navegador.
    """
    token_esperado = os.environ.get('FAROL_INGEST_TOKEN')
    if not token_esperado:
        raise HTTPException(status_code=500, detail='FAROL_INGEST_TOKEN nao configurado')
    if not secrets.compare_digest(x_farol_token, token_esperado):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='token invalido')


class RegistroAchado(BaseModel):
    org: str
    dataset_id: str
    recurso: str
    recurso_nome: str | None = None
    executado_por: str
    ambiente: str = 'sintetico'
    resultado: dict  # mesmo formato devolvido por POST /v1/scan(-upload) do pii-engine


@app.get('/login')
def login_form(request: Request, proximo: str = '/', erro: str | None = None):
    if request.session.get('papel') == 'tecnico':
        return RedirectResponse(url=_proximo_seguro(proximo), status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request, 'login.html',
        {'proximo': _proximo_seguro(proximo), 'erro': erro, 'acao': '/login', 'titulo': 'Painel técnico'},
    )


@app.post('/login')
def login_submit(
    request: Request,
    usuario: str = Form(...),
    senha: str = Form(...),
    proximo: str = Form('/'),
):
    usuario_esperado = os.environ.get('FAROL_TECNICO_USER')
    senha_esperada = os.environ.get('FAROL_TECNICO_PASSWORD')
    if not usuario_esperado or not senha_esperada:
        raise HTTPException(status_code=500, detail='FAROL_TECNICO_USER/FAROL_TECNICO_PASSWORD nao configurados')

    usuario_confere = secrets.compare_digest(usuario, usuario_esperado)
    senha_confere = secrets.compare_digest(senha, senha_esperada)
    destino = _proximo_seguro(proximo)
    if not (usuario_confere and senha_confere):
        return RedirectResponse(url=f'/login?erro=1&proximo={destino}', status_code=status.HTTP_303_SEE_OTHER)

    request.session.clear()
    request.session['usuario'] = usuario
    request.session['papel'] = 'tecnico'
    return RedirectResponse(url=destino, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/login-gerencial')
def login_gerencial_form(request: Request, proximo: str = '/gerencial', erro: str | None = None):
    if request.session.get('papel') == 'gerencial':
        return RedirectResponse(url=_proximo_seguro(proximo), status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request, 'login.html',
        {'proximo': _proximo_seguro(proximo), 'erro': erro, 'acao': '/login-gerencial', 'titulo': 'Painel gerencial'},
    )


@app.post('/login-gerencial')
def login_gerencial_submit(
    request: Request,
    usuario: str = Form(...),
    senha: str = Form(...),
    proximo: str = Form('/gerencial'),
):
    usuario_esperado = os.environ.get('FAROL_GERENCIAL_USER')
    senha_esperada = os.environ.get('FAROL_GERENCIAL_PASSWORD')
    if not usuario_esperado or not senha_esperada:
        raise HTTPException(status_code=500, detail='FAROL_GERENCIAL_USER/FAROL_GERENCIAL_PASSWORD nao configurados')

    usuario_confere = secrets.compare_digest(usuario, usuario_esperado)
    senha_confere = secrets.compare_digest(senha, senha_esperada)
    destino = _proximo_seguro(proximo)
    if not (usuario_confere and senha_confere):
        return RedirectResponse(url=f'/login-gerencial?erro=1&proximo={destino}', status_code=status.HTTP_303_SEE_OTHER)

    request.session.clear()
    request.session['usuario'] = usuario
    request.session['papel'] = 'gerencial'
    return RedirectResponse(url=destino, status_code=status.HTTP_303_SEE_OTHER)


@app.get('/logout')
def logout(request: Request):
    pagina_login = '/login-gerencial' if request.session.get('papel') == 'gerencial' else '/login'
    request.session.clear()
    return RedirectResponse(url=pagina_login, status_code=status.HTTP_303_SEE_OTHER)


def _consultar(ambiente: str, ordenar: str | None = None, direcao: str = 'asc'):
    coluna_sql = _COLUNAS_ORDENAVEIS.get(ordenar or '')
    direcao_sql = 'DESC' if direcao == 'desc' else 'ASC'
    # coluna_sql so' vem da whitelist acima (ou e' None) - nunca do parametro cru,
    # entao interpolar aqui na string do ORDER BY e' seguro.
    order_by = f'{coluna_sql} {direcao_sql} NULLS LAST, timestamp DESC' if coluna_sql else 'timestamp DESC'
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        achados = conn.execute(
            f'SELECT * FROM achados WHERE ambiente = %s ORDER BY {order_by} LIMIT 200',
            (ambiente,),
        ).fetchall()
        stats = conn.execute(
            '''SELECT
                 count(DISTINCT recurso) AS recursos_auditados,
                 count(*) FILTER (WHERE veredito = 'bloquear') AS achados_alto_risco,
                 count(*) FILTER (WHERE veredito = 'nao_analisado') AS nao_analisados,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear') AND revisao = 'pendente') AS pendentes_revisao
               FROM achados WHERE ambiente = %s''',
            (ambiente,),
        ).fetchone()
        execucoes = conn.execute(
            '''SELECT * FROM execucoes WHERE ambiente = %s ORDER BY id DESC LIMIT 5''',
            (ambiente,),
        ).fetchall()
    return achados, stats, execucoes


@app.get('/')
def index(
    request: Request,
    ambiente: str = 'producao',
    ordenar: str | None = None,
    direcao: str = 'asc',
    usuario: str = Depends(_exigir_login),
):
    if ordenar not in _COLUNAS_ORDENAVEIS:
        ordenar = None
    if direcao not in ('asc', 'desc'):
        direcao = 'asc'
    achados, stats, execucoes = _consultar(ambiente, ordenar, direcao)
    tem_execucao_rodando = any(e['status'] == 'rodando' for e in execucoes)
    return templates.TemplateResponse(
        request, 'index.html',
        {
            'achados': achados, 'stats': stats, 'ambiente': ambiente,
            'execucoes': execucoes, 'tem_execucao_rodando': tem_execucao_rodando,
            'ordenar': ordenar, 'direcao': direcao,
            'portal_base': _PORTAL_URL.get(ambiente, ''),
            'usuario': usuario,
        },
    )


@app.post('/revisar/{achado_id}')
def revisar(
    achado_id: int,
    request: Request,
    status_revisao: str = Form(...),
    ambiente: str = Form('producao'),
    ordenar: str = Form(''),
    direcao: str = Form('asc'),
    usuario: str = Depends(_exigir_login),
):
    if status_revisao not in _STATUS_VALIDOS:
        raise HTTPException(status_code=400, detail='status invalido')
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        linha = conn.execute(
            '''UPDATE achados SET revisao = %s, revisado_por = %s, revisado_em = now()
               WHERE id = %s RETURNING revisao, revisado_por''',
            (status_revisao, usuario, achado_id),
        ).fetchone()
        conn.commit()
    if linha is None:
        raise HTTPException(status_code=404, detail='achado nao encontrado')

    # A tela chama este endpoint via fetch() (ver script no index.html) para
    # atualizar so' a linha revisada, sem navegar a pagina - por isso o botao
    # "confirmar"/"falso+" nao leva mais o usuario de volta ao topo da tabela.
    # O redirect abaixo so' roda se o JS nao executar (fallback sem JS).
    if request.headers.get('accept') == 'application/json':
        return linha
    url = f'/?ambiente={ambiente}'
    if ordenar in _COLUNAS_ORDENAVEIS:
        url += f'&ordenar={ordenar}&direcao={direcao}'
    return RedirectResponse(url=url, status_code=303)


@app.post('/v1/achados')
def registrar_achado(req: RegistroAchado, _: None = Depends(_exigir_token_servico)):
    """Ingestao maquina-a-maquina de achados, usada pelo ckanext-farol-guard.

    O scanner grava direto no Postgres porque roda como job em lote no
    mesmo host. O plugin preventivo roda dentro do container do CKAN, um
    ambiente/rede separado por design - dar a ele credencial direta de
    Postgres acoplaria o CKAN ao schema interno do FAROL. Este endpoint
    e' o mesmo papel que persistencia.gravar_resultado() cumpre para o
    scanner, so' que exposto por HTTP em vez de import direto.
    """
    achados = req.resultado.get('achados') or []
    hash_arquivo = req.resultado.get('hash_arquivo')
    veredito = req.resultado.get('veredito')
    if not veredito:
        raise HTTPException(status_code=400, detail='resultado.veredito ausente')

    with psycopg.connect(DSN) as conn:
        if not achados:
            conn.execute(
                '''INSERT INTO achados
                   (ambiente, org, dataset_id, recurso, recurso_nome, veredito, motivo_nao_analisado, hash_arquivo, executado_por)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (req.ambiente, req.org, req.dataset_id, req.recurso, req.recurso_nome, veredito,
                 req.resultado.get('motivo_nao_analisado'), hash_arquivo, req.executado_por),
            )
        else:
            for a in achados:
                conn.execute(
                    '''INSERT INTO achados
                       (ambiente, org, dataset_id, recurso, recurso_nome, campo, categoria, confianca, camada, justificativa, veredito, hash_arquivo, executado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (req.ambiente, req.org, req.dataset_id, req.recurso, req.recurso_nome, a['campo'], a['categoria'],
                     a['confianca'], a['camada'], a.get('justificativa'), veredito, hash_arquivo, req.executado_por),
                )
        conn.commit()
    return {'status': 'ok'}


# --- Disparar/cancelar/acompanhar scan pelo navegador ---
#
# Antes disso, a unica forma de rodar o scanner era `docker compose run`
# via SSH - decisao explicita do Mauricio de nao exigir isso, nem de
# administrador tecnico. O scanner virou um servico HTTP interno
# (scanner/main.py); estas rotas so' autenticam o humano e repassam a
# chamada. `executado_por` nunca vem de campo de texto livre - vem da
# sessao, mesmo principio ja usado em `revisado_por` (ver _exigir_login).


class IniciarScanRequest(BaseModel):
    base_url: str
    ambiente: str = 'sintetico'
    orgs: list[str] | None = None
    formatos: list[str] | None = None
    incremental: bool = False
    api_key: str | None = None
    verify: bool = True


class ListarOrganizacoesRequest(BaseModel):
    base_url: str
    api_key: str | None = None
    verify: bool = True


@app.get('/scan')
def tela_scan(request: Request, usuario: str = Depends(_exigir_login)):
    return templates.TemplateResponse(request, 'scan.html', {'usuario': usuario})


@app.post('/api/scan/organizacoes')
def api_scan_organizacoes(corpo: ListarOrganizacoesRequest, usuario: str = Depends(_exigir_login)):
    try:
        resp = httpx.post(
            f'{_SCANNER_URL}/organizacoes',
            json={'base_url': corpo.base_url, 'verify': corpo.verify, 'api_key': corpo.api_key},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f'nao foi possivel listar organizacoes: {e}')
    return resp.json()


@app.post('/api/scan/iniciar')
def api_scan_iniciar(corpo: IniciarScanRequest, usuario: str = Depends(_exigir_login)):
    try:
        resp = httpx.post(
            f'{_SCANNER_URL}/iniciar',
            json={
                'base_url': corpo.base_url,
                'engine_url': _PII_ENGINE_URL,
                'executado_por': usuario,
                'ambiente': corpo.ambiente,
                'orgs': corpo.orgs,
                'formatos': corpo.formatos,
                'incremental': corpo.incremental,
                'api_key': corpo.api_key,
                'verify': corpo.verify,
            },
            timeout=60,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f'nao foi possivel iniciar o scan: {e}')
    return resp.json()


@app.post('/api/scan/cancelar/{execucao_id}')
def api_scan_cancelar(execucao_id: int, usuario: str = Depends(_exigir_login)):
    try:
        resp = httpx.post(f'{_SCANNER_URL}/cancelar/{execucao_id}', timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f'nao foi possivel cancelar: {e}')
    return resp.json()


@app.get('/api/scan/execucoes')
def api_scan_execucoes(ambiente: str = 'sintetico', usuario: str = Depends(_exigir_login)):
    """Polling leve pra tela /scan - so' as ultimas execucoes, sem os
    achados nem os stats agregados que GET / ja carrega (a pagina de novo
    scan nao precisa deles, e pedir menos dado a cada poll importa mais
    aqui do que em GET /, que so' recarrega a pagina inteira a cada 10s)."""
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        execucoes = conn.execute(
            '''SELECT id, status, processados, total_recursos, recurso_atual,
                      executado_por, orgs, formatos, iniciado_em, finalizado_em
               FROM execucoes WHERE ambiente = %s ORDER BY id DESC LIMIT 5''',
            (ambiente,),
        ).fetchall()
    return {'execucoes': execucoes}


# --- API do painel gerencial (React/Vite em painel-gerencial/) ---
#
# Sessao propria (papel 'gerencial' no cookie, ver _exigir_login_gerencial
# acima) - independente da sessao do painel tecnico. O SPA nao implementa
# login proprio, so' chama estes endpoints com `credentials: 'same-origin'`
# e trata 401 redirecionando pra /login-gerencial. Nunca devolve achado
# individual nem valor de PII - so' agregado.

def _calcular_score_e_cobertura(linha: dict) -> tuple[int | None, int | None]:
    """Score de conformidade: fatia dos achados com resultado definitivo
    (fora nao_analisado, que nao foi sequer avaliado) que saiu como liberar -
    uma medida simples e explicavel, nao um indice composto opaco. Recurso
    nao_analisado conta a parte, na `cobertura`, porque "nao olhamos" e
    "olhamos e nao achamos nada" sao informacoes diferentes. Funcao pura
    (sem I/O) de proposito, pra dar pra testar a aritmetica sem precisar
    de um Postgres de teste.
    """
    avaliados = linha['liberados'] + linha['alertados'] + linha['bloqueados']
    score_conformidade = round(100 * linha['liberados'] / avaliados) if avaliados else None
    cobertura = round(100 * avaliados / linha['total']) if linha['total'] else None
    return score_conformidade, cobertura


@app.get('/api/gerencial/resumo')
def api_resumo(ambiente: str = 'producao', _: str = Depends(_exigir_login_gerencial)):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        linha = conn.execute(
            '''SELECT
                 count(DISTINCT recurso) AS recursos_auditados,
                 count(*) FILTER (WHERE veredito = 'liberar') AS liberados,
                 count(*) FILTER (WHERE veredito = 'alertar') AS alertados,
                 count(*) FILTER (WHERE veredito = 'bloquear') AS bloqueados,
                 count(*) FILTER (WHERE veredito = 'nao_analisado') AS nao_analisados,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear') AND revisao = 'pendente') AS pendentes_revisao,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear') AND revisao = 'confirmado_positivo') AS confirmados,
                 count(*) AS total
               FROM achados WHERE ambiente = %s''',
            (ambiente,),
        ).fetchone()

    score_conformidade, cobertura = _calcular_score_e_cobertura(linha)

    return {
        'recursos_auditados': linha['recursos_auditados'],
        'liberados': linha['liberados'],
        'alertados': linha['alertados'],
        'bloqueados': linha['bloqueados'],
        'nao_analisados': linha['nao_analisados'],
        'pendentes_revisao': linha['pendentes_revisao'],
        'confirmados': linha['confirmados'],
        'score_conformidade': score_conformidade,
        'cobertura': cobertura,
    }


@app.get('/api/gerencial/por-orgao')
def api_por_orgao(ambiente: str = 'producao', _: str = Depends(_exigir_login_gerencial)):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        linhas = conn.execute(
            '''SELECT
                 org,
                 count(DISTINCT recurso) AS recursos_auditados,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear')) AS achados_alto_risco,
                 count(*) FILTER (WHERE veredito = 'nao_analisado') AS nao_analisados,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear') AND revisao = 'pendente') AS pendentes_revisao
               FROM achados WHERE ambiente = %s
               GROUP BY org
               ORDER BY achados_alto_risco DESC, org ASC
               LIMIT 30''',
            (ambiente,),
        ).fetchall()
    return {'orgaos': linhas}


@app.get('/api/gerencial/tendencia')
def api_tendencia(ambiente: str = 'producao', dias: int = 30, _: str = Depends(_exigir_login_gerencial)):
    dias = max(1, min(dias, 365))
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        linhas = conn.execute(
            '''SELECT
                 date_trunc('day', timestamp)::date AS dia,
                 count(*) FILTER (WHERE veredito IN ('alertar','bloquear')) AS achados_alto_risco,
                 count(*) FILTER (WHERE veredito = 'nao_analisado') AS nao_analisados,
                 count(*) AS total
               FROM achados
               WHERE ambiente = %s AND timestamp >= now() - (%s || ' days')::interval
               GROUP BY dia
               ORDER BY dia ASC''',
            (ambiente, dias),
        ).fetchall()
    return {'dias': linhas}


@app.get('/health')
def health():
    return {'status': 'ok'}
