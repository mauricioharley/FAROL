"""
Logica de auditoria em lote: varre um CKAN via API, chama o pii-engine por
recurso, grava achado. Disparado via main.py (servico HTTP do scanner) -
nunca mais por linha de comando direta (decisao explicita do Mauricio: a
ferramenta nao deve exigir interacao por CLI, nem de administrador
tecnico). `preparar_execucao` fica rapida de proposito (so' metadado,
nenhum download de recurso) pra devolver o `execucao_id` synchronous no
POST /iniciar; `rodar_execucao` e' a parte lenta, chamada numa thread por
main.py.

--usar-disco: troca o download HTTP por leitura direta do mount
read-only de producao. So faz sentido quando o scanner roda no mesmo host
que tem esse mount (ver caminho_no_disco em coletor.py).
"""

import os

import requests

from coletor import caminho_no_disco, listar_recursos
from persistencia import (
    atualizar_progresso,
    deve_cancelar,
    finalizar_execucao,
    gravar_resultado,
    iniciar_execucao,
    marcar_recurso_conhecido,
    preparar_schema,
    recurso_mudou,
)


def preparar_execucao(
    base_url: str,
    api_key: str | None,
    verify: bool,
    executado_por: str,
    orgs_filtro: list[str] | None,
    formatos_filtro: list[str] | None,
    ambiente: str,
    incremental: bool,
) -> tuple[int, list[dict]]:
    preparar_schema()
    recursos = listar_recursos(
        base_url, api_key=api_key, verify=verify, orgs_filtro=orgs_filtro, formatos_filtro=formatos_filtro,
    )
    if incremental:
        # So' inclui recurso novo ou com metadado de modificacao diferente do
        # que ja foi visto - o filtro acontece aqui, antes de `iniciar_execucao`,
        # entao `total_recursos` ja reflete so' o que sera de fato reprocessado
        # (nao conta como "processado" um recurso que foi pulado por nao ter mudado).
        recursos = [
            r for r in recursos
            if recurso_mudou(r['org'], r['dataset'], r['recurso'], r.get('modificado_em'))
        ]

    execucao_id = iniciar_execucao(
        total_recursos=len(recursos), executado_por=executado_por, ambiente=ambiente,
        orgs=','.join(orgs_filtro) if orgs_filtro else None,
        formatos=','.join(formatos_filtro) if formatos_filtro else None,
    )
    return execucao_id, recursos


def rodar_execucao(
    execucao_id: int, recursos: list[dict], engine_url: str, executado_por: str, ambiente: str, usar_disco: bool,
) -> None:
    status_final = 'concluido'
    try:
        _escanear_recursos(recursos, engine_url, executado_por, ambiente, execucao_id, usar_disco)
    except Exception:
        status_final = 'erro'
        raise
    finally:
        # Confere de novo aqui (nao so' dentro do loop): um pedido de
        # cancelamento pode ter chegado depois do ultimo recurso processado,
        # mas antes deste finally rodar - o status final precisa refletir
        # isso mesmo assim, nao aparecer como "concluido".
        if deve_cancelar(execucao_id):
            status_final = 'cancelado'
        finalizar_execucao(execucao_id, status_final)


def _escanear_recursos(recursos, engine_url, executado_por, ambiente, execucao_id, usar_disco):
    headers = {'X-Farol-Token': os.environ.get('FAROL_INGEST_TOKEN')}
    for indice, r in enumerate(recursos, start=1):
        if deve_cancelar(execucao_id):
            # Para entre um recurso e outro, nunca no meio de uma chamada ao
            # pii-engine ja em andamento - o achado registrado ate aqui fica
            # visivel no painel mesmo com o scan interrompido (gravar_resultado
            # ja gravou recurso por recurso, nao em lote no final).
            return

        payload = {'dataset_id': r['dataset'], 'nome_arquivo': r['url'].split('?')[0].rsplit('/', 1)[-1]}
        if usar_disco:
            payload['caminho_local'] = str(caminho_no_disco(r['recurso'], base=os.environ.get('FAROL_CKAN_STORAGE_PATH', '/mnt/ckan/storage/resources')))
        else:
            payload['recurso_url'] = r['url']

        atualizar_progresso(execucao_id, indice - 1, r['recurso_nome'])
        try:
            resp = requests.post(f'{engine_url}/v1/scan', json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            resultado = resp.json()
        except requests.RequestException as e:
            print(f"  [erro] {r['org']}/{r['dataset']}/{r['recurso']}: {e}")
            atualizar_progresso(execucao_id, indice, r['recurso_nome'])
            continue

        gravar_resultado(
            org=r['org'], dataset_id=r['dataset'], recurso=r['recurso'], recurso_nome=r['recurso_nome'],
            resultado=resultado, executado_por=executado_por, ambiente=ambiente,
        )
        marcar_recurso_conhecido(r['org'], r['dataset'], r['recurso'], r.get('modificado_em'), execucao_id)
        n_achados = len(resultado.get('achados') or [])
        print(f"  {r['org']}/{r['dataset']}/{r['recurso_nome']} -> {resultado['veredito']} ({n_achados} achado(s))")
        atualizar_progresso(execucao_id, indice, r['recurso_nome'])
