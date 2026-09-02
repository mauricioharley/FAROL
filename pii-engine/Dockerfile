FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-por poppler-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m spacy download pt_core_news_lg

COPY app/ /app/app/

# Nao roda como root: pii-engine processa conteudo de arquivo nao confiavel
# com uma cadeia de parsers (tesseract, poppler, py7zr, rarfile) com
# historico de CVE de memoria - um usuario de servico dedicado limita o
# raio de dano se algum desses parsers for explorado.
RUN useradd --create-home --uid 1001 --shell /usr/sbin/nologin farol && \
    chown -R farol:farol /app
USER farol
# /usr/local/lib nao e' gravavel por `farol` - pip cai automaticamente pra
# instalacao --user (ex: quando os testes instalam requirements-test.txt em
# tempo de execucao, ver README) e coloca o executavel aqui.
ENV PATH=/home/farol/.local/bin:$PATH

ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
