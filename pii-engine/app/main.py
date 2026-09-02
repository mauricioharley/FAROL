"""FAROL pii-engine: motor de deteccao de PII, endpoints POST /v1/scan (por URL/caminho)
e POST /v1/scan-upload (por upload direto de arquivo).

O motor nunca chama o CKAN de volta, devolve o veredito e para por ai. Quem
interpreta e age sobre o veredito e sempre o chamador (plugin ou scanner).
"""

import hashlib
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib3
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, model_validator

from app.core.extracao import ExtracaoAbortada, extrair_recurso, sufixo_suportado
from app.core.motor import rodar_motor

app = FastAPI(title='FAROL pii-engine')

# Verificacao de certificado TLS liga por padrao - so desliga por excecao
# explicita de host (nunca globalmente sem querer). A unica excecao real
# conhecida e' o CKAN de teste local, que usa certificado
# autoassinado (ver ckan-docker/nginx) - todo o resto (dados.gov.br, IBGE,
# CAPES, qualquer portal de terceiro real) tem que continuar verificando de
# verdade. `FAROL_VERIFY_TLS=false` continua existindo como escape hatch
# global, mas o padrao seguro e' este daqui, nao aquele.
_VERIFY_TLS = os.environ.get('FAROL_VERIFY_TLS', 'true').strip().lower() not in ('false', '0', 'nao', 'não')
_HOSTS_TLS_INSEGURO = {
    h.strip().lower() for h in os.environ.get('FAROL_HOSTS_TLS_INSEGURO', '').split(',') if h.strip()
}

if not _VERIFY_TLS or _HOSTS_TLS_INSEGURO:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _verify_para(url: str) -> bool:
    if not _VERIFY_TLS:
        return False
    return (urlsplit(url).hostname or '').lower() not in _HOSTS_TLS_INSEGURO

# Fallback pelo Content-Type HTTP quando a URL nao tem extensao reconhecivel
# - comum em recurso federal servido como API/geoservico (SIDRA, WFS) em vez
# de arquivo estatico com extensao no path.
_SUFIXO_POR_CONTENT_TYPE = {
    'application/json': '.json',
    'text/csv': '.csv',
    'application/csv': '.csv',
    'application/xml': '.xml',
    'text/xml': '.xml',
    'application/pdf': '.pdf',
    'text/plain': '.txt',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.oasis.opendocument.spreadsheet': '.ods',
    'application/vnd.google-earth.kml+xml': '.kml',
    'application/zip': '.zip',
}

# Base permitida para leitura por disco: nunca aceita caminho
# fora daqui, mesmo que o chamador passe algo diferente por engano ou de
# forma maliciosa.
_CKAN_RESOURCES_DIR = Path(os.environ.get('FAROL_CKAN_STORAGE_PATH', '/mnt/ckan/storage/resources')).resolve()


class ScanRequest(BaseModel):
    dataset_id: str
    recurso_url: str | None = None
    caminho_local: str | None = None
    nome_arquivo: str | None = None

    @model_validator(mode='after')
    def _valida_origem(self):
        if not self.recurso_url and not self.caminho_local:
            raise ValueError('informe recurso_url ou caminho_local')
        return self


def _exigir_token_servico(x_farol_token: str = Header(...)) -> None:
    """Autentica chamada maquina-a-maquina (scanner, ckanext-farol-guard), nao pessoa.

    Mesmo padrao de painel/main.py::_exigir_token_servico, reaproveitando o
    mesmo segredo (FAROL_INGEST_TOKEN) ja compartilhado entre os dois - o
    motor nunca deve ficar alcancavel por quem nao seja um dos dois
    chamadores internos conhecidos (ver docker-compose.yml: `expose`, nunca
    `ports`, e mount real de producao read-only).
    """
    token_esperado = os.environ.get('FAROL_INGEST_TOKEN')
    if not token_esperado:
        raise HTTPException(status_code=500, detail='FAROL_INGEST_TOKEN nao configurado')
    if not secrets.compare_digest(x_farol_token, token_esperado):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='token invalido')


@app.get('/health')
def health():
    return {'status': 'ok'}


def _ler_conteudo(req: ScanRequest) -> tuple[bytes, str]:
    if req.caminho_local:
        caminho = Path(req.caminho_local).resolve()
        if _CKAN_RESOURCES_DIR not in caminho.parents and caminho != _CKAN_RESOURCES_DIR:
            raise HTTPException(status_code=400, detail='caminho_local fora do diretorio permitido')
        nome_arquivo = req.nome_arquivo or caminho.name
        return caminho.read_bytes(), nome_arquivo

    conteudo, content_type = _baixar_com_prazo_total(req.recurso_url)
    nome_arquivo = req.nome_arquivo or Path(req.recurso_url.split('?')[0]).name
    if not sufixo_suportado(Path(nome_arquivo).suffix.lower()):
        sufixo_por_tipo = _SUFIXO_POR_CONTENT_TYPE.get((content_type or '').split(';')[0].strip().lower())
        if sufixo_por_tipo:
            nome_arquivo = f'{nome_arquivo or "recurso"}{sufixo_por_tipo}'
    return conteudo, nome_arquivo


_PRAZO_TOTAL_DOWNLOAD_SEGUNDOS = 45
_TAMANHO_BLOCO = 1024 * 256


_TAMANHO_MAXIMO_DOWNLOAD = 200 * 1024 * 1024  # mesmo teto do zip-bomb (extracao.MAX_TAMANHO_DESCOMPACTADO)


