# syntax=docker/dockerfile:1.7
ARG SOURCE_DATE_EPOCH=0
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv
FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS build

ARG SOURCE_DATE_EPOCH
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && rm /app/.venv/lib/python3.12/site-packages/stateback-0.1.0.dist-info/uv_cache.json \
    && sed -i '\|stateback-0.1.0.dist-info/uv_cache.json|d' \
        /app/.venv/lib/python3.12/site-packages/stateback-0.1.0.dist-info/RECORD

FROM python:3.12.14-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134
ARG SOURCE_DATE_EPOCH
ARG STATEBACK_SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="Stateback" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.source="https://github.com/mominrkhan/stateback" \
      org.opencontainers.image.revision="${STATEBACK_SOURCE_REVISION}" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --gid 10001 stateback \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin stateback
WORKDIR /app
COPY --from=build --chown=stateback:stateback /app/.venv /app/.venv
COPY --chown=stateback:stateback alembic.ini ./
COPY --chown=stateback:stateback alembic ./alembic
COPY --chown=stateback:stateback LICENSE /licenses/LICENSE
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["stateback"]
CMD ["api"]
