"""
Prova que o proprio painel cria o schema no startup (lifespan), sem
depender do scanner ja ter rodado antes - regressao da corrida descrita em
docker-compose.yml (painel tem `depends_on: [farol-db, scanner]` sem
`condition`, entao numa subida limpa o container do scanner pode estar de
pe' sem ainda ter criado a tabela).

O banco usado aqui e' criado do zero, sem nenhuma DDL rodada nele (ao
contrario do banco de teste padrao, que o conftest.py ja prepara pra todos
os outros testes) - so' assim da pra provar que e' o lifespan do painel
(main._lifespan), e nao o conftest, quem esta criando a tabela.
"""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg
from fastapi.testclient import TestClient

import main

USUARIO = os.environ['FAROL_TECNICO_USER']
SENHA = os.environ['FAROL_TECNICO_PASSWORD']


def test_lifespan_cria_schema_em_banco_sem_tabela_nenhuma():
    partes = urlsplit(os.environ['FAROL_DB_DSN'])
    dsn_admin = urlunsplit(partes._replace(path='/postgres'))
    nome_db = f'farol_test_semschema_{uuid.uuid4().hex[:8]}'
    dsn_vazio = urlunsplit(partes._replace(path=f'/{nome_db}'))

    with psycopg.connect(dsn_admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE {nome_db}')

    dsn_original = main.DSN
    main.DSN = dsn_vazio
    try:
        # `with TestClient(...)` (nao so' instanciar) e' o que de fato dispara
        # o evento de startup do lifespan - e' isso que estamos testando aqui.
        with TestClient(main.app, base_url='https://testserver') as client:
            resp_login = client.post(
                '/login', data={'usuario': USUARIO, 'senha': SENHA, 'proximo': '/'}, follow_redirects=False,
            )
            assert resp_login.status_code == 303

            resp = client.get('/')
            assert resp.status_code == 200
    finally:
        main.DSN = dsn_original
        with psycopg.connect(dsn_admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS {nome_db} WITH (FORCE)')
