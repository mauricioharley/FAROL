"""
Testes da Camada 1 (heuristica de nome de coluna + regex de valor).
"""

from app.core.camada1 import rodar_camada1


def test_cpf_reconhecido_por_nome_de_coluna():
    achados = rodar_camada1(['cpf'], {'cpf': ['111.222.333-44']})
    assert len(achados) == 1
    assert achados[0]['campo'] == 'cpf'
    assert achados[0]['camada'] == 1
    assert achados[0]['confianca'] >= 0.9  # severidade sensitive


def test_cpf_reconhecido_por_regex_de_valor_mesmo_com_nome_generico():
    achados = rodar_camada1(['coluna_1'], {'coluna_1': ['111.222.333-44']})
    campos_achados = [a['campo'] for a in achados]
    assert 'coluna_1' in campos_achados


def test_coluna_sem_pii_nao_gera_achado():
    achados = rodar_camada1(['quantidade'], {'quantidade': ['10', '20', '30']})
    assert achados == []


def test_nome_de_pessoa_e_severidade_personal_nao_sensitive():
    achados = rodar_camada1(['nome'], {'nome': ['Maria Teste da Silva']})
    assert len(achados) == 1
    # 'nome' e' personal (0.85), nao sensitive (0.95) - diferenca importa pro
    # limiar de bloquear (motor.py, _LIMIAR_BLOQUEAR = 0.9)
    assert achados[0]['confianca'] < 0.9
