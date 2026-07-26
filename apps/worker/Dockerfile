FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev && rm -rf /var/lib/apt/lists/*

COPY apps/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
# Lands at /app/schemas, which is what app/core/paths.py resolves to.
COPY schemas/ ./schemas/
COPY apps/worker/app/ ./app/

# Unprivileged runtime user. DATA_DIR is created and owned even though the
# worker no longer reads it (payloads travel over HTTP) so a mounted volume
# doesn't land root-owned and unwritable.
RUN useradd --create-home --uid 10001 worker \
    && mkdir -p /data \
    && chown -R worker:worker /app /data
USER worker

EXPOSE 8000
# stdlib probe: this image has no curl. Mirrors the compose healthcheck so
# platforms that honour HEALTHCHECK (plain `docker run`) get one too.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:8000/health',timeout=3))['status']=='ok' else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
