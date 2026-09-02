"""Mede precisao/recall da Camada 3 (classificador LLM) contra um ou mais
conjuntos rotulados em JSONL. Roda dentro do container pii-engine, ja que
precisa alcancar o servico `llm` da mesma rede do compose:

    docker compose run --rm \\
        -v $(pwd)/pii-engine/scripts:/app/scripts \\
        -v $(pwd)/pii-engine/eval:/app/eval \\
        --entrypoint python pii-engine scripts/avaliar_camada3.py \\
        eval/sintetico_ampliacao_tuning.jsonl eval/sintetico_ampliacao_validacao.jsonl

Cada linha do JSONL precisa ter "campo" (nome da coluna), "amostras" (lista
de valores) e "categoria_lgpd_correta" (uma das chaves de
app.core.camada3._CATEGORIA_DESCRICAO). Nunca imprime o conteudo das
amostras, so campo/categoria esperada/categoria prevista - mesma regra de
nunca logar o valor de PII que vale para o motor em producao.
"""

import argparse
import json
from collections import defaultdict

from app.core.camada3 import classificar_trecho

CATEGORIAS_SENSIVEIS = {
    'origem_racial_etnica',
    'convicao_religiosa',
    'opiniao_politica',
    'filiacao_sindical_ou_organizacao',
    'dado_saude_ou_vida_sexual',
    'dado_genetico_ou_biometrico',
}


def carregar(caminho: str) -> list[dict]:
    itens = []
    with open(caminho) as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                itens.append(json.loads(linha))
    return itens


def avaliar(itens: list[dict]) -> dict:
    total_por_categoria = defaultdict(int)
    correto_por_categoria = defaultdict(int)
    previsto_por_categoria = defaultdict(int)
    erros = []
    n_erro_llm = 0
    acertos = 0

    for item in itens:
        campo = item['campo']
        esperada = item['categoria_lgpd_correta']
        total_por_categoria[esperada] += 1

        resultado = classificar_trecho(campo, item['amostras'])
        prevista = resultado['categoria_lgpd'] if resultado else None
        if prevista is None:
            n_erro_llm += 1
            prevista = '(erro_llm)'

        previsto_por_categoria[prevista] += 1
        if prevista == esperada:
            acertos += 1
            correto_por_categoria[esperada] += 1
        else:
            erros.append({'campo': campo, 'esperada': esperada, 'prevista': prevista})

    return {
        'total': len(itens),
        'acertos': acertos,
        'erro_llm': n_erro_llm,
        'total_por_categoria': dict(total_por_categoria),
        'correto_por_categoria': dict(correto_por_categoria),
        'previsto_por_categoria': dict(previsto_por_categoria),
        'erros': erros,
    }


def imprimir_relatorio(resultado: dict, nome: str) -> None:
    total = resultado['total']
    print(f'\n=== {nome} ({total} itens) ===')
    if total == 0:
        print('  (vazio)')
        return
    print(f'Acuracia geral: {resultado["acertos"]}/{total} ({resultado["acertos"] / total:.1%})')
    if resultado['erro_llm']:
        print(f'Chamadas ao llm sem resposta parseavel: {resultado["erro_llm"]}')

    tp_sens = total_sens = 0
    for categoria in sorted(resultado['total_por_categoria']):
        total_cat = resultado['total_por_categoria'][categoria]
        correto = resultado['correto_por_categoria'].get(categoria, 0)
        previsto = resultado['previsto_por_categoria'].get(categoria, 0)
        recall = correto / total_cat if total_cat else float('nan')
        precisao = correto / previsto if previsto else float('nan')
        marcador = ' *' if categoria in CATEGORIAS_SENSIVEIS else ''
        print(f'  {categoria}{marcador} (n={total_cat}): recall={recall:.1%} precisao={precisao:.1%}')
        if categoria in CATEGORIAS_SENSIVEIS:
            tp_sens += correto
            total_sens += total_cat

    if total_sens:
        print(f'\n  Recall agregado nas 6 categorias sensiveis do Art. 5o, II (*): '
              f'{tp_sens}/{total_sens} ({tp_sens / total_sens:.1%})')

    if resultado['erros']:
        print('\n  Erros (sem conteudo das amostras, so campo/categoria):')
        for erro in resultado['erros']:
            print(f'    campo={erro["campo"]!r} esperada={erro["esperada"]} prevista={erro["prevista"]}')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('caminhos', nargs='+', help='um ou mais arquivos .jsonl rotulados')
    args = ap.parse_args()

    for caminho in args.caminhos:
        resultado = avaliar(carregar(caminho))
        imprimir_relatorio(resultado, caminho)


if __name__ == '__main__':
    main()
