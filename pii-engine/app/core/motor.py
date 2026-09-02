"""
Agregador de risco: combina achados das camadas 1, 2 e 3 num veredito
único. Nunca grava o valor bruto - só os achados estruturados
(campo/categoria/confianca/camada[/justificativa]).
"""

from app.core.camada1 import rodar_camada1
from app.core.camada2 import rodar_camada2
from app.core.camada3 import rodar_camada3

_LIMIAR_BLOQUEAR = 0.9
_LIMIAR_ALERTAR = 0.6

# Medido contra dado real: em texto burocratico real (edital, lei,
# dicionario de dados), a Camada 3 erra bastante - inclusive com
# confianca alta em falso positivo (ex.: "religioso" numa isencao de IPTU
# virando convicao_religiosa com confianca >= 0.9). Ela ainda nao acumulou
# evidencia suficiente pra decidir "bloquear" sozinha: o teto abaixo garante
# que um achado so' da Camada 3 no maximo vira "alertar" (fila de revisao
# humana) - quem decide "bloquear" sozinho continua sendo Camada 1/2
# (regex/NER), ja validadas em producao.
_TETO_CONFIANCA_CAMADA3 = _LIMIAR_BLOQUEAR - 0.01


def rodar_motor(campos: dict[str, list[str]]) -> dict:
    achados_camada1 = rodar_camada1(list(campos.keys()), campos)
    campos_resolvidos = {a['campo'] for a in achados_camada1}

    achados_camada2: list[dict] = []
    achados_camada3: list[dict] = []
    for campo, valores in campos.items():
        if campo in campos_resolvidos:
            continue
        achados_do_campo = rodar_camada2(campo, valores)
        achados_camada2.extend(achados_do_campo)
        if achados_do_campo:
            # Camada 3 só roda sobre o que a Camada 2 já sinalizou (custo)
            # - refina a categoria exata do Art. 5º, II a partir do sentido
            # do texto, algo que NER/regex não cobrem.
            achados_camada3.extend(rodar_camada3(campo, valores))

    for achado in achados_camada3:
        achado['confianca'] = min(achado['confianca'], _TETO_CONFIANCA_CAMADA3)

    return _agregar(achados_camada1 + achados_camada2 + achados_camada3)


def _agregar(achados: list[dict]) -> dict:
    if not achados:
        return {'score_risco': 0, 'achados': [], 'veredito': 'liberar', 'motivo_nao_analisado': None}

    maior_confianca = max(a['confianca'] for a in achados)
    if maior_confianca >= _LIMIAR_BLOQUEAR:
        veredito = 'bloquear'
    elif maior_confianca >= _LIMIAR_ALERTAR:
        veredito = 'alertar'
    else:
        veredito = 'liberar'

    return {
        'score_risco': round(maior_confianca * 100),
        'achados': achados,
        'veredito': veredito,
        'motivo_nao_analisado': None,
    }
