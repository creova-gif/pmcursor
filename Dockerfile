# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY src/ ./src/
COPY api/ ./api/
COPY web/ ./web/
COPY indexer/ ./indexer/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install ".[server]"


FROM python:3.12-slim AS runtime

ENV PYTHONPATH="/app/src:/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system pmcursor \
    && useradd --system --gid pmcursor --create-home --home-dir /home/pmcursor pmcursor \
    && mkdir -p /orgs && chown pmcursor:pmcursor /orgs

COPY --from=builder /install /usr/local
COPY --chown=pmcursor:pmcursor pyproject.toml ./
COPY --chown=pmcursor:pmcursor src/ ./src/
COPY --chown=pmcursor:pmcursor api/ ./api/
COPY --chown=pmcursor:pmcursor web/ ./web/
COPY --chown=pmcursor:pmcursor indexer/ ./indexer/

USER pmcursor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
