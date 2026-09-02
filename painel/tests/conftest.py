"""
Cria um banco Postgres descartavel (mesmo servidor do FAROL_DB_DSN real, so
o nome do banco muda) antes de qualquer teste rodar, e apaga no final. Nunca
toca no banco `farol` de verdade - isolamento por banco, nao por schema, pra
nao ter risco nenhum de mexer em achado real durante o teste.

FAROL_DB_DSN, FAROL_SESSION_SECRET etc precisam ser definidos aqui, no nivel
de modulo (nao dentro de uma fixture), porque `main.py` le essas variaveis
de ambiente na importacao do modulo - se a fixture rodasse depois do
primeiro `import main`, o RuntimeError de config ausente ja teria disparado.
"""

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

import psycopg

_DSN_ORIGINAL = os.environ.get('FAROL_DB_DSN')
if not _DSN_ORIGINAL:
    raise RuntimeError(
        'FAROL_DB_DSN precisa estar no ambiente pra rodar os testes (mesmo .env do compose) - '
        'rode via: docker compose run --rm painel ...'
    )

_partes = urlsplit(_DSN_ORIGINAL)
_dsn_admin = urlunsplit(_partes._replace(path='/postgres'))
_nome_db_teste = f'farol_test_{uuid.uuid4().hex[:8]}'
_dsn_teste = urlunsplit(_partes._replace(path=f'/{_nome_db_teste}'))

with psycopg.connect(_dsn_admin, autocommit=True) as _conn:
    _conn.execute(f'CREATE DATABASE {_nome_db_teste}')

os.environ['FAROL_DB_DSN'] = _dsn_teste
os.environ.setdefault('FAROL_SESSION_SECRET', 'segredo-de-teste-0123456789abcdef')
os.environ.setdefault('FAROL_TECNICO_USER', 'usuario_teste')
os.environ.setdefault('FAROL_TECNICO_PASSWORD', 'senha_teste_123')
os.environ.setdefault('FAROL_GERENCIAL_USER', 'usuario_gerencial_teste')
os.environ.setdefault('FAROL_GERENCIAL_PASSWORD', 'senha_gerencial_teste_123')
os.environ.setdefault('FAROL_INGEST_TOKEN', 'token_teste_123')

# Mesmo schema de scanner/persistencia.py - duplicado aqui de proposito: o
# painel e o scanner sao imagens/servicos separados (sem dependencia
# compartilhada entre eles no PYTHONPATH), e a tabela e' pequena o
# suficiente pra duplicar valer mais que acoplar os dois servicos so' pra
# teste.
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS achados (
    id SERIAL PRIMARY KEY,
    ambiente TEXT NOT NULL DEFAULT 'producao',
    org TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    recurso TEXT NOT NULL,
    recurso_nome TEXT,
    campo TEXT,
    categoria TEXT,
    confianca REAL,
    camada INT,
    veredito TEXT NOT NULL,
    motivo_nao_analisado TEXT,
    hash_arquivo TEXT,
    executado_por TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    revisao TEXT NOT NULL DEFAULT 'pendente',
    revisado_por TEXT,
    revisado_em TIMESTAMPTZ,
    justificativa TEXT
);

CREATE TABLE IF NOT EXISTS execucoes (
    id SERIAL PRIMARY KEY,
    iniciado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    finalizado_em TIMESTAMPTZ,
    total_recursos INT,
    processados INT NOT NULL DEFAULT 0,
    recurso_atual TEXT,
    status TEXT NOT NULL DEFAULT 'rodando',
    executado_por TEXT NOT NULL,
    ambiente TEXT NOT NULL,
    orgs TEXT,
    formatos TEXT,
    cancelar_solicitado BOOLEAN NOT NULL DEFAULT false
);
'''

with psycopg.connect(_dsn_teste) as _conn:
    _conn.execute(_SCHEMA)
    _conn.commit()


def pytest_sessionfinish(session, exitstatus):
    with psycopg.connect(_dsn_admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS {_nome_db_teste} WITH (FORCE)')
