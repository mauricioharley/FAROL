"""
Camada 1 do FAROL: adapta detect_fields() (pii_detector.py) para o
formato de achado do FAROL (campo/categoria/confianca/camada), sem
alterar o modulo original.
"""

from app.core.pii_detector import detect_fields
from app.models.schemas import DataCategory, PiiSeverity

_CONFIANCA_POR_SEVERIDADE = {
    PiiSeverity.sensitive: 0.95,
    PiiSeverity.personal: 0.85,
}

# DataCategory (definido em app.models.schemas) agrupa por tecnica de
# anonimizacao compativel, nao por rotulo voltado a quem le o painel;
# traduzido aqui.
_CATEGORIA_PT = {
    DataCategory.identifier: 'identificador',
    DataCategory.categorical: 'dado_pessoal',
    DataCategory.secret: 'credencial',
    DataCategory.date: 'data',
    DataCategory.numeric: 'dado_numerico',
    DataCategory.geo: 'geolocalizacao',
}


def rodar_camada1(
    columns: list[str],
    sample_values: dict[str, list[str]] | None = None,
) -> list[dict]:
    achados = []
    for field in detect_fields(columns, sample_values):
        if field.severity == PiiSeverity.public or field.category is None:
            continue
        achados.append(
            {
                'campo': field.name,
                'categoria': _CATEGORIA_PT.get(field.category, field.category.value),
                'confianca': _CONFIANCA_POR_SEVERIDADE.get(field.severity, 0.8),
                'camada': 1,
            }
        )
    return achados