def _baixar_com_prazo_total(url: str) -> tuple[bytes, str | None]:
    """`requests(timeout=...)` só cobre o intervalo entre bytes recebidos,
    não a duração total - um servidor de terceiro que manda byte aos
    poucos (trickle) sem nunca parar passa direto pelo timeout normal e
    ainda assim trava a chamada por muito tempo (visto na pratica contra
    portal de terceiro real). Aqui o corte e' por relogio de parede: tempo
    total decorrido, nao gap entre leituras. Retorna tupla (nao estado
    global) porque o endpoint roda em threadpool - varias chamadas
    concorrentes nao podem compartilhar uma variavel de modulo.

    Teto de tamanho (`_TAMANHO_MAXIMO_DOWNLOAD`): o conteudo baixado fica
    inteiro em memoria (`pedacos`/`b''.join`, nunca em arquivo em disco -
    diferente do caminho de compactado em extracao.py, que ja tinha teto).
    Sem limite aqui, um recurso legitimamente enorme (nao precisa ser zip
    bomb) estoura a RAM do container, nao o disco - e a tela `/scan` torna
    mais facil disparar isso sem querer, contra portal de terceiro real,
    sem revisar cada recurso um a um antes. Verifica primeiro pelo
    Content-Length declarado (rejeita sem baixar nada); se o servidor nao
    declarar ou declarar errado, o corte durante o streaming e' o
    verdadeiro limite."""
    inicio = time.monotonic()
    with requests.get(url, verify=_verify_para(url), timeout=30, stream=True) as resposta:
        resposta.raise_for_status()
        content_type = resposta.headers.get('content-type')
        tamanho_declarado = resposta.headers.get('content-length')
        if tamanho_declarado and int(tamanho_declarado) > _TAMANHO_MAXIMO_DOWNLOAD:
            raise requests.RequestException(
                f'recurso declara {int(tamanho_declarado)} bytes (content-length), acima do limite de '
                f'{_TAMANHO_MAXIMO_DOWNLOAD} bytes - download nem iniciado'
            )
        pedacos = []
        tamanho_lido = 0
        for bloco in resposta.iter_content(chunk_size=_TAMANHO_BLOCO):
            pedacos.append(bloco)
            tamanho_lido += len(bloco)
            if tamanho_lido > _TAMANHO_MAXIMO_DOWNLOAD:
                raise requests.RequestException(
                    f'download excedeu o limite de {_TAMANHO_MAXIMO_DOWNLOAD} bytes (servidor nao declarou '
                    f'content-length correto de antemao)'
                )
            if time.monotonic() - inicio > _PRAZO_TOTAL_DOWNLOAD_SEGUNDOS:
                raise requests.exceptions.Timeout(
                    f'download nao concluido em {_PRAZO_TOTAL_DOWNLOAD_SEGUNDOS}s (tempo total, nao so leitura parada)'
                )
        return b''.join(pedacos), content_type


def _resultado_scan(conteudo: bytes, nome_arquivo: str, dataset_id: str) -> dict:
    hash_arquivo = hashlib.sha256(conteudo).hexdigest()
    try:
        campos = extrair_recurso(nome_arquivo, conteudo)
    except ExtracaoAbortada as e:
        return {
            'score_risco': 0,
            'achados': [],
            'veredito': 'nao_analisado',
            'motivo_nao_analisado': e.motivo,
            'hash_arquivo': hash_arquivo,
            'dataset_id': dataset_id,
        }

    resultado = rodar_motor(campos)
    resultado['dataset_id'] = dataset_id
    resultado['hash_arquivo'] = hash_arquivo
    return resultado


@app.post('/v1/scan', dependencies=[Depends(_exigir_token_servico)])
def scan(req: ScanRequest):
    try:
        conteudo, nome_arquivo = _ler_conteudo(req)
    except requests.RequestException as e:
        # recurso_url de terceiro pode estar lento, fora do ar ou recusar a
        # conexao (visto na pratica contra dado real de terceiro) - falha
        # de rede no download nunca pode virar
        # 500 sem tratamento, mesmo principio ja aplicado a falha de parse
        # em extracao.py: degrada pra nao_analisado, nunca quebra em silencio.
        return {
            'score_risco': 0,
            'achados': [],
            'veredito': 'nao_analisado',
            'motivo_nao_analisado': f'erro_download: {e}',
            'hash_arquivo': None,
            'dataset_id': req.dataset_id,
        }
    return _resultado_scan(conteudo, nome_arquivo, req.dataset_id)


@app.post('/v1/scan-upload', dependencies=[Depends(_exigir_token_servico)])
async def scan_upload(dataset_id: str = Form(...), arquivo: UploadFile = File(...)):
    """Escaneia bytes enviados diretamente, sem URL nem caminho em disco.

    Existe para o plugin preventivo: em `before_resource_create`,
    um upload novo ainda nao tem URL publica nem foi salvo em disco - so
    existe como stream em memoria/tmp do proprio request HTTP do CKAN. Os
    outros dois modos de /v1/scan (recurso_url, caminho_local) pressupoem
    que o recurso ja existe em algum lugar acessivel; este nao.
    """
    conteudo = await arquivo.read()
    nome_arquivo = arquivo.filename or 'arquivo'
    return _resultado_scan(conteudo, nome_arquivo, dataset_id)
