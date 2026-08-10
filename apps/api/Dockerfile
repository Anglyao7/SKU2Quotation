# syntax=docker/dockerfile:1.7
FROM python:3.12.13-slim-bookworm AS runtime

ARG ATC_RELEASE=local
ARG ATC_COMMIT_SHA=unknown
ARG ATC_MIGRATION_HEAD=20260810_0075
ARG ATC_CONFIG_VERSION=container-default-v1
ARG PIP_VERSION=26.1.2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ATC_RELEASE=${ATC_RELEASE} \
    ATC_COMMIT_SHA=${ATC_COMMIT_SHA} \
    ATC_MIGRATION_HEAD=${ATC_MIGRATION_HEAD} \
    ATC_CONFIG_VERSION=${ATC_CONFIG_VERSION}

LABEL org.opencontainers.image.title="智贸云 API" \
      org.opencontainers.image.version="${ATC_RELEASE}" \
      org.opencontainers.image.revision="${ATC_COMMIT_SHA}" \
      org.opencontainers.image.vendor="智贸云"

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 atc \
    && useradd --uid 10001 --gid atc --create-home --shell /usr/sbin/nologin atc

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}" \
    && python -m pip install --no-cache-dir --requirement requirements.txt

COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY apps/api/app ./app
COPY apps/api/scripts ./scripts

RUN mkdir -p /app/var \
    && chown -R atc:atc /app

USER 10001:10001

FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3))['status']=='ok'"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

FROM runtime AS worker
CMD ["python", "-m", "scripts.run_product_event_consumer"]

FROM runtime AS migration
CMD ["alembic", "upgrade", "head"]
