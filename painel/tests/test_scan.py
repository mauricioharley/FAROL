"""
Testes das rotas de disparar/cancelar/acompanhar scan pelo navegador
(main.py). As chamadas ao scanner (httpx.get/post) sao mockadas aqui - o
comportamento real do scanner ja e' coberto em scanner/tests; o foco aqui
e' o contrato do painel: exige sessao, repassa `executado_por` da sessao
(nunca de campo livre), e serve os dados certos pro polling de execucoes.
"""

import os
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import app

DSN = os.environ['FAROL_DB_DSN']
USUARIO = os.environ['FAROL_TECNICO_USER']
SENHA = os.environ['FAROL_TECNICO_PASSWORD']


@pytest.fixture
def logged_client():
    client = TestClient(app, base_url='https://testserver')
    client.post('/login', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/'})
    return client


@pytest.fixture
def execucao_de_teste():
    with psycopg.connect(DSN) as conn:
        cur = conn.execute(
            '''INSERT INTO execucoes (total_recursos, processados, status, executado_por, ambiente, orgs, formatos)
               VALUES (10, 3, 'rodando', 'pytest', 'sintetico', 'org-teste', 'csv') RETURNING id'''
        )
        execucao_id = cur.fetchone()[0]
        conn.commit()
    yield execucao_id
    with psycopg.connect(DSN) as conn:
        conn.execute('DELETE FROM execucoes WHERE id = %s', (execucao_id,))
        conn.commit()


def test_tela_scan_exige_login():
    client = TestClient(app, base_url='https://testserver')
    resp = client.get('/scan')
    assert resp.status_code == 401


def test_tela_scan_responde_para_quem_esta_logado(logged_client):
    resp = logged_client.get('/scan')
    assert resp.status_code == 200


@patch('main.httpx.post')
def test_api_scan_organizacoes_repassa_pro_scanner(mock_post, logged_client):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {'organizacoes': ['org1', 'org2']}
    mock_post.return_value.raise_for_status = lambda: None

    resp = logged_client.post('/api/scan/organizacoes', json={'base_url': 'https://ckan.example'})

    assert resp.status_code == 200
    assert resp.json() == {'organizacoes': ['org1', 'org2']}
    chamada_url, chamada_kwargs = mock_post.call_args
    assert chamada_kwargs['json']['base_url'] == 'https://ckan.example'


def test_api_scan_organizacoes_exige_login():
    client = TestClient(app, base_url='https://testserver')
    resp = client.post('/api/scan/organizacoes', json={'base_url': 'https://ckan.example'})
    assert resp.status_code == 401


@patch('main.httpx.post')
def test_api_scan_iniciar_usa_usuario_da_sessao_como_executado_por(mock_post, logged_client):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {'execucao_id': 1, 'total_recursos': 5}
    mock_post.return_value.raise_for_status = lambda: None

    resp = logged_client.post('/api/scan/iniciar', json={'base_url': 'https://ckan.example'})

    assert resp.status_code == 200
    corpo_enviado_ao_scanner = mock_post.call_args.kwargs['json']
    # executado_por vem da sessao autenticada, nunca de campo livre no corpo
    # da requisicao - o corpo que o navegador manda nem tem esse campo.
    assert corpo_enviado_ao_scanner['executado_por'] == USUARIO
    assert corpo_enviado_ao_scanner['base_url'] == 'https://ckan.example'


@patch('main.httpx.post')
def test_api_scan_iniciar_erro_do_scanner_vira_502(mock_post, logged_client):
    import httpx
    mock_post.side_effect = httpx.HTTPError('scanner fora do ar')
    resp = logged_client.post('/api/scan/iniciar', json={'base_url': 'https://ckan.example'})
    assert resp.status_code == 502


@patch('main.httpx.post')
def test_api_scan_cancelar_repassa_id(mock_post, logged_client):
    mock_post.return_value = MagicMock(status_code=200)
    mock_post.return_value.json.return_value = {'ok': True}
    mock_post.return_value.raise_for_status = lambda: None

    resp = logged_client.post('/api/scan/cancelar/42')

    assert resp.status_code == 200
    url_chamada = mock_post.call_args.args[0]
    assert url_chamada.endswith('/cancelar/42')


def test_api_scan_execucoes_reflete_banco_real(logged_client, execucao_de_teste):
    resp = logged_client.get('/api/scan/execucoes?ambiente=sintetico')
    assert resp.status_code == 200
    ids = [e['id'] for e in resp.json()['execucoes']]
    assert execucao_de_teste in ids


def test_api_scan_execucoes_exige_login():
    client = TestClient(app, base_url='https://testserver')
    resp = client.get('/api/scan/execucoes')
    assert resp.status_code == 401
