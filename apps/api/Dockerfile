FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TIKTOKEN_CACHE_DIR=/app/tokenizer-cache

WORKDIR /app

RUN pip install --no-cache-dir uv==0.11.25

COPY pyproject.toml uv.lock alembic.ini ./
COPY src ./src
COPY alembic ./alembic

RUN uv sync --frozen --no-dev \
    && uv run --frozen --no-dev python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

EXPOSE 8000

CMD ["sh", "-c", "uv run --frozen --no-dev alembic upgrade head && uv run --frozen --no-dev uvicorn aftercare_api.main:app --host 0.0.0.0 --port 8000"]
