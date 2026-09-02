"""
Testes do endpoint HTTP (main.py). O download real (`_baixar_com_prazo_total`)
e' sempre mockado aqui - estes testes cobrem o contrato do endpoint e a
degradacao graciosa em erro, nao a rede de verdade. Os testes do teto de
tamanho no fim do arquivo mockam so' `requests.get`, testando
`_baixar_com_prazo_total` diretamente (a logica de streaming vive so' ali).
"""

import os
from unittest.mock import MagicMock

import pytest
import requests
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import _baixar_com_prazo_total, app, _verify_para

# setdefault (nao atribuicao direta): rodando via `docker compose run`, o
# FAROL_INGEST_TOKEN real ja vem setado pelo compose (mesmo .env de
# producao) - setdefault devolve esse valor real em vez de sobrescreve-lo,
# entao o header de teste sempre bate com o que a dependencia vai comparar.
_TOKEN_VALIDO = os.environ.setdefault('FAROL_INGEST_TOKEN', 'token_teste_123')

client = TestClient(app)
_HEADERS = {'X-Farol-Token': _TOKEN_VALIDO}


def test_health():
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok'}


def test_scan_sem_token_e_negado():
    resp = client.post('/v1/scan', json={'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv'})
    assert resp.status_code == 422  # Header(...) obrigatorio, ausente


def test_scan_com_token_errado_e_negado():
    resp = client.post(
        '/v1/scan',
        json={'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv'},
        headers={'X-Farol-Token': _TOKEN_VALIDO + '-errado'},
    )
    assert resp.status_code == 401


def test_scan_com_token_correto_processa_normalmente(monkeypatch):
    monkeypatch.setattr(
        main_module, '_baixar_com_prazo_total',
        lambda url: (b'quantidade\n10\n20\n', 'text/csv'),
    )
    resp = client.post(
        '/v1/scan',
        json={'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv', 'nome_arquivo': 'dados.csv'},
        headers=_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()['veredito'] == 'liberar'


def test_scan_com_pii_bloqueia(monkeypatch):
    monkeypatch.setattr(
        main_module, '_baixar_com_prazo_total',
        lambda url: (b'nome,cpf\nMaria,111.222.333-44\n', 'text/csv'),
    )
    resp = client.post('/v1/scan', json={
        'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv', 'nome_arquivo': 'dados.csv',
    }, headers=_HEADERS)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo['veredito'] == 'bloquear'
    assert corpo['hash_arquivo']
    assert corpo['dataset_id'] == 'teste'


def test_scan_sem_pii_libera(monkeypatch):
    monkeypatch.setattr(
        main_module, '_baixar_com_prazo_total',
        lambda url: (b'quantidade\n10\n20\n', 'text/csv'),
    )
    resp = client.post('/v1/scan', json={
        'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv', 'nome_arquivo': 'dados.csv',
    }, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()['veredito'] == 'liberar'


def test_scan_erro_download_vira_nao_analisado_gracioso(monkeypatch):
    def _levanta(url):
        raise requests.exceptions.ConnectionError('conexao recusada')

    monkeypatch.setattr(main_module, '_baixar_com_prazo_total', _levanta)
    resp = client.post(
        '/v1/scan', json={'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.csv'}, headers=_HEADERS,
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo['veredito'] == 'nao_analisado'
    assert corpo['motivo_nao_analisado'].startswith('erro_download')
    assert corpo['hash_arquivo'] is None


def test_scan_formato_nao_suportado_vira_nao_analisado(monkeypatch):
    monkeypatch.setattr(
        main_module, '_baixar_com_prazo_total',
        lambda url: (b'qualquer coisa', 'application/octet-stream'),
    )
    resp = client.post('/v1/scan', json={
        'dataset_id': 'teste', 'recurso_url': 'https://exemplo.org/dados.parquet', 'nome_arquivo': 'dados.parquet',
    }, headers=_HEADERS)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo['veredito'] == 'nao_analisado'
    assert corpo['motivo_nao_analisado'] == 'formato_nao_suportado'


def test_scan_sem_url_nem_caminho_local_e_invalido():
    resp = client.post('/v1/scan', json={'dataset_id': 'teste'}, headers=_HEADERS)
    assert resp.status_code == 422


def test_verify_para_padrao_seguro(monkeypatch):
    monkeypatch.setattr(main_module, '_VERIFY_TLS', True)
    monkeypatch.setattr(main_module, '_HOSTS_TLS_INSEGURO', set())
    assert _verify_para('https://dados.gov.br/recurso.csv') is True


def test_verify_para_excecao_so_vale_para_o_host_configurado(monkeypatch):
    monkeypatch.setattr(main_module, '_VERIFY_TLS', True)
    monkeypatch.setattr(main_module, '_HOSTS_TLS_INSEGURO', {'ckan-teste.local'})
    assert _verify_para('https://ckan-teste.local:8444/recurso.csv') is False
    assert _verify_para('https://dados.gov.br/recurso.csv') is True


def test_verify_para_desligado_globalmente(monkeypatch):
    monkeypatch.setattr(main_module, '_VERIFY_TLS', False)
    assert _verify_para('https://qualquer-host.example/recurso.csv') is False


def _resposta_streaming(headers: dict, blocos: list[bytes]):
    resposta = MagicMock()
    resposta.raise_for_status = MagicMock()
    resposta.headers = headers
    resposta.iter_content = MagicMock(return_value=iter(blocos))
    contexto = MagicMock()
    contexto.__enter__ = MagicMock(return_value=resposta)
    contexto.__exit__ = MagicMock(return_value=False)
    return contexto, resposta


def test_baixar_rejeita_pelo_content_length_sem_baixar_nada(monkeypatch):
    monkeypatch.setattr(main_module, '_TAMANHO_MAXIMO_DOWNLOAD', 100)
    contexto, resposta = _resposta_streaming({'content-length': '999999'}, [b'nunca deveria ler isto'])
    monkeypatch.setattr(main_module.requests, 'get', MagicMock(return_value=contexto))

    with pytest.raises(requests.RequestException, match='999999'):
        _baixar_com_prazo_total('https://exemplo.org/gigante.csv')
    # rejeitado so' pelo cabecalho declarado - o corpo nunca chegou a ser lido
    resposta.iter_content.assert_not_called()


def test_baixar_aborta_durante_streaming_sem_content_length_confiavel(monkeypatch):
    monkeypatch.setattr(main_module, '_TAMANHO_MAXIMO_DOWNLOAD', 10)
    # sem content-length (comum em resposta chunked/streamed de verdade) -
    # o unico jeito de pegar isso e' contando durante o streaming mesmo.
    blocos = [b'0123456789', b'mais dez bytes aqui']
    contexto, _ = _resposta_streaming({}, blocos)
    monkeypatch.setattr(main_module.requests, 'get', MagicMock(return_value=contexto))

    with pytest.raises(requests.RequestException, match='limite'):
        _baixar_com_prazo_total('https://exemplo.org/sem-tamanho-declarado.csv')


def test_baixar_aceita_arquivo_dentro_do_limite(monkeypatch):
    monkeypatch.setattr(main_module, '_TAMANHO_MAXIMO_DOWNLOAD', 1000)
    contexto, _ = _resposta_streaming({'content-type': 'text/csv'}, [b'nome,email\n', b'Maria,x@x.com\n'])
    monkeypatch.setattr(main_module.requests, 'get', MagicMock(return_value=contexto))

    conteudo, content_type = _baixar_com_prazo_total('https://exemplo.org/pequeno.csv')
    assert conteudo == b'nome,email\nMaria,x@x.com\n'
    assert content_type == 'text/csv'
