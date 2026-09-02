"""
Testes de run.py: a orquestracao do scan (preparar_execucao + rodar_execucao),
sobretudo o cancelamento no meio e o filtro incremental - os dois
comportamentos novos pedidos explicitamente pelo Mauricio. Rede (listar_recursos,
requests.post pro pii-engine) e' mockada; persistencia usa o Postgres
descartavel real de conftest.py.
"""

import os
from unittest.mock import MagicMock, patch

from persistencia import marcar_recurso_conhecido, solicitar_cancelamento
from run import preparar_execucao, rodar_execucao

# setdefault (nao atribuicao direta): rodando via `docker compose run`, o
# FAROL_INGEST_TOKEN real ja vem setado pelo compose (mesmo .env de
# producao) - setdefault devolve esse valor real em vez de sobrescreve-lo.
_TOKEN_VALIDO = os.environ.setdefault('FAROL_INGEST_TOKEN', 'token_teste_123')


def _recurso(org='org', dataset='ds', recurso='r1', modificado_em='2026-01-01'):
    return {
        'org': org, 'dataset': dataset, 'recurso': recurso, 'recurso_nome': recurso,
        'url': f'https://x.example/{recurso}.csv', 'modificado_em': modificado_em,
    }


def _resposta_scan(veredito='liberar', achados=None):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {'veredito': veredito, 'achados': achados or [], 'hash_arquivo': 'abc'}
    return resp


@patch('run.listar_recursos')
def test_preparar_execucao_modo_incremental_pula_recurso_ja_conhecido(mock_listar):
    r_conhecido = _recurso(recurso='r-conhecido', modificado_em='2026-01-01')
    r_novo = _recurso(recurso='r-novo', modificado_em='2026-01-01')
    mock_listar.return_value = [r_conhecido, r_novo]

    execucao_previa, _ = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=False,
    )
    marcar_recurso_conhecido('org', 'ds', 'r-conhecido', '2026-01-01', execucao_previa)

    _, recursos = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=True,
    )
    assert [r['recurso'] for r in recursos] == ['r-novo']


@patch('run.listar_recursos')
def test_preparar_execucao_sem_incremental_inclui_tudo_mesmo_ja_conhecido(mock_listar):
    r1 = _recurso(recurso='r1', modificado_em='2026-01-01')
    mock_listar.return_value = [r1]
    execucao_previa, _ = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=False,
    )
    marcar_recurso_conhecido('org', 'ds', 'r1', '2026-01-01', execucao_previa)

    _, recursos = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=False,
    )
    assert [r['recurso'] for r in recursos] == ['r1']


@patch('run.requests.post')
@patch('run.listar_recursos')
def test_rodar_execucao_para_quando_cancelamento_ja_pendente_antes_do_loop(mock_listar, mock_post):
    recursos = [_recurso(recurso='r1'), _recurso(recurso='r2'), _recurso(recurso='r3')]
    mock_listar.return_value = recursos
    mock_post.return_value = _resposta_scan()

    execucao_id, recursos_preparados = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=False,
    )
    solicitar_cancelamento(execucao_id)

    rodar_execucao(execucao_id, recursos_preparados, 'http://pii-engine:8000', 'teste', 'sintetico', usar_disco=False)

    # o cancelamento ja estava pendente antes do loop comecar - nenhum
    # recurso deveria ter sido de fato enviado ao pii-engine.
    mock_post.assert_not_called()


@patch('run.requests.post')
@patch('run.listar_recursos')
def test_rodar_execucao_sem_cancelamento_processa_todos_os_recursos(mock_listar, mock_post):
    recursos = [_recurso(recurso='r1'), _recurso(recurso='r2')]
    mock_listar.return_value = recursos
    mock_post.return_value = _resposta_scan()

    execucao_id, recursos_preparados = preparar_execucao(
        'https://ckan.example', None, True, 'teste', None, None, 'sintetico', incremental=False,
    )
    rodar_execucao(execucao_id, recursos_preparados, 'http://pii-engine:8000', 'teste', 'sintetico', usar_disco=False)

    assert mock_post.call_count == 2
    # o pii-engine agora exige autenticacao maquina-a-maquina (mesmo token
    # ja usado pelo plugin) - sem isto toda chamada do scanner levaria 401.
    assert mock_post.call_args.kwargs['headers'] == {'X-Farol-Token': _TOKEN_VALIDO}
