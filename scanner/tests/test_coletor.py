"""
Testes do coletor CKAN (coletor.py). A rede (requests) e' sempre mockada -
estes testes cobrem a montagem da lista de recursos, o filtro de
organizacao e o filtro de formato, nao a API real de nenhum portal.
"""

from unittest.mock import MagicMock, patch

from coletor import _extensao, caminho_no_disco, listar_recursos


def _resposta(resultado):
    resp = MagicMock()
    resp.json.return_value = {'result': resultado}
    return resp


@patch('coletor.requests.get')
def test_listar_recursos_monta_org_dataset_recurso(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps']),  # organization_list
        _resposta({'packages': [{'id': 'ds1'}]}),  # organization_show
        _resposta({  # package_show
            'name': 'dataset-1',
            'metadata_modified': '2026-01-01T00:00:00',
            'resources': [
                {'id': 'r1', 'name': 'Recurso 1', 'url': 'https://portal.example/r1.csv'},
            ],
        }),
    ]
    recursos = listar_recursos('https://portal.example')
    assert recursos == [{
        'org': 'ceps', 'dataset': 'dataset-1', 'recurso': 'r1',
        'recurso_nome': 'Recurso 1', 'url': 'https://portal.example/r1.csv',
        'modificado_em': '2026-01-01T00:00:00',
    }]


@patch('coletor.requests.get')
def test_listar_recursos_usa_nome_do_arquivo_quando_recurso_sem_nome(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps']),
        _resposta({'packages': [{'id': 'ds1'}]}),
        _resposta({
            'name': 'dataset-1',
            'resources': [{'id': 'r1', 'name': None, 'url': 'https://portal.example/arquivo.csv?x=1'}],
        }),
    ]
    recursos = listar_recursos('https://portal.example')
    assert recursos[0]['recurso_nome'] == 'arquivo.csv'


@patch('coletor.requests.get')
def test_listar_recursos_usa_last_modified_do_recurso_quando_existe(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps']),
        _resposta({'packages': [{'id': 'ds1'}]}),
        _resposta({
            'name': 'dataset-1',
            'metadata_modified': '2026-01-01T00:00:00',
            'resources': [{
                'id': 'r1', 'name': 'r1', 'url': 'https://portal.example/r1.csv',
                'last_modified': '2026-06-15T10:00:00',
            }],
        }),
    ]
    recursos = listar_recursos('https://portal.example')
    # last_modified do recurso tem prioridade sobre metadata_modified do dataset -
    # e' a granularidade mais fina disponivel.
    assert recursos[0]['modificado_em'] == '2026-06-15T10:00:00'


@patch('coletor.requests.get')
def test_listar_recursos_filtra_por_orgs(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps', 'ibge', 'capes']),  # organization_list (3 orgs)
        _resposta({'packages': []}),  # organization_show so' pra 'ibge' (unica no filtro)
    ]
    listar_recursos('https://portal.example', orgs_filtro=['ibge'])
    # so' uma chamada de organization_show, pra 'ibge' - as outras 2 orgs
    # foram filtradas antes de qualquer requisicao adicional
    chamadas_organization_show = [
        c for c in mock_get.call_args_list if 'organization_show' in c.args[0]
    ]
    assert len(chamadas_organization_show) == 1
    assert chamadas_organization_show[0].kwargs['params']['id'] == 'ibge'


@patch('coletor.requests.get')
def test_listar_recursos_filtra_por_formato(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps']),
        _resposta({'packages': [{'id': 'ds1'}]}),
        _resposta({
            'name': 'dataset-1',
            'resources': [
                {'id': 'r1', 'name': 'CSV', 'url': 'https://portal.example/dados.csv'},
                {'id': 'r2', 'name': 'PDF', 'url': 'https://portal.example/relatorio.pdf'},
                {'id': 'r3', 'name': 'sem extensao', 'url': 'https://portal.example/download'},
            ],
        }),
    ]
    recursos = listar_recursos('https://portal.example', formatos_filtro=['csv'])
    # so' o CSV entra - o PDF e' excluido pelo filtro, e o recurso sem
    # extensao reconhecivel tambem, porque com filtro ativo nao ha sinal
    # confiavel de que ele bate com o formato pedido.
    assert [r['recurso'] for r in recursos] == ['r1']


@patch('coletor.requests.get')
def test_listar_recursos_sem_filtro_de_formato_inclui_tudo(mock_get):
    mock_get.side_effect = [
        _resposta(['ceps']),
        _resposta({'packages': [{'id': 'ds1'}]}),
        _resposta({
            'name': 'dataset-1',
            'resources': [
                {'id': 'r1', 'name': 'CSV', 'url': 'https://portal.example/dados.csv'},
                {'id': 'r2', 'name': 'sem extensao', 'url': 'https://portal.example/download'},
            ],
        }),
    ]
    recursos = listar_recursos('https://portal.example')
    assert [r['recurso'] for r in recursos] == ['r1', 'r2']


@patch('coletor.requests.get')
def test_listar_recursos_envia_verify_e_api_key(mock_get):
    mock_get.side_effect = [_resposta([])]
    listar_recursos('https://portal.example', api_key='minha-chave', verify=False)
    _, kwargs = mock_get.call_args
    assert kwargs['verify'] is False
    assert kwargs['headers'] == {'Authorization': 'minha-chave'}


def test_extensao():
    assert _extensao('https://x.example/dados.CSV') == 'csv'
    assert _extensao('https://x.example/dados.csv?v=2') == 'csv'
    assert _extensao('https://x.example/download') == ''


def test_caminho_no_disco_sharding():
    caminho = caminho_no_disco('abcdef1234567890', base='/mnt/ckan/storage/resources')
    assert str(caminho) == '/mnt/ckan/storage/resources/abc/def/1234567890'
