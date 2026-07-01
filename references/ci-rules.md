# CI rules — GitHub Actions & GitLab CI

## HIGH — `secret-echoed`: secrets written to build logs

**Detects:** `echo` combined with `${{ secrets.* }}` (Actions) or `$VAR` names
containing SECRET/TOKEN/PASSWORD/KEY (both platforms).

**Why it kills prod:** Build logs are readable by everyone with repo access,
retained for months, and often shipped to third-party log aggregators. GitHub
masks known secret values in logs, but masking fails on transformed values
(base64, substrings, JSON-embedded) — never rely on it.

**Fix:** pass secrets via `env:` to the step that needs them; never interpolate
them into shell strings that get printed.

```yaml
- name: Deploy
  env:
    DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
  run: ./scripts/deploy.sh   # reads $DEPLOY_TOKEN, never prints it
```

## MEDIUM — `missing-needs`: deploy job without `needs:`

**Detects:** 2+ jobs where a job named deploy/release/publish/prod* has no
`needs:` (GitHub Actions).

**Why:** Jobs run **in parallel** by default. Without `needs:`, deploy starts
immediately — it can finish deploying broken code before the test job reports
failure.

**Fix:**
```yaml
deploy:
  needs: [test, build]
  runs-on: ubuntu-latest
```

## MEDIUM — `no-ci-caching`: no dependency or Docker layer caching

**Detects:** `npm/yarn/pnpm install`, `pip install`, `bundle install`, or
`docker build` with no `actions/cache`, `cache:` key, or `--cache-from`.

**Why:** Every run downloads the world. On a busy repo this is minutes per run,
multiplied by every push — slow feedback and wasted runner minutes.

**Fix (Actions — node):**
```yaml
- uses: actions/setup-node@v4
  with:
    node-version: 22
    cache: npm          # one line — caches ~/.npm keyed on package-lock.json
```

**Fix (Actions — Docker):**
```yaml
- uses: docker/build-push-action@v6
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

**Fix (GitLab):**
```yaml
cache:
  key:
    files: [package-lock.json]
  paths: [.npm/]
```

## LOW — `draft-pr-full-pipeline`: draft PRs run everything

**Detects:** `pull_request:` trigger with no `pull_request.draft` condition and
no `ready_for_review` type filter.

**Why:** Work-in-progress pushes burn full pipeline minutes on code the author
knows isn't ready.

**Fix:**
```yaml
jobs:
  test:
    if: github.event.pull_request.draft == false
```
or trigger only on readiness:
```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
```
