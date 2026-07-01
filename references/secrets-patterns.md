# Secret detection patterns

shipcheck scans **every** discovered infra file for these, regardless of type.
Comments (`#`, `//`) are skipped. Matched values are redacted in the report
(first 7 chars + `...`).

## Provider-specific token formats

| Provider | Pattern |
|---|---|
| OpenAI | `sk-(?:proj-)?[A-Za-z0-9_-]{20,}` |
| AWS access key | `AKIA[0-9A-Z]{16}` |
| GitHub (PAT/OAuth/app) | `gh[pousr]_[A-Za-z0-9]{36,}` |
| Slack | `xox[baprs]-[A-Za-z0-9-]{10,}` |
| npm | `npm_[A-Za-z0-9]{36,}` |
| Stripe live | `[sr]k_live_[A-Za-z0-9]{20,}` |
| Google API | `AIza[0-9A-Za-z_-]{35}` |
| Private key blocks | `-----BEGIN (RSA \|EC \|OPENSSH )?PRIVATE KEY-----` |

## Generic credential assignment

Key names containing `PASSWORD`, `PASSWD`, `SECRET`, `TOKEN`, `API_KEY`/`API-KEY`,
`PRIVATE_KEY` assigned a literal value of 8+ chars:

```
(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_]*)\s*[:=]\s*['"]?([^\s'"#]{8,})
```

## Suppressed (never flagged)

Values that are references or obvious placeholders:

- `$VAR`, `${VAR}` — shell/compose interpolation
- `{{ ... }}` — templating (Actions `${{ secrets.X }}`, Helm, Ansible)
- `%VAR%`, `<placeholder>` forms
- `changeme`, `placeholder`, `example`, `your-*`, `xxx…`, `***`, `none`, `null`, `true`, `false`
- `.env.example` files are skipped entirely by the scanner

## `.env` committed — CRITICAL `env-committed`

| Situation | Verdict |
|---|---|
| `.env` tracked by git | committed — every value lives in history **forever**; removal is not enough |
| `.env` untracked, not gitignored | one `git add .` away from the above |
| `.env` untracked and gitignored | clean, not reported |
| no git repo | warned — add `.gitignore` before `git init` |

## When a secret is confirmed exposed

1. **Rotate first, clean up second.** Deleting the line does nothing — it's in history.
2. Invalidate the credential at the provider (revoke token, rotate key).
3. Purge history only if required (`git filter-repo`), knowing forks/clones keep copies.
4. Move to env vars, a secret manager (Vault, AWS Secrets Manager, Doppler), or
   platform secrets (Actions secrets, compose `env_file` + gitignored `.env`).

## Adding a new pattern

Add a `(name, regex)` tuple to `TOKEN_PATTERNS` in `scripts/rules.py`. Keep
patterns anchored to the provider's fixed prefix to avoid false positives.
