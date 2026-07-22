# Stage 3 — Container and edge infrastructure

**Project:** `mdlbot`  
**Scope:** Dockerfiles, Compose topology, networks, volumes, secret delivery,
Nginx, and container security profiles only

Stage 3 implements the infrastructure contract established in Stage 1. It
does not implement the Stage 4 application runtime, Stage 6 workers, Stage 7
download authorization, or Stage 10 backup/installer logic. Compose commands
for those services are stable interfaces for the subsequent stages; those
containers become runnable when their corresponding application modules are
implemented.

## 1. Pinned build inputs

| Component | Pin |
|---|---|
| Python | `python:3.12.13-slim-bookworm` |
| PostgreSQL | `postgres:16.13-bookworm` |
| Redis | `redis:7.4.9-bookworm` |
| Nginx | `nginx:1.30.4-alpine3.24` |
| ClamAV | `clamav/clamav:1.4.5-debian13-slim` |
| Prometheus LTS | `prom/prometheus:v3.5.5` |
| Grafana | `grafana/grafana:13.1.1-ubuntu` |
| Telegram Local Bot API | source commit `adfd7f6a8e990272851777eeb3ae0def4216f161` (`10.2`) |

Application images use a wheel-building stage. Compilers and Git are absent
from runtime images. The media target adds only FFmpeg/FFprobe. The Local Bot
API target builds the official repository at an immutable commit and copies
only installed artifacts into its runtime image.

Exact tags prevent accidental major-version movement. A production release
pipeline must additionally resolve and record multi-architecture image
digests after registry verification; hard-coding one architecture's digest in
this multi-architecture source would make ARM and AMD64 deployments diverge.

## 2. Service and network isolation

| Network | Internet route | Members with special significance |
|---|---:|---|
| `public_network` | yes | Nginx only; the only network with published ports |
| `application_network` | no | Internal HTTP control plane |
| `database_network` | no | PostgreSQL, Redis, and approved stateful services |
| `telegram_network` | yes | Local Bot API and Telegram-facing services |
| `media_network` | no | API and media worker control path |
| `scanner_network` | no | File-producing workers and optional ClamAV |
| `external_download_network` | yes | External downloader and API report address only |

The external downloader is statically assigned `172.29.60.20`; the API report
listener is `172.29.60.10`. The downloader has neither database credentials
nor database/Telegram network membership. The Stage 10 host installer must
apply nftables or `DOCKER-USER` rules to this subnet, because Docker network
membership alone cannot prevent SSRF to addresses reachable through the host's
default route. The required deny set includes loopback, private, link-local,
CGNAT, multicast, reserved/documentation, metadata, Docker, and host networks.

The media worker belongs only to internal networks, so it has no default
internet route. Nginx is the sole host publisher (`80` and `443`); PostgreSQL,
Redis, Local Bot API, ClamAV, Prometheus, Grafana, workers, and the API publish
no host ports.

## 3. Persistent and ephemeral storage

Named volumes separate PostgreSQL, Redis, Telegram Local Bot API data, original
objects, derived media, HLS segments, quarantine, Nginx accounting logs,
encrypted backups, ACME challenges, malware definitions, and monitoring data.
Nginx receives original/media/HLS volumes read-only. Telegram upload receives
originals read-only. The usage collector receives Nginx logs read-only.

Writable process scratch paths are size-bounded `tmpfs` mounts with
`noexec,nosuid,nodev`. Application roots are read-only. User files never enter
the image, application directory, or a public Nginx document root.

## 4. Secret handling

Compose mounts one file per secret under `/run/secrets`. Values never appear in
Compose environment values or command arguments. Entry points validate files,
reject symbolic links, suppress values in logs, and construct encoded database
and Redis URLs only inside the process environment. Redis authentication is
written to a mode-`0600` configuration on a private tmpfs rather than passed on
its command line.

