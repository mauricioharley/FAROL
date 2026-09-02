"""
Testes do agregador de risco (motor.py). O ponto mais importante aqui e' o
teto de confianca da Camada 3 (_TETO_CONFIANCA_CAMADA3): um achado que vem
so' dela nunca pode, sozinho, levar o veredito a "bloquear" - o recall real
medido contra dado real ainda fica abaixo da meta de projeto.
"""

from app.core import motor


def test_agregar_vazio_libera():
    resultado = motor._agregar([])
    assert resultado == {'score_risco': 0, 'achados': [], 'veredito': 'liberar', 'motivo_nao_analisado': None}


def test_agregar_bloqueia_com_confianca_alta():
    achados = [{'campo': 'cpf', 'categoria': 'identificador', 'confianca': 0.95, 'camada': 1}]
    resultado = motor._agregar(achados)
    assert resultado['veredito'] == 'bloquear'
    assert resultado['score_risco'] == 95


def test_agregar_alerta_em_faixa_intermediaria():
    achados = [{'campo': 'x', 'categoria': 'y', 'confianca': 0.7, 'camada': 2}]
    resultado = motor._agregar(achados)
    assert resultado['veredito'] == 'alertar'


def test_agregar_libera_abaixo_do_limiar_de_alerta():
    achados = [{'campo': 'x', 'categoria': 'y', 'confianca': 0.3, 'camada': 2}]
    resultado = motor._agregar(achados)
    assert resultado['veredito'] == 'liberar'


def test_camada3_nunca_bloqueia_sozinha_mesmo_com_confianca_maxima(monkeypatch):
    monkeypatch.setattr(motor, 'rodar_camada1', lambda columns, sample_values=None: [])
    monkeypatch.setattr(motor, 'rodar_camada2', lambda campo, valores: [
        {'campo': campo, 'categoria': 'dado_saude_ou_vida_sexual', 'confianca': 0.7, 'camada': 2},
    ])
    monkeypatch.setattr(motor, 'rodar_camada3', lambda campo, valores: [
        {'campo': campo, 'categoria': 'dado_saude_ou_vida_sexual', 'confianca': 0.99, 'camada': 3, 'justificativa': 'teste'},
    ])

    resultado = motor.rodar_motor({'observacoes': ['algum texto']})

    achados_camada3 = [a for a in resultado['achados'] if a['camada'] == 3]
    assert achados_camada3
    assert all(a['confianca'] <= motor._TETO_CONFIANCA_CAMADA3 for a in achados_camada3)
    assert resultado['veredito'] == 'alertar'


def test_campo_resolvido_pela_camada1_nao_gasta_camada2_nem_3(monkeypatch):
    chamadas_camada2 = []
    monkeypatch.setattr(motor, 'rodar_camada2', lambda campo, valores: chamadas_camada2.append(campo) or [])
    monkeypatch.setattr(motor, 'rodar_camada3', lambda campo, valores: [])

    resultado = motor.rodar_motor({'cpf': ['111.222.333-44']})

    assert 'cpf' not in chamadas_camada2
    assert resultado['veredito'] == 'bloquear'
