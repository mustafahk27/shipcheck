#!/usr/bin/env python3
"""shipcheck auto-fix — applies safe, deterministic fixes for findings.

Usage:
  python3 fix.py [path]            apply fixes, print what changed
  python3 fix.py [path] --dry-run  show planned edits without touching files

Only mechanical, can't-break-anything edits live here:
  no-restart-policy       add `restart: unless-stopped` to the service
  exposed-port            bind the published port to 127.0.0.1
  missing-needs           add `needs: [<other jobs>]` to the deploy job
  draft-pr-full-pipeline  gate each job with `if: ... draft == false`
  env-committed           add .env to .gitignore

Everything needing judgment (pinning versions, USER, HEALTHCHECK, moving
secrets to env vars, cache setup) is left for Claude / the user — see SKILL.md.
"""

import json
import os
import re
import sys

import rules

FIXABLE_RULES = {
    "no-restart-policy",
    "exposed-port",
    "missing-needs",
    "draft-pr-full-pipeline",
    "env-committed",
}


def child_indent(lines, parent_idx):
    """Indent of the first real line nested under lines[parent_idx] (0-based)."""
    parent = len(lines[parent_idx]) - len(lines[parent_idx].lstrip())
    for line in lines[parent_idx + 1:]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        return indent if indent > parent else parent + 2
    return parent + 2


def plan_for_file(path, lines, findings):
    """Return edits for one file: [(line_1based, kind, text)] — kind: insert_after | replace."""
    edits = []
    for f in findings:
        rule, ln = f["rule"], f["line"]
        idx = ln - 1
        if rule == "no-restart-policy":
            pad = " " * child_indent(lines, idx)
            edits.append((ln, "insert_after", pad + "restart: unless-stopped\n"))
        elif rule == "exposed-port":
            new = re.sub(r'(["\']?)(\d+:\d+)', r'\g<1>127.0.0.1:\g<2>', lines[idx], count=1)
            if new != lines[idx]:
                edits.append((ln, "replace", new))
        elif rule == "missing-needs":
            jobs = rules.parse_actions_jobs(lines)
            this_job = next((n for n, j in jobs.items() if j["line"] == ln), None)
            others = [n for n, j in jobs.items() if n != this_job and j["line"] < ln]
            if this_job and others:
                pad = " " * child_indent(lines, idx)
                edits.append((ln, "insert_after",
                              pad + "needs: [{}]\n".format(", ".join(others))))
        elif rule == "draft-pr-full-pipeline":
            for name, job in rules.parse_actions_jobs(lines).items():
                body = "".join(t for _, t in job["body"])
                if re.search(r"(?m)^\s*if:", body):
                    continue
                pad = " " * child_indent(lines, job["line"] - 1)
                edits.append((job["line"], "insert_after",
                              pad + "if: github.event.pull_request.draft == false\n"))
    return edits


def apply_edits(lines, edits):
    for ln, kind, text in sorted(edits, key=lambda e: e[0], reverse=True):
        if kind == "replace":
            lines[ln - 1] = text
        else:
            lines.insert(ln, text)
    return lines


def fix_gitignore(root, dry_run):
    gi = os.path.join(root, ".gitignore")
    existing = ""
    if os.path.exists(gi):
        with open(gi, encoding="utf-8") as f:
            existing = f.read()
    if re.search(r"(?m)^\.env$", existing):
        return None
    if not dry_run:
        with open(gi, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(".env\n")
    return ".gitignore: add `.env`"


def run(root, dry_run=False):
    result = rules.run(root)
    fixable = [f for f in result["findings"] if f["rule"] in FIXABLE_RULES]
    applied, skipped = [], []

    by_path = {}
    for f in fixable:
        by_path.setdefault(f["path"], []).append(f)

    for path, findings in sorted(by_path.items()):
        if any(f["rule"] == "env-committed" for f in findings):
            note = fix_gitignore(root, dry_run)
            if note:
                applied.append(note)
            env_tracked = [f for f in findings if f["rule"] == "env-committed"
                           and "committed to git" in f["message"]]
            for f in env_tracked:
                skipped.append("{}: still tracked — run `git rm --cached {}` and rotate its values"
                               .format(f["path"], f["path"]))
            findings = [f for f in findings if f["rule"] != "env-committed"]
        if not findings:
            continue
        full = os.path.join(root, path)
        with open(full, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        edits = plan_for_file(path, lines, findings)
        if not edits:
            continue
        if not dry_run:
            with open(full, "w", encoding="utf-8") as fh:
                fh.writelines(apply_edits(lines, edits))
        for ln, kind, text in sorted(edits, key=lambda e: e[0]):
            desc = text.strip() if kind == "insert_after" else "→ " + text.strip()
            applied.append("{}:{}: {}".format(path, ln, desc))

    remaining = [f for f in result["findings"] if f["rule"] not in FIXABLE_RULES]
    return {"applied": applied, "skipped": skipped, "remaining": remaining,
            "dry_run": dry_run}


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    as_json = "--json" in args
    paths = [a for a in args if not a.startswith("--")]
    root = paths[0] if paths else "."

    out = run(root, dry_run=dry_run)

    if as_json:
        print(json.dumps(out, indent=2))
        return

    verb = "Would apply" if dry_run else "Applied"
    print("🔧 shipcheck auto-fix")
    print("━" * 43)
    if not out["applied"]:
        print("Nothing auto-fixable found.")
    else:
        print("{} {} fix(es):".format(verb, len(out["applied"])))
        for a in out["applied"]:
            print("  ✅ " + a)
    for s in out["skipped"]:
        print("  ⚠️  " + s)
    if out["remaining"]:
        print()
        print("{} finding(s) need judgment (version pins, USER, HEALTHCHECK, secrets):"
              .format(len(out["remaining"])))
        for f in out["remaining"]:
            print("  ▪ [{}] {}:{} — {}".format(f["severity"], f["path"], f["line"], f["rule"]))
        print()
        print("Ask Claude to fix these, or see references/ for remediation patterns.")


if __name__ == "__main__":
    main()