The complete secret inventory and safe generation procedure are in
`docker/secrets/README.md`. The ignored deployment directory is `./secrets`.
The Stage 10 installer will automate interactive collection, permissions, and
rotation; Stage 3 intentionally does not create real credentials.

## 5. Nginx security and delivery contract

Nginx runs as UID/GID `101`, listens inside the container on unprivileged ports
`8080/8443`, and is mapped to host `80/443`. Startup fails when the domain,
webhook path, or TLS files are invalid or unavailable. Unknown hostnames receive
connection close status `444`; HTTP for the configured host redirects to HTTPS.

The edge enables TLS 1.2/1.3, disables session tickets and version disclosure,
adds HSTS/CSP and other browser headers, bounds header/body timeouts and sizes,
limits connections and requests, and accepts at most one byte range. It trusts
no forwarded-client header by default. Trusted proxy CIDRs may be compiled into
the image only after operator verification.

Application routes validate download/stream sessions. After authorization,
the API returns an `X-Accel-Redirect` to one of three `internal` aliases:
original objects, derived media, or HLS. Clients cannot address those locations
directly. Daily-rolled structured JSON logs include request/session
identifiers, response bytes, timings, and status for the Stage 7 usage
collector. Stage 7 owns post-ingestion retention and deletion of old daily
files; Docker's JSON log driver independently rotates the stdout copy.

TLS files are ordinary, non-symlink copies at `runtime/tls/fullchain.pem` and
`runtime/tls/privkey.pem`, readable by UID `101`. Certificate issuance and the
atomic renewal hook belong to Stage 10. This avoids running a privileged ACME
client inside the public edge container.

## 6. Container hardening

Every Compose service has a read-only root, all Linux capabilities dropped,
`no-new-privileges`, Docker's default seccomp allow-list, PID/CPU/memory/file
descriptor bounds, health checks where the process contract exists, graceful
stop windows for stateful services, and rotated Docker logs. No service is
privileged, uses host networking, mounts the Docker socket, or receives a broad
host filesystem mount.

`docker-compose.production.yml` opts application, downloader, media, and Nginx
services into four AppArmor profiles. Profile loading instructions are in
`docker/security/README.md`. PostgreSQL, Redis, Telegram, ClamAV, Prometheus,
and Grafana retain their vendor-compatible AppArmor/default-Docker profile plus
the Compose capability and seccomp controls.

## 7. Deployment preparation and validation

Prepare non-secret configuration and credentials:

```bash
cp .env.example .env
install -d -m 0700 secrets runtime/tls
```

Follow `docker/secrets/README.md`, copy non-symlink TLS files into
`runtime/tls`, set owner `101:101`, directory mode `0700`, certificate mode
`0444`, and private-key mode `0400`. Then validate and build:

```bash
docker compose --env-file .env --profile local-bot-api config --quiet
docker compose --env-file .env --profile local-bot-api build --pull
docker compose --env-file .env --profile operations run --rm migrate
docker compose --env-file .env --profile local-bot-api up -d
```

On AppArmor-enabled Linux, add `-f docker-compose.production.yml` to the Compose
commands after loading the profiles. Add `--profile clamav` and/or
`--profile monitoring` to enable those optional services.

To use Telegram's official cloud Bot API, set:

```dotenv
TELEGRAM_API_MODE=official
TELEGRAM_API_BASE_URL=https://api.telegram.org
```

and omit `--profile local-bot-api`. The Stage 4 capability registry must apply
the stricter cloud limits. Local mode remains the recommended production mode.

In the current authoring environment, Docker Engine, Nginx, AppArmor parser,
and ShellCheck are unavailable. Therefore container builds, Compose's own
schema expansion, Nginx runtime parsing, and live AppArmor loading are not
claimed as executed here. Stage 3's automated tests parse YAML, enforce service
and network boundaries, detect embedded secrets/unpinned `latest` images,
check POSIX shell syntax, and inspect the Nginx delivery contract. A deployment
is not accepted until the four Docker commands above and host security checks
succeed on the target Linux host.
