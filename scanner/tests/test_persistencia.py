"""
Testes de persistencia.py contra um Postgres descartavel de verdade (ver
conftest.py) - nao mock de banco, pra a logica condicional de
recurso_mudou/deve_cancelar refletir o comportamento real do SQL, nao uma
suposicao sobre ele.
"""

from persistencia import (
    deve_cancelar,
    finalizar_execucao,
    iniciar_execucao,
    marcar_recurso_conhecido,
    recurso_mudou,
    solicitar_cancelamento,
)


def test_recurso_nunca_visto_e_sempre_mudou():
    assert recurso_mudou('org', 'ds', 'novo-recurso', '2026-01-01') is True


def test_recurso_sem_modificado_em_e_sempre_mudou():
    # Sem sinal confiavel de data, trata como mudado - mais seguro
    # reprocessar do que arriscar pular achado real por engano.
    assert recurso_mudou('org', 'ds', 'r-sem-data', None) is True


def test_recurso_marcado_com_mesma_data_nao_mudou():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    marcar_recurso_conhecido('org', 'ds', 'r1', '2026-01-01T00:00:00', execucao_id)
    assert recurso_mudou('org', 'ds', 'r1', '2026-01-01T00:00:00') is False


def test_recurso_marcado_com_data_diferente_mudou():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    marcar_recurso_conhecido('org', 'ds', 'r2', '2026-01-01T00:00:00', execucao_id)
    assert recurso_mudou('org', 'ds', 'r2', '2026-02-01T00:00:00') is True


def test_marcar_recurso_conhecido_e_upsert_idempotente():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    marcar_recurso_conhecido('org', 'ds', 'r3', '2026-01-01T00:00:00', execucao_id)
    marcar_recurso_conhecido('org', 'ds', 'r3', '2026-03-01T00:00:00', execucao_id)
    # a segunda chamada atualiza o registro (mesma PK), nao cria um segundo -
    # a data mais recente e' o que vale pra proxima comparacao.
    assert recurso_mudou('org', 'ds', 'r3', '2026-03-01T00:00:00') is False


def test_iniciar_execucao_aceita_formatos():
    execucao_id = iniciar_execucao(
        total_recursos=5, executado_por='teste', ambiente='sintetico', orgs='org1,org2', formatos='csv,xlsx',
    )
    assert execucao_id > 0


def test_cancelamento_nao_solicitado_por_padrao():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    assert deve_cancelar(execucao_id) is False


def test_solicitar_cancelamento_marca_flag():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    solicitar_cancelamento(execucao_id)
    assert deve_cancelar(execucao_id) is True


def test_finalizar_execucao_aceita_status_cancelado():
    execucao_id = iniciar_execucao(total_recursos=1, executado_por='teste', ambiente='sintetico', orgs=None)
    finalizar_execucao(execucao_id, status='cancelado')  # nao deve levantar
