"""
Servico HTTP do scanner: dispara, cancela e ajuda a preencher a tela de
"novo scan" do painel. Antes disso, o scanner so' rodava via `docker
compose run` (linha de comando) - decisao explicita do Mauricio: a
ferramenta nao deve exigir interacao por CLI, nem de administrador
tecnico.

Nunca exposto direto pra fora do compose - so' o `painel` fala com este
servico, dentro da rede interna (mesmo padrao que o `painel` ja usa pra
falar com o `pii-engine`). O painel autentica o humano (sessao); este
servico so' confia em quem ja esta na rede interna do compose.

O scan em si roda numa thread separada (bloqueia em download HTTP e em
chamada ao pii-engine) - a thread grava progresso em `execucoes` a cada
recurso (persistencia.py), e quem quiser acompanhar le esse progresso
direto do banco (e' o que o painel ja faz) - por isso nao existe um
endpoint de "status" aqui, so' iniciar/cancelar/listar organizacao.
"""

import threading
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from persistencia import preparar_schema, solicitar_cancelamento
from run import preparar_execucao, rodar_execucao


@asynccontextmanager
async def _lifespan(app: FastAPI):
    preparar_schema()
    yield


app = FastAPI(title='FAROL - Scanner', lifespan=_lifespan)


@app.get('/health')
def health():
    return {'status': 'ok'}


class ListarOrganizacoesBody(BaseModel):
    base_url: str
    api_key: str | None = None
    verify: bool = True


@app.post('/organizacoes')
def organizacoes(corpo: ListarOrganizacoesBody):
    """Proxy fino pro organization_list do CKAN alvo - so' pra popular o
    seletor de organizacao na tela de novo scan do painel, antes de
    disparar qualquer coisa; nao lista recurso nem baixa nada.
    """
    headers = {'Authorization': corpo.api_key} if corpo.api_key else {}
    try:
        resp = requests.get(
            f'{corpo.base_url}/api/3/action/organization_list', headers=headers, verify=corpo.verify, timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f'nao foi possivel listar organizacoes: {e}')
    return {'organizacoes': resp.json()['result']}


class IniciarScanBody(BaseModel):
    base_url: str
    engine_url: str
    executado_por: str
    ambiente: str = 'sintetico'
    orgs: list[str] | None = None
    formatos: list[str] | None = None
    incremental: bool = False
    usar_disco: bool = False
    api_key: str | None = None
    verify: bool = True


@app.post('/iniciar')
def iniciar(body: IniciarScanBody):
    # A listagem (so' metadado, via API do CKAN) roda aqui, sincrona - rapida
    # o bastante pra devolver o execucao_id na resposta deste POST, sem
    # precisar de um segundo endpoint so' pra "me diga o id que voce gerou".
    # So' a parte lenta (baixar e classificar cada recurso) vai pra thread.
    try:
        execucao_id, recursos = preparar_execucao(
            base_url=body.base_url, api_key=body.api_key, verify=body.verify,
            executado_por=body.executado_por, orgs_filtro=body.orgs,
            formatos_filtro=body.formatos, ambiente=body.ambiente, incremental=body.incremental,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f'nao foi possivel listar recursos do CKAN: {e}')

    thread = threading.Thread(
        target=rodar_execucao,
        args=(execucao_id, recursos, body.engine_url, body.executado_por, body.ambiente, body.usar_disco),
        daemon=True,
    )
    thread.start()
    return {'execucao_id': execucao_id, 'total_recursos': len(recursos)}


@app.post('/cancelar/{execucao_id}')
def cancelar(execucao_id: int):
    solicitar_cancelamento(execucao_id)
    return {'ok': True}
