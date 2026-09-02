FROM nginx:stable-alpine

ENV NGINX_DIR=/etc/nginx

RUN apk update --no-cache && \
    apk upgrade --no-cache && \
    apk add --no-cache openssl

COPY default.conf ${NGINX_DIR}/conf.d/default.conf

RUN mkdir -p ${NGINX_DIR}/certs

# Certificado autoassinado gerado a cada start do container - mesmo padrão
# já usado pelo nginx do ckan-docker (ver ckan-docker/nginx/Dockerfile).
# Só serve pro ambiente de teste local; um deploy real troca isto por
# certificado emitido de verdade (ex. Let's Encrypt via um proxy reverso
# existente), montando os arquivos em vez de gerar aqui.
ENTRYPOINT \
  openssl req \
    -subj '/O=Farol/CN=localhost' \
    -x509 -newkey rsa:4096 \
    -nodes \
    -keyout ${NGINX_DIR}/certs/painel.key \
    -out ${NGINX_DIR}/certs/painel.crt \
    -days 365 && \
  nginx -g 'daemon off;'
