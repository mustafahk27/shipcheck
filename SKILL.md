---
name: shipcheck
description: Use when the user wants a pre-deployment infrastructure audit — says "shipcheck", "check my infra", "ready to deploy?", "audit my configs", or is about to deploy. Scans Dockerfiles, docker-compose, K8s manifests, GitHub Actions/GitLab CI, nginx configs, and .env files for secrets, misconfigurations, and quality problems.
---

# shipcheck — pre-flight infrastructure audit

Audits the repo's infrastructure files before deployment and renders a
color-coded terminal report of everything that could kill prod.

## How to run

Everything is one command — it discovers files, runs all rules, and renders
the report (scan → rules → report are chained internally):

```bash
FORCE_COLOR=1 python3 {skill_dir}/scripts/report.py <repo-root>
```

- `<repo-root>` defaults to `.` — use the user's current project root, NOT the skill directory.
- Exit code 1 means CRITICAL or HIGH findings exist (useful for CI gating); it is not an error.
- Print the script's output verbatim — it is already formatted with colors and emoji.

Flags:
- `--export` — additionally writes `shipcheck-report.md` (markdown table, PR-ready) into the repo root
- `--json` — raw findings JSON instead of the report (use this when you need to act on findings programmatically)
- `--fix` — apply safe deterministic fixes first, then report what remains (see Auto-fix below)

Individual stages, if ever needed separately:
- `scripts/scan.py <root>` — JSON list of discovered infra files with types
- `scripts/rules.py <root>` — JSON of scanned files + findings
- `scripts/fix.py <root> [--dry-run]` — apply (or preview) the deterministic fixes only

## Workflow

1. Run the report command above against the user's repo root and show the output.
2. If the user asks why a finding matters or how to fix it properly, load the
   matching reference for full context and remediation patterns:
   - `references/docker-rules.md` — Dockerfile + docker-compose rules
   - `references/k8s-rules.md` — Kubernetes manifest rules
   - `references/ci-rules.md` — GitHub Actions / GitLab CI rules
   - `references/secrets-patterns.md` — secret-detection regexes and rotation guidance
3. After showing the report, offer to:
   - auto-fix the mechanical findings (re-run with `--fix`)
   - generate `shipcheck-report.md` for PR attachment (re-run with `--export`)
   - fix the remaining findings directly (start with CRITICAL, then HIGH)
4. If the user passed `--export` or `--fix` (e.g. `/shipcheck --fix`), run with the flag immediately.

## Auto-fix

Two tiers. `--fix` applies **tier 1** — deterministic edits that cannot break
behavior in a bad way:

- add `restart: unless-stopped` to compose services
- bind published database/cache ports to `127.0.0.1`
- add `needs: [<upstream jobs>]` to deploy jobs
- gate workflow jobs with `if: github.event.pull_request.draft == false`
- add `.env` to `.gitignore`

**Tier 2** is you. After `--fix`, the report lists findings that need judgment —
fix them by editing the files yourself, per the references:

- `unpinned-latest` / `no-digest-pin` — pick a concrete current version tag for
  the image (check what major version the project actually uses before pinning)
- `runs-as-root` — add a `USER`; verify the app doesn't need root-owned paths first
- `no-healthcheck` — write a HEALTHCHECK against the app's real port/endpoint
- `hardcoded-secret` — replace the literal with an env reference, add the var to
  the right secret store, and TELL THE USER the old value must be rotated
- `no-ci-caching` — add the cache config that matches their setup (setup-node
  `cache:`, actions/cache, buildx `--cache-from`)

Show a diff of what you changed, then re-run the report to prove the findings
are gone. Never fix `hardcoded-secret` by just deleting the line — the value
lives in git history; rotation is the fix.

## Interpreting findings

- **CRITICAL** (hardcoded secrets, committed .env) — block the deploy. Any exposed
  credential must be **rotated**, not just removed: it lives in git history.
- **HIGH** (root containers, :latest, no healthcheck, no resource limits, echoed secrets) — fix before shipping.
- **MEDIUM/LOW** — quality and speed; fix opportunistically.

False positives happen (e.g. example values that look like credentials). When a
secret finding looks like a placeholder, say so rather than demanding rotation —
but verify by reading the flagged line first.
