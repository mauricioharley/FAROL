# Solução de problemas

Cada item abaixo foi um incidente real, encontrado e corrigido durante a construção do FAROL - não é uma lista hipotética. Formato: sintoma → causa → correção.

## Instalação e configuração

**Sintoma:** `docker compose up` falha ou entra em conflito de porta.
**Causa:** outro serviço no mesmo host já usa a porta configurada.
**Correção:** confira portas ocupadas (`ss -ltnp` ou equivalente) antes de definir as portas
publicadas no `docker-compose.yml`/`.env` de um CKAN de teste.

**Sintoma:** uma variável de ambiente nova não tem efeito nenhum depois de `docker compose up -d`.
**Causa:** convenção de nome errada, se for uma variável `CKAN_*` - três convenções
(`CKAN_`, `CKAN__`, `CKAN___`) coexistem e não são a mesma coisa.
**Correção:** ver a tabela em [Variáveis de ambiente](instalacao/variaveis-de-ambiente.md).

**Sintoma:** botão de "Upload" não aparece na tela de novo recurso do CKAN.
**Causa:** falta `CKAN__UPLOADS_ENABLED=true` (dois underscores) - `CKAN_UPLOADS_ENABLED` (um
underscore) não tem efeito, não está na lista fixa do núcleo do CKAN.
**Correção:** usar a convenção de dois underscores, redeploy.

**Sintoma:** aviso de certificado autoassinado no navegador ao acessar um CKAN de teste.
**Causa:** esperado - CKAN de teste local não tem certificado de CA pública.
**Correção:** nenhuma; prosseguir mesmo assim é seguro nesse contexto específico (ambiente de
teste, nunca produção real).

## Extração de conteúdo (Camada 0)

**Sintoma:** um "campo" no achado é, na verdade, a linha de cabeçalho inteira de um CSV
concatenada, ou um trecho de texto sem sentido.
**Causa:** delimitador "detectado com sucesso" não significa cabeçalho lido corretamente - um
arquivo com a linha de cabeçalho inteira envolvida por aspas duplicadas externas (artefato de
exportação malformado) engana o `csv.Sniffer`, que escolhe um delimitador plausível mas errado.
**Correção:** checagem de plausibilidade pós-parse (`_nomes_de_campo_plausiveis` - nenhum nome de campo real passa de ~80 caracteres nem contém o próprio delimitador); se falhar,
`ExtracaoAbortada("cabecalho_csv_malformado")` em vez de inventar um achado.

**Sintoma:** o mesmo problema acima, mas em `.ods` - o "campo" é o título completo de uma tabela.
**Causa:** exports do SIDRA/IBGE (`geratabela`) têm o título da tabela na primeira linha da
primeira planilha, não nomes de coluna reais.
**Correção:** mesma checagem de plausibilidade, reaproveitada em `_extrair_ods` - `ExtracaoAbortada("cabecalho_ods_malformado")`.

**Sintoma:** recurso `.xlsx` derruba o `pii-engine` com erro 500 (`zipfile.BadZipFile`).
**Causa:** URL anuncia `.xlsx` mas o conteúdo real é `.xls` antigo (formato OLE, não ZIP) - visto
contra dado federal real.
**Correção:** `extrair_recurso` envolve a chamada ao extrator num `try/except` amplo, convertendo
qualquer falha de parser em `ExtracaoAbortada("arquivo_corrompido_ou_extensao_incorreta")` em vez
de crashar.

**Sintoma:** PDF processado não gera achado nenhum, mesmo tendo texto visível ao abrir.
**Causa:** PDF escaneado/assinado sem camada de texto extraível.
**Correção:** fallback automático para OCR (`pdf2image` + `pytesseract`, `lang="por"`) quando o
texto extraído por `pypdf` é curto demais para ser real.

**Sintoma:** recurso de formato não reconhecido (`.parquet`, `.dbf` avulso, binário proprietário)
some silenciosamente, sem indicar que não foi analisado.
**Causa:** por design - mas é fácil confundir "não olhamos" com "olhamos e não achamos nada" se
não se checar o `veredito`.
**Correção:** sempre checar `veredito = "nao_analisado"` e `motivo_nao_analisado` na resposta - nunca tratar ausência de achado como confirmação de "sem risco" sem checar o motivo.

## Rede e download

**Sintoma:** `/v1/scan` trava por muito tempo contra um recurso de terceiro lento, mesmo com
timeout configurado.
**Causa:** o timeout padrão do `requests` cobre só o intervalo entre bytes recebidos - um
servidor que responde em "trickle" constante (nunca para de mandar byte, mas devagar) passa
batido por esse tipo de timeout.
**Correção:** `_baixar_com_prazo_total` - download em streaming com corte por tempo total
decorrido (45s), não só por gap entre leituras.

**Sintoma:** `/v1/scan` derruba com erro 500 quando o servidor de origem do recurso está fora do
ar ou recusa conexão.
**Causa:** `requests.RequestException` não tratado.
**Correção:** capturado e convertido em `veredito: "nao_analisado"`,
`motivo_nao_analisado: "erro_download: ..."`.

**Sintoma:** recurso federal/geoserviço (API, WFS) nunca é analisado - sempre
`formato_nao_suportado`, mesmo sendo um CSV/JSON de verdade.
**Causa:** a URL não tem extensão reconhecível no path (comum em API - o formato só aparece no
header `Content-Type` da resposta).
**Correção:** fallback de formato pelo `Content-Type` HTTP (`_SUFIXO_POR_CONTENT_TYPE`) quando a
URL não resolve extensão sozinha.

## Camada 2 (NER) - falsos positivos e negativos conhecidos

**Sintoma:** uma coluna de texto livre com conteúdo claramente sensível (ex. "acompanhamento de
saúde mental") não gera achado nenhum.
**Causa:** menção categórica de dado sensível não é uma entidade nomeada - os reconhecedores
padrão do Presidio (`PERSON`/`LOCATION`/`ORGANIZATION`) não cobrem isso.
**Correção:** reconhecedor customizado (`DADO_SAUDE`, lista curta de termos em português,
case-insensitive) registrado no `analyzer.registry`.

**Sintoma:** campos claramente institucionais (nome de instituição de ensino, nome de curso, sigla
de região) são classificados como `nome_pessoa` ou `endereco_local`.
**Causa:** limitação real do modelo `pt_core_news_lg` sobre nomes próprios institucionais em
texto administrativo real - confirmado testando contra dado público federal (CAPES, IBGE).
**Ainda não corrigido** - registrado como limitação conhecida, a considerar quando a Camada 3
amadurecer como filtro de refinamento.
**O que fazer hoje:** tratar achado sobre campo claramente institucional com ceticismo extra na
revisão manual; não é motivo para desligar a Camada 2 (ela também é quem pega nome de pessoa de
verdade em texto livre).

## Camada 3 (LLM)

**Sintoma:** acurácia caiu de ~93% (medição inicial, majoritariamente sintética) para ~30%
contra dado real.
**Causa:** a medição inicial tinha proporção alta de exemplo sintético/didático - nunca testado
contra ambiguidade genuína de texto burocrático real (edital, lei, dicionário de dados).
**Correção:** não foi trocar de modelo (Qwen3-8B testado, resultado estatisticamente igual) - foi
adicionar few-shot com exemplos reais (7 falso-positivo + 2 verdadeiro-positivo) ao prompt, que
levou a acurácia a 66,7% no mesmo conjunto de 30 itens reais.
**Mitigação permanente:** a Camada 3 nunca decide `bloquear` sozinha (confiança limitada a 0,89) - existe para reforçar `alertar`, não para substituir revisão humana.
