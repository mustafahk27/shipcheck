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

Individual stages, if ever needed separately:
- `scripts/scan.py <root>` — JSON list of discovered infra files with types
- `scripts/rules.py <root>` — JSON of scanned files + findings

## Workflow

1. Run the report command above against the user's repo root and show the output.
2. If the user asks why a finding matters or how to fix it properly, load the
   matching reference for full context and remediation patterns:
   - `references/docker-rules.md` — Dockerfile + docker-compose rules
   - `references/k8s-rules.md` — Kubernetes manifest rules
   - `references/ci-rules.md` — GitHub Actions / GitLab CI rules
   - `references/secrets-patterns.md` — secret-detection regexes and rotation guidance
3. After showing the report, offer to:
   - generate `shipcheck-report.md` for PR attachment (re-run with `--export`)
   - fix the findings directly (start with CRITICAL, then HIGH)
4. If the user passed `--export` (e.g. `/shipcheck --export`), run with the flag immediately.

## Interpreting findings

- **CRITICAL** (hardcoded secrets, committed .env) — block the deploy. Any exposed
  credential must be **rotated**, not just removed: it lives in git history.
- **HIGH** (root containers, :latest, no healthcheck, no resource limits, echoed secrets) — fix before shipping.
- **MEDIUM/LOW** — quality and speed; fix opportunistically.

False positives happen (e.g. example values that look like credentials). When a
secret finding looks like a placeholder, say so rather than demanding rotation —
but verify by reading the flagged line first.
