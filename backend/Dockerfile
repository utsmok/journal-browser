FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# uid 1000 matches the usual first host user, so the bind-mounted ./landing
# volume stays writable when the container runs non-root.
RUN useradd --create-home --uid 1000 app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev && chown -R app:app /app

USER app

EXPOSE 8000

# Migrations run at container start so `docker compose up` is self-contained.
CMD ["sh", "-c", "uv run --no-dev alembic upgrade head && uv run --no-dev uvicorn journal_browser.main:app --host 0.0.0.0 --port 8000"]
