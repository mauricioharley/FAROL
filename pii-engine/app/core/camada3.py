"""
Camada 3: classificador LLM local (Qwen3-4B via llama.cpp, servico `llm`
do compose do FAROL). So' entra em campo sobre campos que a Camada 2 ja
sinalizou - nunca sobre o catalogo inteiro, para controlar custo. Cobre um
gap real da Camada 2: NER e regex nao distinguem "opiniao politica" de
"filiacao sindical" nem pegam "origem racial/etnica" ou "dado genetico" -
sao categorias do Art. 5o, II da LGPD que só dá pra reconhecer lendo o
sentido do texto, nao so' o formato.

Sempre local (llama.cpp no proprio host, nunca API de LLM de terceiro,
mesmo principio das Camadas 1 e 2). Retorna so' a classificacao
estruturada (categoria/confianca/justificativa curta e generica) - nunca
o valor original, nunca loga o trecho enviado.

Falha aberta: se o `llm` estiver indisponivel ou responder algo
inutilizavel, retorna [] e quem agrega mantem so' o veredito da Camada 2 -
Camada 3 so' pode reforcar ou refinar categoria, nunca é o unico motivo
de um "liberar" sobre algo que a Camada 2 ja tinha sinalizado.

Prompt usa few-shot com exemplo REAL: testar contra mais de mil recursos
reais mostrou que trocar de modelo (4B->8B) nao corrigia o problema - o
gargalo era o prompt nunca ter mostrado exemplo de texto burocratico
real (edital, lei, dicionario de dados) que contem a palavra-gatilho sem
ser dado pessoal.
"""

import json
import logging
import os

import requests
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

_LLM_URL = os.environ.get('FAROL_LLM_URL', 'http://llm:8080').rstrip('/')
_LLM_MODEL = os.environ.get('FAROL_LLM_MODEL', 'qwen3-4b')
_LLM_TIMEOUT_SECONDS = float(os.environ.get('FAROL_LLM_TIMEOUT_SECONDS', '60'))

_MAX_AMOSTRAS = 5
_MAX_CHARS_POR_VALOR = 200

# Art. 5o, II da LGPD (dado pessoal sensivel) + duas categorias de saida
# que nao sao do inciso II, mas fecham o conjunto de resposta do LLM.
_CATEGORIA_DESCRICAO = {
    'origem_racial_etnica': 'origem racial ou étnica',
    'convicao_religiosa': 'convicção religiosa',
    'opiniao_politica': 'opinião política',
    'filiacao_sindical_ou_organizacao': 'filiação a sindicato ou organização de caráter religioso, filosófico ou político',
    'dado_saude_ou_vida_sexual': 'dado referente à saúde ou à vida sexual',
    'dado_genetico_ou_biometrico': 'dado genético ou biométrico',
    'dado_pessoal_comum': 'dado pessoal comum (identifica alguém, mas não é sensível pelo Art. 5º, II)',
    'nenhum': 'não é dado pessoal',
}
_CATEGORIAS_VALIDAS = set(_CATEGORIA_DESCRICAO)


class _ClassificacaoLLM(BaseModel):
    categoria_lgpd: str
    confianca: float
    justificativa: str


def _prompt_sistema() -> str:
    lista = '\n'.join(f'- {chave}: {desc}' for chave, desc in _CATEGORIA_DESCRICAO.items())
    return f"""Você é um classificador de dados pessoais conforme a LGPD (Lei 13.709/2018), Art. 5º, incisos I e II.
Você recebe o nome de uma coluna e uma amostra de valores (de uma planilha ou documento de um portal de dados abertos) já sinalizados por um filtro anterior como possível dado pessoal. Sua tarefa é decidir a categoria mais precisa, entre EXATAMENTE estas opções:
{lista}

Regras:
1. Responda somente com um objeto JSON válido, sem markdown, sem texto antes ou depois.
2. "categoria_lgpd" deve ser exatamente uma das chaves acima, sem inventar outra.
3. "confianca" é um número entre 0.0 e 1.0.
4. "justificativa" deve ser uma frase curta e genérica sobre o TIPO de conteúdo (ex.: "menciona filiação partidária"), nunca repetir nem citar os valores originais recebidos.
5. Falso negativo é pior que falso positivo aqui: havendo dúvida real entre uma categoria sensível e "dado_pessoal_comum", prefira a categoria sensível com confiança moderada em vez de descartar.
6. Decida pelo CONTEÚDO real da amostra de valores, nunca só pelo nome da coluna. Um nome de coluna como "origem" ou "executor" não significa origem étnica nem filiação só porque a palavra lembra a categoria - sigla de órgão público (ex.: "PMF", "HABITAFOR", "ESTADO") não é filiação sindical nem política.""".strip()


