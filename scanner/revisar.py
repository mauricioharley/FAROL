"""
Marca o status de revisao humana de um achado. Uso:
  docker compose run --rm scanner python revisar.py <id> confirmado_positivo seu-nome
  docker compose run --rm scanner python revisar.py <id> falso_positivo seu-nome

So atualiza status/quem/quando -- nunca le nem grava valor bruto, so o id do
achado ja existente.
"""

import sys

import psycopg

from persistencia import DSN

_STATUS_VALIDOS = {'pendente', 'confirmado_positivo', 'falso_positivo'}


def marcar_revisao(achado_id: int, status: str, revisor: str) -> None:
    if status not in _STATUS_VALIDOS:
        raise ValueError(f'status invalido: {status}. Use um de {_STATUS_VALIDOS}')
    with psycopg.connect(DSN) as conn:
        conn.execute(
            'UPDATE achados SET revisao = %s, revisado_por = %s, revisado_em = now() WHERE id = %s',
            (status, revisor, achado_id),
        )
        conn.commit()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('uso: python revisar.py <id> <pendente|confirmado_positivo|falso_positivo> <revisor>')
        sys.exit(1)
    marcar_revisao(int(sys.argv[1]), sys.argv[2], sys.argv[3])
    print('ok')
