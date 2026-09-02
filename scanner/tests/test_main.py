"""
Testes do servico HTTP do scanner (main.py) - preparar_execucao/rodar_execucao
e solicitar_cancelamento sao mockados aqui (a logica deles ja e' coberta em
test_run.py e test_persistencia.py); o foco e' o contrato HTTP em si:
validacao de entrada, disparo em thread separada, cancelamento, e o proxy
de /organizacoes.
"""

from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}


@patch('main.requests.get')
def test_organizacoes_proxy(mock_get):
    mock_get.return_value.json.return_value = {'result': ['org1', 'org2']}
    mock_get.return_value.raise_for_status = lambda: None
    resp = client.post('/organizacoes', json={'base_url': 'https://ckan.example'})
    assert resp.status_code == 200
    assert resp.json() == {'organizacoes': ['org1', 'org2']}


@patch('main.requests.get')
def test_organizacoes_proxy_erro_vira_502(mock_get):
    mock_get.side_effect = requests.RequestException('timeout')
    resp = client.post('/organizacoes', json={'base_url': 'https://ckan.example'})
    assert resp.status_code == 502


@patch('main.threading.Thread')
@patch('main.preparar_execucao')
def test_iniciar_devolve_execucao_id_e_dispara_thread_sem_bloquear(mock_preparar, mock_thread):
    mock_preparar.return_value = (42, [{'recurso': 'r1'}])
    resp = client.post('/iniciar', json={
        'base_url': 'https://ckan.example', 'engine_url': 'http://pii-engine:8000',
        'executado_por': 'usuario_teste', 'ambiente': 'sintetico',
    })
    assert resp.status_code == 200
    assert resp.json() == {'execucao_id': 42, 'total_recursos': 1}
    mock_thread.assert_called_once()
    mock_thread.return_value.start.assert_called_once()


@patch('main.preparar_execucao')
def test_iniciar_erro_de_rede_vira_502(mock_preparar):
    mock_preparar.side_effect = requests.RequestException('ckan fora do ar')
    resp = client.post('/iniciar', json={
        'base_url': 'https://ckan.example', 'engine_url': 'http://pii-engine:8000',
        'executado_por': 'usuario_teste',
    })
    assert resp.status_code == 502


def test_iniciar_exige_campos_obrigatorios():
    resp = client.post('/iniciar', json={'base_url': 'https://ckan.example'})
    assert resp.status_code == 422  # engine_url e executado_por faltando


@patch('main.solicitar_cancelamento')
def test_cancelar_chama_persistencia_com_o_id_certo(mock_solicitar):
    resp = client.post('/cancelar/42')
    assert resp.status_code == 200
    assert resp.json() == {'ok': True}
    mock_solicitar.assert_called_once_with(42)
