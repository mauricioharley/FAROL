FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY coletor.py persistencia.py run.py main.py revisar.py ./

# Nao roda como root - mesmo padrao aplicado em pii-engine/painel (UID e
# nome iguais nos 3, por consistencia).
RUN useradd --create-home --uid 1001 --shell /usr/sbin/nologin farol && \
    chown -R farol:farol /app
USER farol
# /usr/local/lib nao e' gravavel por `farol` - pip cai automaticamente pra
# instalacao --user (ex: quando os testes instalam requirements-test.txt em
# tempo de execucao, ver README) e coloca o executavel aqui.
ENV PATH=/home/farol/.local/bin:$PATH

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
