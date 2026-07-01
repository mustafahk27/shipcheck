# Docker rules — Dockerfile & docker-compose

## HIGH — `unpinned-latest`: `:latest` or missing tag

**Detects:** `FROM node:latest`, `FROM node`, `image: postgres:latest`, `image: redis`

**Why it kills prod:** `:latest` is a moving target. The image you tested is not
the image you deploy — a rebuild next week silently pulls a new major version.
Rollbacks become impossible because "latest" no longer means what it meant.

**Fix:**
```dockerfile
FROM node:22.12-alpine
```
```yaml
image: postgres:16.4
```

## HIGH — `runs-as-root`: no non-root USER

**Detects:** Dockerfile with no `USER` directive (or only `USER root`).

**Why:** A compromised process owns the container, and container escapes are far
easier from root. Most base images ship a ready-made user.

**Fix:**
```dockerfile
# node images ship a "node" user:
USER node
# or create one:
RUN addgroup -S app && adduser -S app -G app
USER app
```

## HIGH — `no-healthcheck`: missing HEALTHCHECK

**Detects:** Dockerfile with no `HEALTHCHECK` instruction.

**Why:** Without it, Docker/Swarm/compose consider a wedged process "running"
forever. Orchestrators can't restart what they can't see failing.

**Fix:**
```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1
```

## LOW — `no-digest-pin`: base image not pinned to digest

**Detects:** `FROM` without `@sha256:...`.

**Why:** Even a version tag can be re-pushed upstream (tag mutation / supply-chain
drift). A digest is immutable.

**Fix:**
```dockerfile
FROM node:22.12-alpine@sha256:9fcc1a6da2b9eee38638df75c5f826e06e9c79f6a0f97f16ed617b2ec5c8a969
```
Get the digest with `docker buildx imagetools inspect node:22.12-alpine`.

## MEDIUM — `no-restart-policy` (compose)

**Detects:** a service with neither `restart:` nor `deploy:` (swarm restart_policy).

**Why:** After a crash or host reboot the service stays down until a human notices.

**Fix:**
```yaml
services:
  api:
    restart: unless-stopped
```

## MEDIUM — `exposed-port` (compose)

**Detects:** database/cache ports published to the host: 5432 (PostgreSQL),
3306 (MySQL), 27017 (MongoDB), 6379 (Redis), 9200 (Elasticsearch),
11211 (Memcached), 2375 (Docker daemon), 5984 (CouchDB). Bindings to
`127.0.0.1` are not flagged.

**Why:** `"5432:5432"` binds to 0.0.0.0 — your database is reachable from the
internet on an unfirewalled host. Containers on the same compose network don't
need published ports to talk to each other.

**Fix:**
```yaml
# best: no mapping at all — other services reach db:5432 via the network
# if host access is genuinely needed:
ports:
  - "127.0.0.1:5432:5432"
```
