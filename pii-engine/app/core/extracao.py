"""
Camada 0: transforma um recurso (nome + bytes) em campo -> valores, antes da
Camada 1. Formato sem extrator registrado, ou compactado que estoura limite
de profundidade/tamanho, levanta ExtracaoAbortada -- nunca falha em silencio
como um achado 'liberar'.
"""

import csv
import io
import json
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

MAX_PROFUNDIDADE = 3
MAX_TAMANHO_DESCOMPACTADO = 200 * 1024 * 1024  # 200 MB por recurso
MAX_PAGINAS_OCR = 30  # cada pagina OCR e cara em CPU; limite conservador

_DELIMITADORES_CSV = ',;\t|'
MAX_TAMANHO_NOME_CAMPO = 80  # nome de coluna real nao passa disso; acima e' sinal de parse quebrado


class ExtracaoAbortada(Exception):
    def __init__(self, motivo: str):
        self.motivo = motivo
        super().__init__(motivo)


def tem_texto_extraivel(caminho_pdf) -> bool:
    from pypdf import PdfReader

    texto = ''.join(p.extract_text() or '' for p in PdfReader(caminho_pdf).pages)
    return len(texto.strip()) > 50


def _decodificar(conteudo: bytes) -> str:
    # 'utf-8-sig' em vez de 'utf-8': decodifica igual quando nao ha BOM, mas
    # remove o BOM (﻿) quando ha - sem isso, o BOM grudava no primeiro
    # nome de campo (CSV) ou no inicio do texto extraido, e ja foi visto
    # virando "achado" de PII sobre o proprio titulo do arquivo (RJ/SETRAM).
    for codificacao in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode('utf-8-sig', errors='replace')


def _nomes_de_campo_plausiveis(nomes: list[str]) -> bool:
    """Sinal de que o delimitador escolhido (pelo Sniffer ou pelo fallback)
    esta errado, ou que a linha de cabecalho esta estruturalmente quebrada
    (ex. linha inteira envolvida por aspas duplicadas, um artefato real de
    exportacao ja visto em CSV de orgao publico): um nome de coluna de
    verdade nao contem o proprio caractere delimitador nem passa de
    MAX_TAMANHO_NOME_CAMPO. Quando isso falha, a causa nao e' "delimitador
    levemente errado" - e' "nao da para confiar neste parse".
    """
    if not nomes:
        return False
    for nome in nomes:
        if len(nome) > MAX_TAMANHO_NOME_CAMPO:
            return False
        if any(d in nome for d in _DELIMITADORES_CSV):
            return False
    return True


_MAX_LINHAS_PREAMBULO = 5  # limite conservador; acima disso, deixa o parse seguir e falhar do jeito normal


def _pular_preambulo(texto: str, delimitador: str) -> str:
    """Achado real (Fase 4b, CSV de orgao publico): algumas exportacoes tem
    linha(s) de titulo/metadado do relatorio antes do cabecalho de
    verdade - ex. 'COMPOSICAO DO QUADRO DE PESSOAL/SETRAM;' seguida de
    'MES DE AGOSTO/2025;', so depois vem 'TIPO DE VINCULO;QUANTITATIVO'.
    Uma linha de cabecalho real tem pelo menos 2 nomes de coluna nao
    vazios; uma linha de titulo, que so usa o delimitador incidentalmente
    no final, tem 1. Pula so linhas iniciais nesse padrao, ate um limite -
    nunca mexe em CSV de coluna unica de verdade (ali o Sniffer nem acha
    delimitador nenhum, essa funcao nao e' chamada com celulas <2 nunca).
    """
    linhas = texto.splitlines(keepends=True)
    indice = 0
    while indice < min(_MAX_LINHAS_PREAMBULO, len(linhas) - 1):
        celulas = next(csv.reader([linhas[indice]], delimiter=delimitador), [])
        if len(celulas) < 2 or sum(1 for c in celulas if c.strip()) >= 2:
            break
        indice += 1
    return ''.join(linhas[indice:])


