# Stage 6 — Durable queue, workers, progress, and quota

Stage 6 connects the bilingual intake flow to durable PostgreSQL jobs, atomic multi-window quota reservations, a fair dispatcher, Redis Streams transport, and isolated download/upload workers. PostgreSQL remains authoritative; Redis contains dispatch transport and temporary progress only.

## Delivered flow

1. Telegram file or external URL intake validates the source and creates one idempotent job inside the same transaction as its quota reservations and policy snapshot.
2. The dispatcher locks eligible PostgreSQL rows with `SKIP LOCKED`, applies separate normal/VIP lanes, priority aging, a maximum normal wait, and a maximum consecutive VIP ratio.
3. Dispatch generation and a random lease hash are persisted before an outbox event publishes the one-time raw lease to the correct Redis Stream.
4. A pool-specific worker claims the message, and the API validates its credential, job type, generation, lease, expiry, stream, consumer group, and exact persisted Redis message ID.
5. Workers report real transferred bytes. PostgreSQL reservations are atomically topped up and Redis stores both the latest snapshot and a bounded progress stream.
6. The bot progress consumer edits the original queue message in the user's stored Persian or English language.
7. Completion persists the file, reference, immutable events, attempt outcome, and actual quota usage in one transaction before acknowledging Redis.

External downloads re-resolve every redirect, reject non-global addresses, pin all accepted DNS answers, disable automatic redirects/decompression, bound headers and timeouts, enforce the policy size while streaming, write to job-owned temporary storage, hash content, optionally scan with ClamAV, and atomically expose a completed object.

Telegram downloads support both regular Bot API file URLs and Local Bot API absolute paths. Local paths must resolve under the mounted Telegram data root and be regular non-symlink files.

When an external file fits the policy snapshot's active Telegram capability, completion schedules one idempotent `telegram_upload` child job. The upload worker rechecks containment, symlink status, exact on-disk size, and the capability limit immediately before streaming a known-length multipart upload with real progress. Larger files are never submitted to Telegram and continue to the Stage 7 direct-link path.

## Failure and recovery properties

- Worker credentials are distinct per pool. The external worker has neither bot token nor PostgreSQL/Redis credentials and cannot join internal application or Telegram networks.
- Attempts and dispatch generations prevent duplicate execution. Exhausted jobs become dead letters and release or commit their reservations according to transferred bytes.
- Lease expiry produces an explicit failed transition before retry or dead-letter routing. Redis replays after a committed completion are rejected by the durable state and acknowledged.
- Active workers extend reservation expiry on heartbeat. Expired reservations without a valid lease terminate the stale job before reconciliation, preventing a released reservation from later running without quota.
- A malware result other than the captured scan policy's accepted state fails closed and never creates an available file record.
- The raw lease is removed from the outbox payload immediately after successful publication. Completion/failure reports must match the published outbox message ID.

## Verification record

The complete local suite completed with 90 passing tests and one skipped destructive PostgreSQL test because `TEST_DATABASE_URL` was not configured. Stage 6 coverage includes SSRF/numeric-host rejection, public-address classification, URL normalization, quota-window boundaries, VIP fairness and starvation limits, worker credential separation, typed completion payloads, storage traversal rejection, content-based MIME detection, DNS pinning, and Compose least-privilege boundaries.

Python compilation and all dependency-independent tests were executed. Docker Engine, PostgreSQL, Redis, Telegram credentials, and ClamAV were unavailable in the authoring environment, so live container orchestration, destructive migration, real Telegram transfer, and malware-daemon checks are not claimed as executed. The Stage 10 installer treats those as deployment acceptance gates.
