# Stage 8 — secure streaming and media processing

Stage 8 adds browser players, direct Range-capable streaming, isolated media
processing, and optional HLS video-on-demand output. Download and stream
credentials remain cryptographically and operationally separate.

## Request flow

1. The bot creates a 256-bit opaque stream token after checking file ownership,
   plan streaming access, and concurrent-session limits.
2. `/watch/{token}` or `/listen/{token}` renders a no-script player. When an HLS
   variant is ready it is offered first, with the progressive stream as fallback.
3. `/stream/{token}` and `/hls/{token}/{sequence}.ts` bind the first request to a
   hashed IP and user-agent, enforce the per-plan connection ceiling in Redis,
   and return an internal Nginx redirect.
4. Nginx serves object, media, and HLS volumes only through `internal` locations.
   Application telemetry headers are removed before the response leaves Nginx.
5. The structured access log replaces all stream, player, HLS, download, and
   webhook capabilities with `[redacted]`; the usage collector attributes bytes
   and releases the connection counter idempotently.

## Media worker boundary

`media-worker` has no PostgreSQL, Redis, Telegram, download-signing, or internal
service credential. It receives only its `media_worker_token`, reaches only the
API control plane on `application_network`, reads `/srv/storage/objects` as
read-only, and writes `/srv/storage/media` and `/srv/storage/hls`.

The worker:

- rejects absolute paths, traversal, symlinks, and non-regular source files;
- invokes FFprobe and FFmpeg with an argument vector and never through a shell;
- bounds probe output, metadata fields, process output, and execution time;
- removes source metadata and maps only the primary video/audio streams;
- writes to job-owned temporary paths and atomically publishes completed output;
- records sanitized codecs, dimensions, duration, variants, and every HLS segment
  in PostgreSQL through the authenticated worker control API.

Container memory, CPU, PID, no-new-privileges, read-only-root, and dropped
capability limits provide the outer resource boundary. HLS segment length,
probe timeout, processing timeout, and transcoding/HLS switches are captured in
the immutable admission policy snapshot so a running job cannot change policy
mid-flight.

## Secret mounts

The public deployment contract intentionally documents secret filenames and
mounts, never values:

| Service | Secret mount |
|---|---|
| API | `/run/secrets/media_worker_token` |
| media-worker | `/run/secrets/media_worker_token` |
| API, bot, usage collector | `/run/secrets/stream_signing_key` |

`stream_signing_key` and `download_signing_key` must be different 32-byte keys,
hex encoded. All four worker pool tokens must also be distinct.

## Verification

The local suite covers worker credential scope, traversal rejection, result
schema validation, metadata sanitization, direct-play decisions, HLS playlist
validation, API behavior, Compose isolation, and the existing platform
contracts. A local FFmpeg smoke test generated an actual MP4 fixture and HLS
segments. Live Nginx Range/HLS behavior still requires the deployed stack and is
part of the final server acceptance procedure.
