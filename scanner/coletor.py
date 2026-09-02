"""
Coletor CKAN: fala API/HTTP para metadados sempre. Para o conteudo dos
recursos, o padrao e HTTP, mas da pra trocar por leitura direta de disco
(otimizacao exclusiva de quando o scanner roda no mesmo host que tem o
mount read-only da producao, ver caminho_no_disco).
"""

from pathlib import Path

import requests


def _extensao(url: str) -> str:
    nome = url.split('?')[0].rsplit('/', 1)[-1]
    if '.' not in nome:
        return ''
    return nome.rsplit('.', 1)[-1].lower()


def listar_recursos(
    base_url: str,
    api_key: str | None = None,
    verify: bool = True,
    orgs_filtro: list[str] | None = None,
    formatos_filtro: list[str] | None = None,
) -> list[dict]:
    headers = {'Authorization': api_key} if api_key else {}
    orgs = requests.get(
        f'{base_url}/api/3/action/organization_list', headers=headers, verify=verify, timeout=30
    ).json()['result']

    if orgs_filtro:
        orgs = [o for o in orgs if o in orgs_filtro]

    # Normaliza pra comparar sem depender de maiuscula/minuscula nem de ponto
    # na frente (usuario pode digitar ".csv" ou "CSV" na tela de novo scan).
    formatos_normalizados = (
        {f.lower().lstrip('.') for f in formatos_filtro} if formatos_filtro else None
    )

    recursos = []
    for org in orgs:
        datasets_resumo = requests.get(
            f'{base_url}/api/3/action/organization_show',
            params={'id': org, 'include_datasets': True},
            headers=headers,
            verify=verify,
            timeout=30,
        ).json()['result']['packages']

        for ds_resumo in datasets_resumo:
            ds = requests.get(
                f'{base_url}/api/3/action/package_show',
                params={'id': ds_resumo['id']},
                headers=headers,
                verify=verify,
                timeout=30,
            ).json()['result']
            for res in ds['resources']:
                # Formato sem extensao reconhecivel, com filtro ativo: exclui -
                # sem sinal confiavel de formato, mais seguro deixar de fora
                # de um scan com escopo explicito do que incluir as cegas.
                if formatos_normalizados is not None and _extensao(res['url']) not in formatos_normalizados:
                    continue
                recursos.append(
                    {
                        'org': org,
                        'dataset': ds['name'],
                        'recurso': res['id'],
                        'recurso_nome': res.get('name') or res['url'].split('?')[0].rsplit('/', 1)[-1],
                        'url': res['url'],
                        # Usado pelo modo incremental (persistencia.recurso_mudou) pra
                        # decidir se o recurso precisa ser reprocessado ou nao - o CKAN
                        # devolve isso de graca no metadado, sem precisar baixar nada.
                        'modificado_em': res.get('last_modified') or ds.get('metadata_modified'),
                    }
                )
    return recursos


def caminho_no_disco(resource_id: str, base: str = '/mnt/ckan/storage/resources') -> Path:
    return Path(base) / resource_id[0:3] / resource_id[3:6] / resource_id[6:]
