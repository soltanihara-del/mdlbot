# syntax=docker/dockerfile:1.10

ARG TELEGRAM_BOT_API_COMMIT=adfd7f6a8e990272851777eeb3ae0def4216f161

FROM debian:bookworm-slim AS telegram-builder
ARG TELEGRAM_BOT_API_COMMIT
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates cmake g++ git gperf make libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --filter=blob:none https://github.com/tdlib/telegram-bot-api.git . \
    && git checkout --detach "${TELEGRAM_BOT_API_COMMIT}" \
    && git submodule update --init --recursive --depth 1
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/telegram-bot-api \
    && cmake --build build --target install --parallel 2

FROM debian:bookworm-slim AS telegram-bot-api
ARG TELEGRAM_UID=10002
ARG TELEGRAM_GID=10002
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libssl3 libstdc++6 tini zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${TELEGRAM_GID}" telegram \
    && useradd --uid "${TELEGRAM_UID}" --gid "${TELEGRAM_GID}" --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin telegram \
    && install -d -o "${TELEGRAM_UID}" -g "${TELEGRAM_GID}" -m 0750 /var/lib/telegram-bot-api /var/tmp/telegram-bot-api
COPY --from=telegram-builder /opt/telegram-bot-api /opt/telegram-bot-api
COPY --chmod=0555 --chown=${TELEGRAM_UID}:${TELEGRAM_GID} docker/telegram-bot-api/entrypoint.sh /usr/local/bin/telegram-bot-api-entrypoint
USER ${TELEGRAM_UID}:${TELEGRAM_GID}
EXPOSE 8081
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/telegram-bot-api-entrypoint"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 CMD ["curl", "--silent", "--show-error", "--output", "/dev/null", "http://127.0.0.1:8081/"]