def _extrair_csv(conteudo: bytes) -> dict[str, list[str]]:
    texto = _decodificar(conteudo)
    try:
        delimitador = csv.Sniffer().sniff(texto[:4096], delimiters=_DELIMITADORES_CSV).delimiter
    except csv.Error:
        delimitador = ','
    texto = _pular_preambulo(texto, delimitador)
    reader = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    nomes_campo = reader.fieldnames or []

    if not _nomes_de_campo_plausiveis(nomes_campo):
        # O Sniffer "teve sucesso" (ou o fallback ',' foi usado), mas o
        # resultado nao e' um cabecalho de verdade - ex. o Sniffer escolheu
        # ';' por causa de duas colunas vazias no fim da linha, quando o
        # delimitador real e' ',', ou a linha inteira veio envolvida por
        # aspas duplicadas (exportacao malformada). Tentar outro delimitador
        # as cegas nao resolve o segundo caso, entao a resposta correta e'
        # nao fingir que o cabecalho foi lido - nao inventar achado sobre um
        # "campo" que na verdade e' a linha inteira ou um pedaco dela.
        raise ExtracaoAbortada('cabecalho_csv_malformado')

    campos: dict[str, list[str]] = {nome: [] for nome in nomes_campo}
    for linha in reader:
        for nome, valor in linha.items():
            if nome in campos:
                campos[nome].append(valor or '')
    return campos


