"""
Testes da API do painel gerencial (main.py). A aritmetica de score/cobertura
e' testada como funcao pura (sem banco); os endpoints em si sao testados
contra o banco de teste descartavel (ver conftest.py).
"""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from main import _calcular_score_e_cobertura, app

DSN = os.environ['FAROL_DB_DSN']
USUARIO_TECNICO = os.environ['FAROL_TECNICO_USER']
SENHA_TECNICO = os.environ['FAROL_TECNICO_PASSWORD']
USUARIO = os.environ['FAROL_GERENCIAL_USER']
SENHA = os.environ['FAROL_GERENCIAL_PASSWORD']


def test_score_e_cobertura_com_dado_misto():
    linha = {'liberados': 3, 'alertados': 1, 'bloqueados': 1, 'total': 6}
    score, cobertura = _calcular_score_e_cobertura(linha)
    assert score == 60  # 3 / (3+1+1)
    assert cobertura == 83  # 5 / 6, arredondado


def test_score_e_cobertura_sem_nada_avaliado_e_none_nao_zero():
    # None (nao 0%) e' o valor certo aqui: "nao ha dado suficiente pra
    # calcular" e' diferente de "conformidade zero" - confundir os dois
    # faria um catalogo vazio parecer uma crise de conformidade.
    linha = {'liberados': 0, 'alertados': 0, 'bloqueados': 0, 'total': 0}
    score, cobertura = _calcular_score_e_cobertura(linha)
    assert score is None
    assert cobertura is None


def test_score_100_quando_tudo_liberado():
    linha = {'liberados': 5, 'alertados': 0, 'bloqueados': 0, 'total': 5}
    score, cobertura = _calcular_score_e_cobertura(linha)
    assert score == 100
    assert cobertura == 100


@pytest.fixture
def logged_client():
    # base_url https: mesmo motivo do fixture equivalente em test_auth.py -
    # o cookie de sessao e' Secure de verdade (https_only=True), TestClient
    # precisa simular origem https pra guardar/reenviar o cookie. Login pelo
    # /login-gerencial (credencial propria desde 2026-08-22, ver
    # _exigir_login_gerencial em main.py) - /login (tecnico) nao abre mais
    # rota /api/gerencial/*.
    client = TestClient(app, base_url='https://testserver')
    client.post('/login-gerencial', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/gerencial'})
    return client


@pytest.fixture
def logged_client_tecnico():
    client = TestClient(app, base_url='https://testserver')
    client.post('/login', data={'usuario': USUARIO_TECNICO, 'senha': SENHA_TECNICO, 'proximo': '/'})
    return client


@pytest.fixture
def achado_de_teste():
    with psycopg.connect(DSN) as conn:
        conn.execute(
            '''INSERT INTO achados (ambiente, org, dataset_id, recurso, veredito, executado_por)
               VALUES ('producao', 'org-teste', 'dataset-teste', 'recurso-1', 'alertar', 'pytest')'''
        )
        conn.commit()
    yield
    with psycopg.connect(DSN) as conn:
        conn.execute("DELETE FROM achados WHERE org = 'org-teste'")
        conn.commit()


def test_api_resumo_reflete_dado_real(logged_client, achado_de_teste):
    resp = logged_client.get('/api/gerencial/resumo?ambiente=producao')
    assert resp.status_code == 200
    assert resp.json()['alertados'] >= 1


def test_api_por_orgao_lista_org_de_teste(logged_client, achado_de_teste):
    resp = logged_client.get('/api/gerencial/por-orgao?ambiente=producao')
    assert resp.status_code == 200
    orgs = [o['org'] for o in resp.json()['orgaos']]
    assert 'org-teste' in orgs


def test_api_gerencial_exige_login():
    client = TestClient(app)
    resp = client.get('/api/gerencial/resumo', headers={'Accept': 'application/json'})
    assert resp.status_code == 401


def test_api_gerencial_nunca_devolve_valor_bruto(logged_client, achado_de_teste):
    # Nenhuma resposta da API gerencial pode ter um campo de valor/trecho -
    # so' agregado. Checagem defensiva: nenhuma das tres rotas devolve o
    # nome do dataset/recurso de teste em lugar nenhum do corpo.
    for rota in ('resumo', 'por-orgao', 'tendencia'):
        resp = logged_client.get(f'/api/gerencial/{rota}?ambiente=producao')
        assert 'dataset-teste' not in resp.text
        assert 'recurso-1' not in resp.text


def test_sessao_tecnica_nao_abre_rota_gerencial(logged_client_tecnico):
    # Credencial propria desde 2026-08-22 (pedido do Mauricio): uma sessao
    # tecnica valida (FAROL_TECNICO_USER/PASSWORD) nao deve conseguir ler a
    # API gerencial - sao publicos diferentes, nao so' duas telas do mesmo
    # login.
    resp = logged_client_tecnico.get(
        '/api/gerencial/resumo?ambiente=producao', headers={'Accept': 'application/json'},
    )
    assert resp.status_code == 401


def test_sessao_gerencial_nao_abre_rota_tecnica(logged_client):
    # E o inverso: uma sessao gerencial valida nao abre o painel tecnico
    # (tabela de achados, revisao) nem a tela de disparar scan.
    resp = logged_client.get('/', headers={'Accept': 'application/json'})
    assert resp.status_code == 401
    resp = logged_client.get('/scan', headers={'Accept': 'application/json'})
    assert resp.status_code == 401


def test_logout_volta_pro_login_certo_conforme_o_papel(logged_client, logged_client_tecnico):
    resp_gerencial = logged_client.get('/logout', follow_redirects=False)
    assert resp_gerencial.headers['location'] == '/login-gerencial'

    resp_tecnico = logged_client_tecnico.get('/logout', follow_redirects=False)
    assert resp_tecnico.headers['location'] == '/login'
