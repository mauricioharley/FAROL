"""
Cria um banco Postgres descartavel (mesmo servidor do FAROL_DB_DSN real, so'
o nome do banco muda) antes de qualquer teste rodar, e apaga no final. Nunca
toca no banco `farol` de verdade - mesmo padrao de isolamento que
painel/tests/conftest.py ja usa.

Diferente do painel (que duplica o schema por nao ter persistencia.py no
mesmo PYTHONPATH), aqui o scanner importa e chama preparar_schema() direto -
mesma imagem, mesmo modulo, sem risco de o schema duplicado desalinhar do
real.
"""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg

_DSN_ORIGINAL = os.environ.get('FAROL_DB_DSN')
if not _DSN_ORIGINAL:
    raise RuntimeError(
        'FAROL_DB_DSN precisa estar no ambiente pra rodar os testes (mesmo .env do compose) - '
        'rode via: docker compose run --rm scanner ...'
    )

_partes = urlsplit(_DSN_ORIGINAL)
_dsn_admin = urlunsplit(_partes._replace(path='/postgres'))
_nome_db_teste = f'farol_test_{uuid.uuid4().hex[:8]}'
_dsn_teste = urlunsplit(_partes._replace(path=f'/{_nome_db_teste}'))

with psycopg.connect(_dsn_admin, autocommit=True) as _conn:
    _conn.execute(f'CREATE DATABASE {_nome_db_teste}')

os.environ['FAROL_DB_DSN'] = _dsn_teste

import persistencia  # noqa: E402 - so' depois de trocar FAROL_DB_DSN, o modulo le a env var na importacao

persistencia.preparar_schema()


def pytest_sessionfinish(session, exitstatus):
    with psycopg.connect(_dsn_admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS {_nome_db_teste} WITH (FORCE)')
