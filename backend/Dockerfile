FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# uid 1000 matches the usual first host user, so the bind-mounted ./landing
# volume stays writable when the container runs non-root.
RUN useradd --create-home --uid 1000 app

# Runtime tooling outside Python, installed before the dependency layers so
# rebuilds of the deps below never redo it:
# - tzdata: the scheduler's cron schedules follow the container TZ.
# - postgresql-client-17 (PGDG): nightly pg_dump/pg_restore must match the
#   db service's Postgres major; Debian bookworm's own client stops at 15.
# - supercronic: runs the scheduler crontab; release binary, checksum-verified.
# - git: uv fetches the bibliofabric packages from git sources until they
#   are released on PyPI (see [tool.uv.sources] in pyproject.toml).
ARG SUPERCRONIC_VERSION=v0.2.51
ARG SUPERCRONIC_SHA256=cc232108374e8e2b537045f2d5eaa1229f619db314c3ba6a14d38b35dc0aa123
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg tzdata \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && curl -fsSL "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
        -o /usr/local/bin/supercronic \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/supercronic \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev && chown -R app:app /app

# Pre-fetch the ONNX query-encoding model so the first semantic search needs
# no network at runtime (services/embeddings.py encode_query loads lazily).
ENV FASTEMBED_CACHE_PATH=/app/.fastembed
RUN uv run --no-dev python -c "from fastembed import TextEmbedding; list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5').embed(['warmup']))" \
    && chown -R app:app /app

USER app

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Migrations run at container start so `docker compose up` is self-contained.
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev uvicorn journal_browser.main:app --host 0.0.0.0 --port 8000"]
