# Pinned by digest, like the Python dependencies are by hash, so a rebuild
# gets the image CI tested rather than whatever the tag points at that day.
# Refresh it to pick up base-image security fixes: the digest is the
# "docker-content-digest" of the 3.12-slim manifest list on Docker Hub
# (e.g. `docker buildx imagetools inspect python:3.12-slim`).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app

# No apt packages: the install is wheels-only, and the lxml wheel bundles its
# own libxml2/libxslt, so the -dev headers this used to install were never used.

# requirements.txt is the hash-locked resolution of requirements.in (see its
# header for the uv command that regenerates it). Wheels only, so no sdist
# setup.py runs during the build, and every artifact must match its pinned hash.
COPY apps/worker/requirements.txt .
RUN pip install --no-cache-dir --only-binary :all: --require-hashes -r requirements.txt

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
# platforms that honour HEALTHCHECK (plain `docker run`) get one too. Probes
# $PORT when the platform sets one (Railway does), as the server below listens
# there; it used to probe 8000 regardless.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://localhost:%s/health' % os.environ.get('PORT', '8000'),timeout=3))['status']=='ok' else 1)"]

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
