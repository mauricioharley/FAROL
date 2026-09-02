"""
Testes do login por sessao (main.py). Substitui o antigo HTTP Basic - aqui
cobrimos o fluxo completo (login, logout, redirecionamento pra quem chega
sem sessao) e a protecao contra open redirect em `proximo`.
"""

import os

import pytest
from fastapi.testclient import TestClient

from main import _proximo_seguro, app

USUARIO = os.environ['FAROL_TECNICO_USER']
SENHA = os.environ['FAROL_TECNICO_PASSWORD']
USUARIO_GERENCIAL = os.environ['FAROL_GERENCIAL_USER']
SENHA_GERENCIAL = os.environ['FAROL_GERENCIAL_PASSWORD']


@pytest.fixture
def client():
    # base_url https: o SessionMiddleware real (main.py) marca o cookie de
    # sessao como Secure (https_only=True, ver justificativa la) - o
    # TestClient tem que simular uma origem https de verdade, senao o
    # proprio httpx descarta o cookie por conta propria e o teste falharia
    # por um motivo que nao existe em producao (o painel so' roda atras de
    # TLS, ver painel-nginx).
    return TestClient(app, base_url='https://testserver')


def test_proximo_seguro_aceita_caminho_relativo():
    assert _proximo_seguro('/gerencial') == '/gerencial'


def test_proximo_seguro_rejeita_url_absoluta_de_outro_dominio():
    assert _proximo_seguro('https://site-malicioso.example/phish') == '/'


def test_proximo_seguro_rejeita_protocol_relative_url():
    assert _proximo_seguro('//site-malicioso.example') == '/'


def test_proximo_seguro_vazio_ou_ausente_vira_raiz():
    assert _proximo_seguro(None) == '/'
    assert _proximo_seguro('') == '/'


def test_get_raiz_sem_sessao_e_401_para_chamada_nao_navegador(client):
    resp = client.get('/', headers={'Accept': 'application/json'})
    assert resp.status_code == 401


def test_get_raiz_sem_sessao_navegador_redireciona_para_login(client):
    resp = client.get('/', headers={'Accept': 'text/html'}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers['location'].startswith('/login')


def test_login_com_senha_errada_nao_autentica(client):
    resp = client.post(
        '/login', data={'usuario': USUARIO, 'senha': 'senha-errada', 'proximo': '/'}, follow_redirects=False,
    )
    assert resp.status_code == 303
    assert 'erro=1' in resp.headers['location']

    resp2 = client.get('/', headers={'Accept': 'application/json'})
    assert resp2.status_code == 401


def test_login_correto_autentica_e_libera_acesso(client):
    resp = client.post(
        '/login', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/'}, follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers['location'] == '/'

    resp2 = client.get('/')
    assert resp2.status_code == 200


def test_proximo_e_respeitado_apos_login(client):
    resp = client.post(
        '/login', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/gerencial'}, follow_redirects=False,
    )
    assert resp.headers['location'] == '/gerencial'


def test_proximo_malicioso_e_ignorado_mesmo_apos_login_correto(client):
    resp = client.post(
        '/login',
        data={'usuario': USUARIO, 'senha': SENHA, 'proximo': 'https://site-malicioso.example'},
        follow_redirects=False,
    )
    assert resp.headers['location'] == '/'


def test_logout_limpa_sessao(client):
    client.post('/login', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/'})
    client.get('/logout')
    resp = client.get('/', headers={'Accept': 'application/json'})
    assert resp.status_code == 401


# --- /login-gerencial: credencial propria, desde 2026-08-22 ---
# Tecnico e gerencial sao publicos diferentes - ver _exigir_login_gerencial
# em main.py. Os testes de isolamento entre as duas sessoes (uma nao abre
# rota da outra) ficam em test_api_gerencial.py, perto do que protegem.


def test_login_gerencial_com_credencial_tecnica_nao_autentica(client):
    # A credencial do painel tecnico nao deve servir pro login gerencial -
    # sao dois pares diferentes, nao um so' verificado de dois jeitos.
    resp = client.post(
        '/login-gerencial', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/gerencial'},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert 'erro=1' in resp.headers['location']


def test_login_gerencial_correto_autentica_e_libera_acesso_gerencial(client):
    resp = client.post(
        '/login-gerencial',
        data={'usuario': USUARIO_GERENCIAL, 'senha': SENHA_GERENCIAL, 'proximo': '/gerencial'},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers['location'] == '/gerencial'

    resp2 = client.get('/api/gerencial/resumo?ambiente=producao')
    assert resp2.status_code == 200
