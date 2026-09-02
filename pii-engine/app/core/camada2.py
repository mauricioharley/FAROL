"""
Camada 2: NER sobre colunas de texto livre que a Camada 1 não resolveu por
heurística de nome nem por regex de valor. Presidio + spaCy pt_core_news_lg
para entidades nomeadas (pessoa/local/organização) + um reconhecedor BR
customizado para menções categóricas de dado sensível (LGPD Art. 5º, II)
que não são entidades nomeadas - 'saúde mental' não é um nome próprio, é
uma categoria, e os reconhecedores padrão do Presidio não cobrem isso.
Sempre local (nunca uma API de LLM de terceiro). Nunca loga o texto bruto.
"""

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

_ENTIDADES = ['PERSON', 'LOCATION', 'ORGANIZATION', 'EMAIL_ADDRESS', 'PHONE_NUMBER', 'DADO_SAUDE', 'CPF_CNPJ']

_CATEGORIA_POR_ENTIDADE = {
    'PERSON': 'nome_pessoa',
    'LOCATION': 'endereco_local',
    'ORGANIZATION': 'organizacao',
    'EMAIL_ADDRESS': 'identificador',
    'PHONE_NUMBER': 'dado_pessoal',
    'DADO_SAUDE': 'dado_saude',
    'CPF_CNPJ': 'identificador',
}

# Lista curta, propositalmente conservadora - termos claros de
# condição/atendimento de saúde em português. Expandir com uso real.
_TERMOS_SAUDE = [
    'saude mental', 'saúde mental', 'transtorno bipolar', 'esquizofrenia',
    'depressao', 'depressão', 'ansiedade', 'hiv', 'aids', 'cancer', 'câncer',
    'diabetes', 'hipertensao', 'hipertensão', 'acompanhamento psiquiatrico',
    'acompanhamento psiquiátrico', 'uso de medicacao controlada',
    'uso de medicação controlada',
]

# CPF/CNPJ em texto livre (PDF/TXT/DOCX): a Camada 1 so cobre valor de
# celula tabular; sem isso, esses formatos nunca teriam CPF/CNPJ detectado.
_PADRAO_CPF = r'(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)'
_PADRAO_CNPJ = r'(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)'



def _recognizer_dado_saude() -> PatternRecognizer:
    padroes = [Pattern(name=f'saude_{i}', regex=f'(?i){termo}', score=0.85) for i, termo in enumerate(_TERMOS_SAUDE)]
    return PatternRecognizer(supported_entity='DADO_SAUDE', patterns=padroes, supported_language='pt')


def _recognizer_cpf_cnpj() -> PatternRecognizer:
    padroes = [
        Pattern(name='cpf', regex=_PADRAO_CPF, score=0.9),
        Pattern(name='cnpj', regex=_PADRAO_CNPJ, score=0.9),
    ]
    return PatternRecognizer(supported_entity='CPF_CNPJ', patterns=padroes, supported_language='pt')


_analyzer: AnalyzerEngine | None = None


def _get_analyzer() -> AnalyzerEngine:
    global _analyzer
    if _analyzer is None:
        configuracao = {
            'nlp_engine_name': 'spacy',
            'models': [{'lang_code': 'pt', 'model_name': 'pt_core_news_lg'}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuracao)
        analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=['pt'])
        analyzer.registry.add_recognizer(_recognizer_dado_saude())
        analyzer.registry.add_recognizer(_recognizer_cpf_cnpj())
        _analyzer = analyzer
    return _analyzer


def rodar_camada2(campo: str, valores: list[str]) -> list[dict]:
    """NER sobre uma coluna de texto livre. Achado agregado por campo (não
    por linha) - confianca é o maior score de cada tipo de entidade encontrado."""
    analyzer = _get_analyzer()
    melhor_por_entidade: dict[str, float] = {}
    for valor in valores:
        if not valor or not valor.strip():
            continue
        for r in analyzer.analyze(text=valor, language='pt', entities=_ENTIDADES):
            melhor_por_entidade[r.entity_type] = max(melhor_por_entidade.get(r.entity_type, 0.0), r.score)

    return [
        {
            'campo': campo,
            'categoria': _CATEGORIA_POR_ENTIDADE.get(entidade, entidade.lower()),
            'confianca': round(score, 2),
            'camada': 2,
        }
        for entidade, score in melhor_por_entidade.items()
    ]
