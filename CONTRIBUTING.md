# Contributing to shipcheck

Thanks for helping catch prod-killers. The most valuable contribution is a new
rule — here's the recipe.

## Adding a rule (4 steps)

1. **Write the check** in `scripts/rules.py`. Use the `finding()` helper:
   severity (`CRITICAL`/`HIGH`/`MEDIUM`/`LOW`), a kebab-case rule id, the exact
   line number, a one-line message that explains *why it hurts*, and a one-line
   fix. Line-based parsing only — no PyYAML, no pip dependencies (that's a hard
   rule: shipcheck must run on a bare Python 3.9).

2. **Break a demo file** in `demo/` so your rule fires in the showcase. Every
   rule must be visible when running against `demo/`, or covered by a test
   fixture if it can't coexist with the existing demo files.

3. **Add the rationale** to the matching `references/*.md` — what it detects,
   why it kills prod, and a copy-pasteable fix. This is what Claude shows users
   who ask "why does this matter?".

4. **Add a test** in `tests/test_shipcheck.py` — at minimum: the rule fires on
   a bad fixture and stays silent on a good one (false-positive guard).

## Auto-fixable rules

If the fix is deterministic and can't break behavior (adding a line, tightening
a binding), also add it to `scripts/fix.py`: a branch in `plan_for_file()` plus
the rule id in `FIXABLE_RULES`. Fixes must be idempotent — running `--fix`
twice applies nothing the second time. If the fix needs judgment (choosing a
version, knowing an endpoint), don't automate it; document the manual fix in
the reference instead.

## Before you open the PR

```bash
python3 -m unittest discover -s tests   # all green
python3 scripts/rules.py . | python3 -c "import json,sys; \
  f=[x for x in json.load(sys.stdin)['findings'] if not x['path'].startswith('demo/')]; \
  assert not f, f"                       # self-scan stays clean
```

CI runs both on every PR (draft PRs are skipped — shipcheck practices what it
preaches).

## What gets accepted

- Rules that catch **real deployment failures**, not style preferences
- Messages that say why, fixes that are actionable in one line
- Zero new dependencies, exact line numbers, no false-positive-prone patterns
  (anchor secret regexes to fixed provider prefixes)

Unsure whether a rule idea fits? Open an issue first — cheap to discuss, and
`good first issue` tickets are seeded with vetted ideas.
