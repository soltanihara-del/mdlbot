# syntax=docker/dockerfile:1.10

ARG REDIS_IMAGE=redis:7.4.9-bookworm
FROM ${REDIS_IMAGE}
COPY --chown=redis:redis docker/redis/redis.conf /etc/redis/redis.conf
COPY --chmod=0555 --chown=redis:redis docker/redis/entrypoint.sh /usr/local/bin/mdlbot-redis-entrypoint
COPY --chmod=0555 --chown=redis:redis docker/redis/healthcheck.sh /usr/local/bin/mdlbot-redis-healthcheck
USER redis
ENTRYPOINT ["/usr/local/bin/mdlbot-redis-entrypoint"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 CMD ["/usr/local/bin/mdlbot-redis-healthcheck"]
