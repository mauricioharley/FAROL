"""
Persistencia dos achados. Nunca grava o valor bruto de PII, so campo,
categoria, confianca, camada, justificativa (frase curta e generica da
Camada 3, nunca o trecho original), veredito, hash do arquivo e a trilha
de quem/quando/onde rodou.
"""

import os

import psycopg

DSN = os.environ.get('FAROL_DB_DSN')
if not DSN:
    raise RuntimeError('FAROL_DB_DSN nao configurado')

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
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE achados ADD COLUMN IF NOT EXISTS hash_arquivo TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS recurso_nome TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS ambiente TEXT NOT NULL DEFAULT 'producao';
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisao TEXT NOT NULL DEFAULT 'pendente';
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisado_por TEXT;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS revisado_em TIMESTAMPTZ;
ALTER TABLE achados ADD COLUMN IF NOT EXISTS justificativa TEXT;

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
    orgs TEXT
);
ALTER TABLE execucoes ADD COLUMN IF NOT EXISTS formatos TEXT;
-- Pedido de cancelamento vindo do painel (POST /cancelar/{id} no scanner) -
-- a propria execucao roda numa thread do servico, entao o jeito seguro de
-- pedir "para" de fora e' um sinal no banco, checado entre um recurso e
-- outro (nunca no meio de uma chamada ao pii-engine ja em andamento).
ALTER TABLE execucoes ADD COLUMN IF NOT EXISTS cancelar_solicitado BOOLEAN NOT NULL DEFAULT false;

-- Metadado de "ultima vez visto" por recurso, usado so' pelo modo
-- incremental (persistencia.recurso_mudou): um novo scan incremental
-- contra o mesmo CKAN inclui so' recurso novo ou com modificado_em
-- diferente do que ja foi registrado aqui - nunca substitui achados, so'
-- decide o que precisa ser reprocessado.
CREATE TABLE IF NOT EXISTS recursos_conhecidos (
    org TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    recurso TEXT NOT NULL,
    modificado_em TEXT,
    ultima_execucao_id INT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org, dataset_id, recurso)
);
'''


def preparar_schema() -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(_SCHEMA)


def gravar_resultado(
    org: str,
    dataset_id: str,
    recurso: str,
    recurso_nome: str,
    resultado: dict,
    executado_por: str,
    ambiente: str,
) -> None:
    achados = resultado.get('achados') or []
    hash_arquivo = resultado.get('hash_arquivo')
    with psycopg.connect(DSN) as conn:
        if not achados:
            conn.execute(
                '''INSERT INTO achados
                   (ambiente, org, dataset_id, recurso, recurso_nome, veredito, motivo_nao_analisado, hash_arquivo, executado_por)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (ambiente, org, dataset_id, recurso, recurso_nome, resultado['veredito'],
                 resultado.get('motivo_nao_analisado'), hash_arquivo, executado_por),
            )
        else:
            for a in achados:
                conn.execute(
                    '''INSERT INTO achados
                       (ambiente, org, dataset_id, recurso, recurso_nome, campo, categoria, confianca, camada, justificativa, veredito, hash_arquivo, executado_por)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (ambiente, org, dataset_id, recurso, recurso_nome, a['campo'], a['categoria'], a['confianca'],
                     a['camada'], a.get('justificativa'), resultado['veredito'], hash_arquivo, executado_por),
                )
        conn.commit()


def iniciar_execucao(
    total_recursos: int, executado_por: str, ambiente: str, orgs: str | None, formatos: str | None = None,
) -> int:
    with psycopg.connect(DSN) as conn:
        cur = conn.execute(
            'INSERT INTO execucoes (total_recursos, executado_por, ambiente, orgs, formatos) '
            'VALUES (%s,%s,%s,%s,%s) RETURNING id',
            (total_recursos, executado_por, ambiente, orgs, formatos),
        )
        execucao_id = cur.fetchone()[0]
        conn.commit()
    return execucao_id


def atualizar_progresso(execucao_id: int, processados: int, recurso_atual: str | None) -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(
            'UPDATE execucoes SET processados = %s, recurso_atual = %s WHERE id = %s',
            (processados, recurso_atual, execucao_id),
        )
        conn.commit()


def finalizar_execucao(execucao_id: int, status: str = 'concluido') -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(
            'UPDATE execucoes SET status = %s, finalizado_em = now(), recurso_atual = NULL WHERE id = %s',
            (status, execucao_id),
        )
        conn.commit()


def solicitar_cancelamento(execucao_id: int) -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute('UPDATE execucoes SET cancelar_solicitado = true WHERE id = %s', (execucao_id,))
        conn.commit()


def deve_cancelar(execucao_id: int) -> bool:
    with psycopg.connect(DSN) as conn:
        linha = conn.execute(
            'SELECT cancelar_solicitado FROM execucoes WHERE id = %s', (execucao_id,)
        ).fetchone()
    return bool(linha and linha[0])


def recurso_mudou(org: str, dataset_id: str, recurso: str, modificado_em: str | None) -> bool:
    """True se o recurso e' novo ou seu metadado de modificacao mudou desde
    a ultima vez que foi escaneado - usado pelo modo incremental pra decidir
    o que entra num novo scan. Recurso sem 'modificado_em' (o CKAN alvo nao
    devolveu essa informacao) e' sempre tratado como mudado: sem sinal
    confiavel, reprocessar de novo e' mais seguro do que arriscar pular um
    achado real por engano.
    """
    if not modificado_em:
        return True
    with psycopg.connect(DSN) as conn:
        linha = conn.execute(
            'SELECT modificado_em FROM recursos_conhecidos WHERE org = %s AND dataset_id = %s AND recurso = %s',
            (org, dataset_id, recurso),
        ).fetchone()
    return linha is None or linha[0] != modificado_em


def marcar_recurso_conhecido(
    org: str, dataset_id: str, recurso: str, modificado_em: str | None, execucao_id: int,
) -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(
            '''INSERT INTO recursos_conhecidos (org, dataset_id, recurso, modificado_em, ultima_execucao_id, atualizado_em)
               VALUES (%s,%s,%s,%s,%s, now())
               ON CONFLICT (org, dataset_id, recurso)
               DO UPDATE SET modificado_em = EXCLUDED.modificado_em,
                              ultima_execucao_id = EXCLUDED.ultima_execucao_id,
                              atualizado_em = now()''',
            (org, dataset_id, recurso, modificado_em, execucao_id),
        )
        conn.commit()