def _prompt_usuario(campo: str, valores: list[str], *, com_instrucao: bool = True) -> str:
    amostras = [v.strip()[:_MAX_CHARS_POR_VALOR] for v in valores if v and v.strip()][:_MAX_AMOSTRAS]
    amostras_fmt = '\n'.join(f'- {a}' for a in amostras) or '(sem amostra disponível)'
    texto = f'Nome da coluna: {campo}\nAmostra de valores:\n{amostras_fmt}'
    if com_instrucao:
        texto = '/no_think\n' + texto + (
            '\n\nResponda com um único objeto JSON, com as chaves categoria_lgpd, confianca e justificativa.'
        )
    return texto


# Few-shot com falso positivo/negativo REAL encontrado numa varredura
# ampla sobre um catalogo real - o problema medido nao era falta de
# capacidade do modelo, era o prompt nunca ter mostrado
# exemplo de texto burocratico real (edital, lei, dicionario de dados) que
# contem a palavra-gatilho sem ser dado pessoal. As duas ultimas amostras
# (positivas) evitam que os negativos empurrem o modelo a suprimir demais
# e piorar o recall que ja era o ponto fraco.
_EXEMPLOS_POUCOS_DISPAROS: list[tuple[str, list[str], dict]] = [
    ('TIPO_BENEFICIO', ['Imóvel Cedido a Templo Religioso'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'categoria de beneficio fiscal sobre um imovel, nao dado de pessoa'}),
    ('uso_solo', ['religioso'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'categoria de uso do solo urbano (zoneamento), nao pessoa'}),
    ('OBJETO DO PROCESSO', ['Registro de precos para aquisicao de teste rapido de gravidez (HCG) para atender a demanda da secretaria de saude'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'objeto de compra publica de insumo de saude, nao dado de gestante identificada'}),
    ('OBJETO DO PROCESSO', ['Busca de uma cultura que garanta o respeito as diferencas, sem preconceitos de raca, cor, crenca, religiao, etarismo e orientacao sexual'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'clausula de nao-discriminacao em edital, nao descreve pessoa especifica'}),
    ('Obs Fiscal', ['Descarte irregular de entulho causando transtorno aos moradores do local'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.85,
      'justificativa': 'transtorno no sentido de incomodo/inconveniente, nao termo medico'}),
    ('texto_extraido', ['RACACOR C(01) Raca/Cor: 1-Branca 2-Preta 3-Amarela 4-Parda 5-Indigena'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'dicionario de dados/legenda de codificacao de arquivo, nao registro real de pessoa'}),
    ('FORNECEDORES / PARTICIPANTES', ['Associacao Nossa Casa de Apoio a Pessoas com Cancer'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'nome de pessoa juridica (ONG/fornecedor), nao paciente identificado'}),
    ('ocorrências', ['Afastamento conforme portaria, CID F339 transtorno depressivo recorrente sem especificacao, processo P276335/2022'],
     {'categoria_lgpd': 'dado_saude_ou_vida_sexual', 'confianca': 0.85,
      'justificativa': 'registro individual de afastamento com codigo de diagnostico medico (CID)'}),
    ('ocorrências', ['Afastamento para o sindicato, conforme ato 3843/2021'],
     {'categoria_lgpd': 'filiacao_sindical_ou_organizacao', 'confianca': 0.85,
      'justificativa': 'registro individual de afastamento para atividade sindical'}),

    # Segunda rodada de exemplos (medida contra conjunto sintetico adversarial dedicado,
    # nao contra o catalogo real - ver pii-engine/eval/). Confirma dois padroes que a
    # primeira rodada nao cobria: confusao entre opiniao_politica e filiacao_sindical
    # quando o texto fala de campanha/partido em vez de sindicato, e falso positivo de
    # dado_genetico_ou_biometrico sobre descricao institucional de sistema/servico (essa
    # categoria nao tinha nenhum negativo no few-shot ate aqui).
    ('situacao_funcional', ['Servidor fez campanha para candidato a vereador durante o expediente, distribuindo material de propaganda partidaria no local de trabalho'],
     {'categoria_lgpd': 'opiniao_politica', 'confianca': 0.85,
      'justificativa': 'manifestacao de apoio a candidato/partido, distinto de atividade sindical'}),
    ('ata_reuniao', ['Membro do conselho declarou publicamente apoio a candidatura do prefeito a reeleicao durante sessao plenaria, registrado em ata'],
     {'categoria_lgpd': 'opiniao_politica', 'confianca': 0.8,
      'justificativa': 'manifestacao publica de posicionamento politico-partidario de pessoa identificada em ata'}),
    ('nome_comissao', ['Comissao Eleitoral Municipal, responsavel por fiscalizar propaganda politica no periodo de campanha'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'nome de orgao/comissao institucional que trata de tema politico, nao e opiniao de pessoa identificada'}),
    ('objeto_processo', ['Registro de precos para aquisicao de kit de teste rapido de HIV para atender as unidades basicas de saude do municipio'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'aquisicao institucional de insumo de saude publica, mesmo padrao do teste de gravidez, nao descreve paciente identificado'}),
    ('descricao_sistema', ['Sistema de ponto eletronico do predio administrativo central utiliza leitor biometrico de digital para todos os servidores'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'descreve o sistema/equipamento em uso, nao o dado biometrico de uma pessoa especifica'}),
    ('objeto_licitacao', ['Contratacao de empresa para realizacao de exame de DNA em processo de identificacao de restos mortais nao identificados no cemiterio municipal'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'contratacao institucional de servico pericial, nao e dado genetico de pessoa ja identificada'}),
    ('criterio_edital', ['Reserva de 20% das vagas do certame para candidatos negros e pardos, conforme Lei federal de cotas raciais em concursos publicos'],
     {'categoria_lgpd': 'nenhum', 'confianca': 0.9,
      'justificativa': 'clausula de politica de cotas em edital, mesmo padrao do exemplo de uso do solo, nao descreve pessoa especifica'}),
    ('parecer_tecnico', ['Familia autodeclarada quilombola solicitou inclusao no cadastro de comunidades tradicionais para fins de regularizacao fundiaria do territorio'],
     {'categoria_lgpd': 'origem_racial_etnica', 'confianca': 0.8,
      'justificativa': 'autodeclaracao de pertencimento etnico-racial tradicional vinculada a familia identificavel'}),
]


