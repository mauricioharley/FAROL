"""
Testes da Camada 0 (extracao.py). Cobrem sobretudo as classes de bug reais
achadas testando contra dado real: cabecalho CSV malformado virando
"campo" falso, extensao que nao bate com o conteudo real, limite de
profundidade de zip que precisa propagar mesmo de dentro de um zip
aninhado, e GeoJSON que nao pode tratar a estrutura como texto livre.
"""

import io
import json
import zipfile

import pytest

from app.core.extracao import (
    MAX_PROFUNDIDADE,
    ExtracaoAbortada,
    _nomes_de_campo_plausiveis,
    extrair_recurso,
    sufixo_suportado,
)


def test_sufixo_suportado():
    assert sufixo_suportado('.csv')
    assert sufixo_suportado('.zip')
    assert not sufixo_suportado('.parquet')


def test_csv_normal():
    conteudo = 'nome,email\nMaria,maria@example.com\n'.encode('utf-8')
    campos = extrair_recurso('dados.csv', conteudo)
    assert campos == {'nome': ['Maria'], 'email': ['maria@example.com']}


def test_csv_com_bom_utf8_nao_gruda_no_primeiro_nome_de_campo():
    # Achado real (Fase 4b, CSV de terceiro): BOM UTF-8 nao removido fazia
    # o primeiro nome de campo virar '﻿nome', o que ja causou um
    # falso positivo (Camada 2 classificando o proprio cabecalho como
    # endereco quando o "campo" era na verdade o titulo do relatorio).
    conteudo = 'nome,email\nMaria,maria@example.com\n'.encode('utf-8-sig')
    campos = extrair_recurso('dados.csv', conteudo)
    assert campos == {'nome': ['Maria'], 'email': ['maria@example.com']}


def test_csv_com_linhas_de_titulo_antes_do_cabecalho_real():
    # Achado real (Fase 4b, CSV do RJ/SETRAM): duas linhas de titulo/
    # metadado do relatorio antes do cabecalho de verdade. Sem pular essas
    # linhas, o motor lia o titulo do relatorio como se fosse nome de
    # campo, e a Camada 2 chegava a classifica-lo como endereco.
    conteudo = (
        'COMPOSIÇÃO DO QUADRO DE PESSOAL/SETRAM;\n'
        'MÊS DE AGOSTO/2025;\n'
        'TIPO DE VÍNCULO;QUANTITATIVO\n'
        'EXTRA-QUADRO;143\n'
    ).encode('utf-8')
    campos = extrair_recurso('dados.csv', conteudo)
    assert campos == {'TIPO DE VÍNCULO': ['EXTRA-QUADRO'], 'QUANTITATIVO': ['143']}


def test_csv_coluna_unica_de_verdade_nao_e_tratado_como_preambulo():
    # Nao pode confundir CSV de coluna unica legitimo com preambulo -
    # aqui nao ha delimitador nenhum pra sniffar, entao a funcao de pular
    # preambulo nunca ve uma linha com 2+ celulas pra considerar "titulo".
    conteudo = 'nome\nMaria\nJoao\n'.encode('utf-8')
    campos = extrair_recurso('dados.csv', conteudo)
    assert campos == {'nome': ['Maria', 'Joao']}


def test_csv_cabecalho_malformado_aspas_envolvendo_linha_inteira():
    # Artefato real de exportacao: a linha de cabecalho inteira
    # vem entre aspas duplas, o Sniffer "acerta" um delimitador mas o
    # resultado nao e' cabecalho de verdade.
    conteudo = '"nome,email,telefone"\n"Maria,x@x.com,123"\n'.encode('utf-8')
    with pytest.raises(ExtracaoAbortada) as exc:
        extrair_recurso('quebrado.csv', conteudo)
    assert exc.value.motivo == 'cabecalho_csv_malformado'


def test_nomes_de_campo_plausiveis():
    assert _nomes_de_campo_plausiveis(['nome', 'cpf'])
    assert not _nomes_de_campo_plausiveis([])
    assert not _nomes_de_campo_plausiveis(['a' * 81])
    assert not _nomes_de_campo_plausiveis(['campo,com,virgula'])


def test_formato_nao_suportado():
    with pytest.raises(ExtracaoAbortada) as exc:
        extrair_recurso('arquivo.parquet', b'qualquer coisa')
    assert exc.value.motivo == 'formato_nao_suportado'


def test_shapefile_avulso_vira_nao_analisado_nunca_finge_ler():
    with pytest.raises(ExtracaoAbortada) as exc:
        extrair_recurso('dados.shp', b'qualquer coisa')
    assert exc.value.motivo == 'shapefile_incompleto'


def test_extensao_declarada_nao_bate_com_conteudo_vira_erro_gracioso():
    # Bug real: recurso publicado como .xlsx cujo conteudo real
    # era .xls antigo (OLE, nao zip) - antes derrubava o servico com 500.
    with pytest.raises(ExtracaoAbortada) as exc:
        extrair_recurso('falso.xlsx', b'nao sou um zip valido')
    assert exc.value.motivo.startswith('arquivo_corrompido_ou_extensao_incorreta')


def test_geojson_so_le_properties_nunca_o_envelope_estrutural():
    geojson = {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'properties': {'nome': 'Escola Municipal X'},
                'geometry': {'type': 'Point', 'coordinates': [0, 0]},
            },
        ],
    }
    campos = extrair_recurso('dados.geojson', json.dumps(geojson).encode('utf-8'))
    assert campos == {'nome': ['Escola Municipal X']}
    assert 'type' not in campos
    assert 'geometry' not in campos
    assert 'features' not in campos


def _zip_de(conteudo: bytes, nome_interno: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(nome_interno, conteudo)
    return buf.getvalue()


def test_zip_pula_arquivo_interno_nao_suportado_mas_le_o_resto():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('dados.csv', 'nome\nMaria\n')
        z.writestr('binario.exe', b'\x00\x01\x02')
    campos = extrair_recurso('pacote.zip', buf.getvalue())
    assert campos == {'dados.csv:nome': ['Maria']}


def test_zip_profundidade_maxima_propaga_mesmo_vindo_de_dentro_de_zip_aninhado():
    # Bug real ja encontrado neste projeto: um `except ExtracaoAbortada` mal feito
    # engolia esse limite junto com o caso legitimo de "formato interno nao
    # suportado, pula e segue" - o corte de seguranca contra zip bomb
    # (profundidade/tamanho) tem que propagar sempre, nunca ser tratado como
    # "arquivo pulado, segue o resto".
    conteudo = b''
    for i in range(MAX_PROFUNDIDADE + 1):
        conteudo = _zip_de(conteudo, f'nivel{i}.zip')

    with pytest.raises(ExtracaoAbortada) as exc:
        extrair_recurso('topo.zip', conteudo)
    assert exc.value.motivo == 'profundidade_maxima_excedida'


def test_xml_generico_so_texto_de_no_folha():
    xml = b'<raiz><nome>Maria</nome><endereco><rua>Rua X</rua></endereco></raiz>'
    campos = extrair_recurso('dados.xml', xml)
    assert campos == {'nome': ['Maria'], 'rua': ['Rua X']}
    assert 'endereco' not in campos  # tem filho, e' estrutura, nao dado de folha