def _extrair_xlsx(conteudo: bytes) -> dict[str, list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    ws = wb.active
    linhas = ws.iter_rows(values_only=True)
    cabecalho = [str(c) if c is not None else '' for c in next(linhas)]
    campos: dict[str, list[str]] = {nome: [] for nome in cabecalho}
    for linha in linhas:
        for nome, valor in zip(cabecalho, linha):
            campos[nome].append('' if valor is None else str(valor))
    return campos


def _achatar(obj) -> dict[str, list[str]]:
    """Achata lista de dict (ou dict unico) em campo -> valores. Estrutura
    aninhada (dict/list dentro de um valor) e descartada de proposito -- e
    o que causava o ruido do GeoJSON tratando estrutura como texto livre."""
    campos: dict[str, list[str]] = {}
    registros = obj if isinstance(obj, list) else [obj]
    for registro in registros:
        if not isinstance(registro, dict):
            continue
        for nome, valor in registro.items():
            if isinstance(valor, (dict, list)):
                continue
            campos.setdefault(nome, []).append('' if valor is None else str(valor))
    return campos


def _extrair_json(conteudo: bytes) -> dict[str, list[str]]:
    dados = json.loads(_decodificar(conteudo))
    # GeoJSON: anda so pelas properties de cada feature, nunca pelo envelope
    # estrutural (type/features/geometry sao esqueleto, nao dado do usuario).
    if isinstance(dados, dict) and dados.get('type') == 'FeatureCollection':
        propriedades = [f.get('properties', {}) for f in dados.get('features', []) if isinstance(f, dict)]
        return _achatar(propriedades)
    if isinstance(dados, dict) and dados.get('type') == 'Feature':
        return _achatar(dados.get('properties', {}))
    return _achatar(dados)


def _extrair_yaml(conteudo: bytes) -> dict[str, list[str]]:
    import yaml

    dados = yaml.safe_load(_decodificar(conteudo))
    return _achatar(dados)


def _extrair_txt(conteudo: bytes) -> dict[str, list[str]]:
    return {'texto_extraido': [_decodificar(conteudo)]}


def _extrair_pdf(conteudo: bytes) -> dict[str, list[str]]:
    with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
        tmp.write(conteudo)
        tmp.flush()
        if tem_texto_extraivel(tmp.name):
            from pypdf import PdfReader

            texto = ''.join(p.extract_text() or '' for p in PdfReader(tmp.name).pages)
        else:
            from pdf2image import convert_from_path
            import pytesseract

            paginas = convert_from_path(tmp.name, first_page=1, last_page=MAX_PAGINAS_OCR)
            texto = '\n'.join(pytesseract.image_to_string(p, lang='por') for p in paginas)
    return {'texto_extraido': [texto]}


def _extrair_docx(conteudo: bytes) -> dict[str, list[str]]:
    import docx

    doc = docx.Document(io.BytesIO(conteudo))
    texto = '\n'.join(p.text for p in doc.paragraphs)
    return {'texto_extraido': [texto]}


def _extrair_odt(conteudo: bytes) -> dict[str, list[str]]:
    from odf import teletype
    from odf.opendocument import load
    from odf.text import P

    doc = load(io.BytesIO(conteudo))
    texto = '\n'.join(teletype.extractText(p) for p in doc.getElementsByType(P))
    return {'texto_extraido': [texto]}


def _extrair_ods(conteudo: bytes) -> dict[str, list[str]]:
    from odf import teletype
    from odf.opendocument import load
    from odf.table import Table, TableCell, TableRow

    doc = load(io.BytesIO(conteudo))
    tabelas = doc.getElementsByType(Table)
    if not tabelas:
        return {}
    linhas = tabelas[0].getElementsByType(TableRow)
    if not linhas:
        return {}

    def texto_da_celula(celula) -> str:
        return teletype.extractText(celula)

    cabecalho = [texto_da_celula(c) for c in linhas[0].getElementsByType(TableCell)]
    if not _nomes_de_campo_plausiveis([n for n in cabecalho if n]):
        # Mesmo caso do CSV malformado (ver _nomes_de_campo_plausiveis): em
        # export do SIDRA/geratabela a primeira linha da primeira planilha
        # e as vezes um titulo/descricao da tabela, nao cabecalho de coluna
        # - sem essa checagem isso vira um "campo" com o texto todo do
        # titulo, e a Camada 1 acaba classificando pedacos dele como PII.
        raise ExtracaoAbortada('cabecalho_ods_malformado')
    campos: dict[str, list[str]] = {nome: [] for nome in cabecalho if nome}
    for linha in linhas[1:]:
        for nome, celula in zip(cabecalho, linha.getElementsByType(TableCell)):
            if nome in campos:
                campos[nome].append(texto_da_celula(celula))
    return campos


def _extrair_kml(conteudo: bytes) -> dict[str, list[str]]:
    """KML e XML com schema conhecido: cada Placemark tem name/description
    escritos por humano, isso e o que interessa -- nao a geometria crua."""
    raiz = ET.fromstring(conteudo)
    campos: dict[str, list[str]] = {'name': [], 'description': []}
    achou_placemark = False
    for elemento in raiz.iter():
        if elemento.tag.rsplit('}', 1)[-1] != 'Placemark':
            continue
        achou_placemark = True
        for filho in elemento:
            filho_tag = filho.tag.rsplit('}', 1)[-1]
            if filho_tag in campos and filho.text and filho.text.strip():
                campos[filho_tag].append(filho.text.strip())
    if not achou_placemark:
        return _extrair_xml(conteudo)
    return {k: v for k, v in campos.items() if v}


def _extrair_xml(conteudo: bytes) -> dict[str, list[str]]:
    """XML generico: so texto de no-folha (sem filhos), nunca a estrutura
    em si -- mesmo cuidado do GeoJSON, para nao confundir tag com dado."""
    raiz = ET.fromstring(conteudo)
    campos: dict[str, list[str]] = {}
    for elemento in raiz.iter():
        if len(elemento) > 0 or not (elemento.text and elemento.text.strip()):
            continue
        tag = elemento.tag.rsplit('}', 1)[-1]
        campos.setdefault(tag, []).append(elemento.text.strip())
    return campos


def _extrair_shp_avulso(conteudo: bytes) -> dict[str, list[str]]:
    # Sem os arquivos irmaos (.dbf com a tabela de atributos, .shx), da para
    # ler geometria mas nao o dado que importa para deteccao de PII. Nao e
    # bug a corrigir aqui -- shapefile e formato de varios arquivos juntos;
    # o caminho de verdade e o pacote compactado (.shz), tratado a parte.
    raise ExtracaoAbortada('shapefile_incompleto')


_EXTRATORES = {
    '.csv': _extrair_csv,
    '.xlsx': _extrair_xlsx,
    '.json': _extrair_json,
    '.geojson': _extrair_json,
    '.yaml': _extrair_yaml,
    '.yml': _extrair_yaml,
    '.txt': _extrair_txt,
    '.pdf': _extrair_pdf,
    '.docx': _extrair_docx,
    '.odt': _extrair_odt,
    '.ods': _extrair_ods,
    '.kml': _extrair_kml,
    '.xml': _extrair_xml,
    '.shp': _extrair_shp_avulso,
}

_COMPACTADOS = {'.zip', '.7z', '.rar', '.kmz', '.shz'}
_COMPACTADOS_ZIP = {'.zip', '.kmz', '.shz'}  # mesmo formato zip, extensao diferente


def sufixo_suportado(sufixo: str) -> bool:
    """Usado pelo pii-engine (main.py) pra decidir se vale tentar completar
    o nome do arquivo pelo Content-Type HTTP quando a URL nao tem extensao
    reconhecivel - comum em recurso federal servido como API/geoservico
    (SIDRA, WFS) em vez de arquivo estatico."""
    return sufixo in _EXTRATORES or sufixo in _COMPACTADOS


def extrair_recurso(nome_arquivo: str, conteudo: bytes, profundidade: int = 0) -> dict[str, list[str]]:
    sufixo = Path(nome_arquivo).suffix.lower()

    if sufixo in _COMPACTADOS:
        if profundidade >= MAX_PROFUNDIDADE:
            raise ExtracaoAbortada('profundidade_maxima_excedida')
        return _extrair_compactado(nome_arquivo, conteudo, profundidade)

    extrator = _EXTRATORES.get(sufixo)
    if extrator is None:
        raise ExtracaoAbortada('formato_nao_suportado')
    try:
        return extrator(conteudo)
    except ExtracaoAbortada:
        raise
    except Exception as e:
        # Conteudo nao bate com a extensao declarada (ex.: link ".xlsx" que
        # na verdade serve um .xls antigo, formato OLE em vez de zip) - visto
        # na pratica contra dado real de terceiro. Sem isso, qualquer parser
        # de terceiro (openpyxl, pypdf, ET...) quebra com 500 em vez de
        # degradar pra nao_analisado, do jeito que
        # todo o resto deste modulo ja se compromete a fazer.
        raise ExtracaoAbortada(f'arquivo_corrompido_ou_extensao_incorreta: {e}')


def _extrair_shapefile_de_diretorio(diretorio: Path) -> dict[str, list[str]] | None:
    shp_files = list(diretorio.rglob('*.shp'))
    if not shp_files:
        return None
    import geopandas

    gdf = geopandas.read_file(shp_files[0])
    campos: dict[str, list[str]] = {}
    for coluna in gdf.columns:
        if coluna == 'geometry':
            continue
        campos[coluna] = [str(v) for v in gdf[coluna].tolist()]
    return campos


def _extrair_compactado(nome_arquivo: str, conteudo: bytes, profundidade: int) -> dict[str, list[str]]:
    sufixo = Path(nome_arquivo).suffix.lower()

    with tempfile.TemporaryDirectory() as tmpdir:
        arq_path = Path(tmpdir) / f'origem{sufixo}'
        arq_path.write_bytes(conteudo)
        destino = Path(tmpdir) / 'extraido'
        destino.mkdir()

        if sufixo in _COMPACTADOS_ZIP:
            with zipfile.ZipFile(arq_path) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_TAMANHO_DESCOMPACTADO:
                    raise ExtracaoAbortada('tamanho_maximo_excedido')
                z.extractall(destino)
        elif sufixo == '.7z':
            import py7zr

            with py7zr.SevenZipFile(arq_path) as z:
                if sum(i.uncompressed for i in z.list()) > MAX_TAMANHO_DESCOMPACTADO:
                    raise ExtracaoAbortada('tamanho_maximo_excedido')
                z.extractall(destino)
        elif sufixo == '.rar':
            import rarfile

            with rarfile.RarFile(arq_path) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_TAMANHO_DESCOMPACTADO:
                    raise ExtracaoAbortada('tamanho_maximo_excedido')
                z.extractall(destino)

        resultado_shp = _extrair_shapefile_de_diretorio(destino)
        if resultado_shp is not None:
            return resultado_shp

        campos: dict[str, list[str]] = {}
        for caminho in destino.rglob('*'):
            if not caminho.is_file():
                continue
            try:
                sub_campos = extrair_recurso(caminho.name, caminho.read_bytes(), profundidade + 1)
            except ExtracaoAbortada as e:
                if e.motivo == 'formato_nao_suportado':
                    continue
                raise
            for nome, valores in sub_campos.items():
                campos.setdefault(f'{caminho.name}:{nome}', []).extend(valores)
        return campos
