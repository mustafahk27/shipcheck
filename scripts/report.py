#!/usr/bin/env python3
"""shipcheck report — renders the audit as a color-coded terminal report.

Usage:
  python3 report.py [path]            terminal report
  python3 report.py [path] --export   also writes shipcheck-report.md in [path]
  python3 report.py [path] --json     raw findings JSON instead of the report
"""

import json
import os
import sys
from datetime import date

import rules

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
SEVERITIES = {  # severity: (emoji, ANSI color)
    "CRITICAL": ("🔴", "\033[31m"),
    "HIGH":     ("🟠", "\033[33m"),
    "MEDIUM":   ("🟡", "\033[93m"),
    "LOW":      ("🔵", "\033[36m"),
}
RULE = "━" * 43


def render_terminal(result, root):
    color = sys.stdout.isatty() or os.environ.get("FORCE_COLOR")

    def c(code, text):
        return "{}{}{}".format(code, text, RESET) if color else text

    scanned = result["scanned"]
    findings = result["findings"]
    dirty = {f["path"] for f in findings}
    clean = len(scanned) - len(dirty)

    out = []
    out.append(c(BOLD, "🚢 shipcheck — pre-flight audit"))
    out.append(RULE)
    out.append("Scanned: {} files  |  Issues: {}  |  Clean: {}".format(
        len(scanned), len(findings), clean))
    out.append("")

    if not scanned:
        out.append("No infrastructure files found in {} — nothing to audit.".format(root))
    elif not findings:
        out.append(c("\033[32m", "✅ All clear — no issues found. Ship it."))
    else:
        for f in findings:
            emoji, sev_color = SEVERITIES[f["severity"]]
            out.append("{} {} {}".format(
                emoji,
                c(sev_color + BOLD, "[{}]".format(f["severity"])),
                c(BOLD, "{}:{}".format(f["path"], f["line"]))))
            out.append("   {}".format(f["message"]))
            out.append(c(DIM, "   💡 Fix: {}".format(f["fix"])))
            out.append("")
        counts = {}
        for f in findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        summary = "  ".join("{} {} {}".format(SEVERITIES[s][0], counts[s], s.lower())
                            for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if s in counts)
        out.append(summary)

    out.append(RULE)
    if findings:
        out.append(c(DIM, "Run `/shipcheck --export` to save as shipcheck-report.md"))
    return "\n".join(out)


def render_markdown(result):
    scanned = result["scanned"]
    findings = result["findings"]
    dirty = {f["path"] for f in findings}

    md = ["# 🚢 shipcheck — pre-flight audit", ""]
    md.append("*{} · {} files scanned · {} issues · {} clean*".format(
        date.today().isoformat(), len(scanned), len(findings), len(scanned) - len(dirty)))
    md.append("")
    if not findings:
        md.append("✅ **All clear — no issues found.**")
    else:
        md.append("| Severity | Location | Issue | Fix |")
        md.append("|---|---|---|---|")
        for f in findings:
            emoji, _ = SEVERITIES[f["severity"]]
            md.append("| {} {} | `{}:{}` | {} | {} |".format(
                emoji, f["severity"], f["path"], f["line"],
                f["message"].replace("|", "\\|"), f["fix"].replace("|", "\\|")))
    md.append("")
    md.append("### Files scanned")
    md.append("")
    for s in scanned:
        mark = "⚠️" if s["path"] in dirty else "✅"
        md.append("- {} `{}` ({})".format(mark, s["path"], s["type"]))
    md.append("")
    return "\n".join(md)


def main():
    args = [a for a in sys.argv[1:]]
    export = "--export" in args
    as_json = "--json" in args
    paths = [a for a in args if not a.startswith("--")]
    root = paths[0] if paths else "."

    result = rules.run(root)

    if as_json:
        print(json.dumps(result, indent=2))
        return

    print(render_terminal(result, root))

    if export:
        out_path = os.path.join(root, "shipcheck-report.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(result))
        print("\n📄 Report saved to {}".format(out_path))

    # exit 1 on CRITICAL/HIGH so CI can gate on it
    if any(f["severity"] in ("CRITICAL", "HIGH") for f in result["findings"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
