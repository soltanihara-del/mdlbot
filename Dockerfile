# syntax=docker/dockerfile:1.10

ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS wheel-builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN python -m pip wheel --wheel-dir /wheels . \
    && python -m pip wheel --wheel-dir /wheels pytest==8.4.1 pytest-asyncio==1.0.0 PyYAML==6.0.2 httpx==0.28.1

FROM ${PYTHON_IMAGE} AS app-runtime
ARG APP_UID=10001
ARG APP_GID=10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/mdlbot/bin:${PATH}
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libmagic1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" mdlbot \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin mdlbot \
    && install -d -o "${APP_UID}" -g "${APP_GID}" -m 0750 /app /opt/mdlbot /srv/mdlbot
COPY --from=wheel-builder /wheels /wheels
RUN python -m venv /opt/mdlbot \
    && /opt/mdlbot/bin/pip install --no-index --find-links=/wheels mdlbot \
    && rm -rf /wheels
COPY --chmod=0555 --chown=${APP_UID}:${APP_GID} docker/app/entrypoint.sh /usr/local/bin/mdlbot-entrypoint
COPY --chown=${APP_UID}:${APP_GID} alembic.ini /app/alembic.ini
COPY --chown=${APP_UID}:${APP_GID} app/db/migrations /app/app/db/migrations
COPY --chown=${APP_UID}:${APP_GID} locales /app/locales
WORKDIR /app
USER ${APP_UID}:${APP_GID}
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/mdlbot-entrypoint"]

FROM app-runtime AS media-runtime
USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001

FROM postgres:16.13-bookworm AS postgres-client

FROM app-runtime AS backup-runtime
USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends liblz4-1 libpq5 libreadline8 libzstd1 openssl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=postgres-client /usr/lib/postgresql/16/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres-client /usr/lib/postgresql/16/bin/pg_restore /usr/local/bin/pg_restore
USER 10001:10001

FROM app-runtime AS test
USER root
COPY --from=wheel-builder /wheels /wheels
RUN /opt/mdlbot/bin/pip install --no-index --find-links=/wheels "mdlbot[test]" \
    && /opt/mdlbot/bin/pip install --no-index --find-links=/wheels PyYAML==6.0.2 \
    && rm -rf /wheels
COPY --chown=10001:10001 tests ./tests
USER 10001:10001
CMD ["pytest"]
