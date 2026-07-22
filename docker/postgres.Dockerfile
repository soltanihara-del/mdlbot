# syntax=docker/dockerfile:1.10

ARG POSTGRES_IMAGE=postgres:16.13-bookworm
FROM ${POSTGRES_IMAGE}
COPY --chmod=0555 docker/postgres/initdb/00-security-roles.sh /docker-entrypoint-initdb.d/00-security-roles.sh
