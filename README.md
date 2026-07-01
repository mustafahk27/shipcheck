# 🚢 shipcheck

![rules](https://img.shields.io/badge/rules-13-blue) ![file types](https://img.shields.io/badge/file%20types-7-brightgreen) ![python](https://img.shields.io/badge/python-3.9%2B%20stdlib%20only-yellow)

**Pre-deployment infrastructure auditor for [Claude Code](https://claude.com/claude-code).**
Run `/shipcheck` and get a color-coded terminal report of everything that could kill prod — before it ships.

Scans **Dockerfiles · docker-compose · Kubernetes manifests · GitHub Actions · GitLab CI · nginx configs · .env files**.

## Demo

Run against the intentionally broken files in [`demo/`](demo/):

```
🚢 shipcheck — pre-flight audit
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scanned: 3 files  |  Issues: 21  |  Clean: 0

🔴 [CRITICAL] bad-dockerfile:9
   Hardcoded OpenAI API key detected: sk-proj...
   💡 Fix: Move to an environment variable or secret manager; rotate the exposed credential

🟠 [HIGH] bad-compose.yml:15
   Service "db" uses `postgres:latest` — :latest/no tag is not reproducible
   💡 Fix: Pin to a specific version tag

🟡 [MEDIUM] bad-workflow.yml:28
   Job "deploy" has no `needs:` — it can deploy before tests finish (jobs run in parallel)
   💡 Fix: Add `needs: [test, build]` so deploy waits for upstream jobs

🔵 [LOW] bad-dockerfile:4
   Base image `node:latest` not pinned to a digest — tag contents can change upstream
   💡 Fix: Pin to a digest: `node:latest@sha256:<digest>`

🔴 5 critical  🟠 7 high  🟡 8 medium  🔵 1 low
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run `/shipcheck --export` to save as shipcheck-report.md
```

<!-- TODO: replace with terminal screenshot/gif: FORCE_COLOR=1 python3 scripts/report.py demo -->

## Install

**Local (any project, no GitHub needed):**

```bash
mkdir -p .claude/skills && cp -r path/to/shipcheck .claude/skills/shipcheck
```

**From GitHub:**

```bash
claude plugin install mustafahk27/shipcheck
```

Then in Claude Code:

```
/shipcheck              # audit the current repo
/shipcheck --export     # also write shipcheck-report.md for PR attachment
```

Or run it standalone — no Claude required, no dependencies (pure stdlib):

```bash
python3 scripts/report.py /path/to/repo        # exits 1 on CRITICAL/HIGH → CI-gate friendly
```

## Rules

| Severity | Rule | Applies to |
|---|---|---|
| 🔴 CRITICAL | Hardcoded secrets / tokens (OpenAI, AWS, GitHub, Slack, npm, Stripe, Google, private keys, generic) | all files |
| 🔴 CRITICAL | `.env` committed to git (or not gitignored) | git |
| 🟠 HIGH | Unpinned `:latest` / missing image tag | Dockerfile, compose |
| 🟠 HIGH | Container runs as root (no `USER`) | Dockerfile |
| 🟠 HIGH | Missing `HEALTHCHECK` | Dockerfile |
| 🟠 HIGH | No CPU/memory resource limits | K8s |
| 🟠 HIGH | Secrets echoed into build logs | Actions, GitLab |
| 🟡 MEDIUM | No restart policy | compose |
| 🟡 MEDIUM | Database/cache ports published to host | compose |
| 🟡 MEDIUM | Deploy job missing `needs:` | Actions |
| 🟡 MEDIUM | No dependency / Docker layer caching | Actions, GitLab |
| 🔵 LOW | Base image not pinned to digest | Dockerfile |
| 🔵 LOW | Draft PRs run the full pipeline | Actions |

Full rationale and remediation patterns live in [`references/`](references/).

## How it works

```
scan.py  →  finds infra files (type detection by name + content)
rules.py →  runs every rule, emits findings JSON with exact line numbers
report.py → renders the terminal report / markdown export
```

Pure Python stdlib — no PyYAML, no pip install. Line-based parsing keeps exact
line numbers in every finding.

## Contributing rules

New rule ideas welcome — [open a PR](../../pulls). A rule needs:

1. A check in `scripts/rules.py` (severity, message, one-line fix)
2. A demo trigger in `demo/` so it's visible in the showcase
3. A rationale entry in the matching `references/*.md`

## License

MIT