def _mensagens_poucos_disparos() -> list[dict]:
    mensagens = []
    for campo, valores, resposta in _EXEMPLOS_POUCOS_DISPAROS:
        mensagens.append({'role': 'user', 'content': _prompt_usuario(campo, valores, com_instrucao=False)})
        mensagens.append({'role': 'assistant', 'content': json.dumps(resposta, ensure_ascii=False)})
    return mensagens


def _extrair_json(texto: str) -> dict:
    """Tira <think>...</think> (o Qwen3 emite isso mesmo com
    chat_template_kwargs.enable_thinking desligado), tira cerca de
    markdown, acha o primeiro objeto JSON balanceado."""
    texto = texto.strip()
    while '<think>' in texto and '</think>' in texto:
        inicio_think = texto.find('<think>')
        fim_think = texto.find('</think>', inicio_think)
        if fim_think == -1:
            break
        texto = texto[:inicio_think] + texto[fim_think + len('</think>'):]
    texto = texto.strip()
    if texto.startswith('```'):
        linhas = texto.splitlines()
        if linhas and linhas[0].startswith('```'):
            linhas = linhas[1:]
        if linhas and linhas[-1].strip().startswith('```'):
            linhas = linhas[:-1]
        texto = '\n'.join(linhas).strip()

    inicio = texto.find('{')
    if inicio == -1:
        raise ValueError(f'sem objeto JSON na resposta do llm: {texto!r}')
    profundidade = 0
    dentro_string = False
    escape = False
    for i in range(inicio, len(texto)):
        ch = texto[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            dentro_string = not dentro_string
            continue
        if dentro_string:
            continue
        if ch == '{':
            profundidade += 1
        elif ch == '}':
            profundidade -= 1
            if profundidade == 0:
                return json.loads(texto[inicio:i + 1])
    raise ValueError(f'JSON nao balanceado na resposta do llm: {texto!r}')


def classificar_trecho(campo: str, valores: list[str]) -> dict | None:
    """Chama o `llm` sobre uma amostra pequena de um campo ja sinalizado
    pela Camada 2. Retorna None se o llm estiver indisponivel ou responder
    algo inutilizavel - falha aberta, o motor mantem so' o veredito da
    Camada 2 nesse caso."""
    payload = {
        'model': _LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': _prompt_sistema()},
            *_mensagens_poucos_disparos(),
            {'role': 'user', 'content': _prompt_usuario(campo, valores)},
        ],
        'temperature': 0.0,
        'top_p': 1.0,
        'max_tokens': 300,
        'stream': False,
        'chat_template_kwargs': {'enable_thinking': False},
        'reasoning_format': 'none',
    }
    try:
        resp = requests.post(f'{_LLM_URL}/v1/chat/completions', json=payload, timeout=_LLM_TIMEOUT_SECONDS)
        resp.raise_for_status()
        conteudo = resp.json()['choices'][0]['message']['content']
        bruto = _extrair_json(conteudo)
        classificacao = _ClassificacaoLLM.model_validate(bruto)
    except (requests.RequestException, ValueError, KeyError, IndexError, ValidationError) as e:
        log.warning('camada3: llm indisponivel ou resposta invalida, mantendo so a Camada 2 (%s)', e)
        return None

    if classificacao.categoria_lgpd not in _CATEGORIAS_VALIDAS or not (0.0 <= classificacao.confianca <= 1.0):
        log.warning('camada3: classificacao fora do contrato esperado (%r), mantendo so a Camada 2', classificacao)
        return None
    return classificacao.model_dump()


def rodar_camada3(campo: str, valores: list[str]) -> list[dict]:
    classificacao = classificar_trecho(campo, valores)
    if classificacao is None or classificacao['categoria_lgpd'] == 'nenhum':
        return []
    return [{
        'campo': campo,
        'categoria': classificacao['categoria_lgpd'],
        'confianca': round(classificacao['confianca'], 2),
        'camada': 3,
        'justificativa': classificacao['justificativa'],
    }]
