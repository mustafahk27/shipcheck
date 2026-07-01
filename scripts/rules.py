#!/usr/bin/env python3
"""shipcheck rules engine — runs audit rules against discovered infra files.

Usage: python3 rules.py [path]
Prints a JSON object: {"scanned": [...], "findings": [...]}

Each finding: {"severity", "rule", "path", "line", "message", "fix"}
Severities: CRITICAL, HIGH, MEDIUM, LOW
"""

import json
import os
import re
import subprocess
import sys

import scan

# ---------------------------------------------------------------- secrets

# (name, pattern) — provider-specific token formats
TOKEN_PATTERNS = [
    ("OpenAI API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("npm token", re.compile(r"npm_[A-Za-z0-9]{36,}")),
    ("Stripe key", re.compile(r"[sr]k_live_[A-Za-z0-9]{20,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

# generic KEY=value / KEY: value where the key name implies a secret
GENERIC_SECRET = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_]*)"
    r"\s*[:=]\s*['\"]?([^\s'\"#]{8,})"
)

# values that are references, not literals — never flag these
SAFE_VALUE = re.compile(
    r"^\$|\$\{|\{\{|^%|<[^>]+>$|^(?:change_?me|placeholder|example|your[-_]|xxx+|\*+$|none$|null$|true$|false$)",
    re.I,
)


def redact(value):
    return value[:7] + "..." if len(value) > 10 else "***"


def check_secrets(path, lines):
    findings = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for name, pat in TOKEN_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append(finding(
                    "CRITICAL", "hardcoded-secret", path, i,
                    "Hardcoded {} detected: {}".format(name, redact(m.group(0))),
                    "Move to an environment variable or secret manager; rotate the exposed credential",
                ))
                break
        else:
            m = GENERIC_SECRET.search(line)
            if m and not SAFE_VALUE.search(m.group(2)):
                findings.append(finding(
                    "CRITICAL", "hardcoded-secret", path, i,
                    "Hardcoded credential detected: {}={}".format(m.group(1), redact(m.group(2))),
                    "Move to an environment variable or secret manager; rotate the exposed credential",
                ))
    return findings


def check_env_committed(root, path):
    """CRITICAL if a .env file is committed to git (or present with no gitignore cover)."""
    def git(*args):
        try:
            return subprocess.run(["git"] + list(args), cwd=root,
                                  capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None

    tracked = git("ls-files", "--error-unmatch", path)
    if tracked is None or tracked.returncode == 128:  # git missing or not a repo
        try:
            with open(os.path.join(root, ".gitignore"), encoding="utf-8") as gi:
                if re.search(r"(?m)^\.env$", gi.read()):
                    return []
        except OSError:
            pass
        msg = "{} present outside git — will be committed the moment this becomes a repo".format(path)
        fix = "Add .env to .gitignore before initializing git"
    elif tracked.returncode == 0:
        msg = "{} is committed to git — every secret in it lives in history forever".format(path)
        fix = "git rm --cached {}, add it to .gitignore, and rotate every value in it".format(path)
    else:  # in a repo but untracked — safe only if gitignored
        ignored = git("check-ignore", "-q", path)
        if ignored is not None and ignored.returncode == 0:
            return []
        msg = "{} is not gitignored — one `git add .` away from being committed".format(path)
        fix = "Add .env to .gitignore"
    return [finding("CRITICAL", "env-committed", path, 1, msg, fix)]


# ---------------------------------------------------------------- dockerfile

def check_dockerfile(path, lines):
    findings = []
    has_user = False
    has_healthcheck = False
    last_from_line = None

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = re.match(r"(?i)^FROM\s+(\S+)", stripped)
        if m:
            image = m.group(1)
            last_from_line = i
            if image.lower() in ("scratch",) or image.startswith("$"):
                continue
            ref = image.split("@")[0]
            tag = ref.split(":")[-1] if ":" in ref.split("/")[-1] else None
            if tag == "latest" or (tag is None and "@" not in image):
                findings.append(finding(
                    "HIGH", "unpinned-latest", path, i,
                    "Base image `{}` uses :latest (or no tag) — builds are not reproducible".format(image),
                    "Pin to a specific version, e.g. `node:22.12-alpine`",
                ))
            if "@sha256:" not in image:
                findings.append(finding(
                    "LOW", "no-digest-pin", path, i,
                    "Base image `{}` not pinned to a digest — tag contents can change upstream".format(image),
                    "Pin to a digest: `{}@sha256:<digest>`".format(ref),
                ))
        if re.match(r"(?i)^USER\s+(?!root\b)\S+", stripped):
            has_user = True
        if re.match(r"(?i)^HEALTHCHECK\b", stripped):
            has_healthcheck = True

    anchor = last_from_line or 1
    if not has_user:
        findings.append(finding(
            "HIGH", "runs-as-root", path, anchor,
            "Container runs as root — a compromised process owns the container",
            "Add a non-root user: `USER node` (or create one with adduser)",
        ))
    if not has_healthcheck:
        findings.append(finding(
            "HIGH", "no-healthcheck", path, anchor,
            "No HEALTHCHECK — orchestrators can't detect a wedged container",
            "Add `HEALTHCHECK CMD curl -f http://localhost:3000/health || exit 1`",
        ))
    return findings


# ---------------------------------------------------------------- compose

RISKY_PORTS = {
    "5432": "PostgreSQL", "3306": "MySQL", "27017": "MongoDB",
    "6379": "Redis", "9200": "Elasticsearch", "11211": "Memcached",
    "2375": "Docker daemon", "5984": "CouchDB",
}


def parse_compose_services(lines):
    """Minimal indentation-based parse: {service: {"line": n, "keys": {key: line}}}."""
    services = {}
    in_services = False
    services_indent = None
    current = None
    for i, raw in enumerate(lines, 1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if re.match(r"^services:\s*$", stripped) and indent == 0:
            in_services = True
            services_indent = None
            continue
        if not in_services:
            continue
        if indent == 0:  # left the services: block
            in_services = False
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", stripped)
        if m and (services_indent is None or indent == services_indent):
            services_indent = indent
            current = m.group(1)
            services[current] = {"line": i, "keys": {}}
        elif current and m and indent > services_indent:
            key = m.group(1)
            services[current]["keys"].setdefault(key, i)
    return services


def check_compose(path, lines):
    findings = []
    services = parse_compose_services(lines)
    for name, svc in services.items():
        keys = svc["keys"]
        if "restart" not in keys and "deploy" not in keys:
            findings.append(finding(
                "MEDIUM", "no-restart-policy", path, svc["line"],
                'No restart policy for service "{}" — it stays down after a crash'.format(name),
                "Add `restart: unless-stopped`",
            ))
        m = re.match(r"(?i)^\s*image:\s*(\S+)", lines[keys["image"] - 1]) if "image" in keys else None
        if m:
            image = m.group(1).strip("'\"")
            ref = image.split("@")[0]
            tag = ref.split(":")[-1] if ":" in ref.split("/")[-1] else None
            if tag == "latest" or (tag is None and "@" not in image):
                findings.append(finding(
                    "HIGH", "unpinned-latest", path, keys["image"],
                    'Service "{}" uses `{}` — :latest/no tag is not reproducible'.format(name, image),
                    "Pin to a specific version tag",
                ))
        if "ports" in keys:
            j = keys["ports"]
            while j < len(lines):
                pline = lines[j]
                if not pline.strip().startswith("-"):
                    if j > keys["ports"] and pline.strip() and not pline.strip().startswith("#"):
                        break
                    j += 1
                    continue
                pm = re.search(r'["\']?(?:[\d.]+:)?(\d+):\d+', pline)
                if pm and pm.group(1) in RISKY_PORTS and "127.0.0.1" not in pline:
                    findings.append(finding(
                        "MEDIUM", "exposed-port", path, j + 1,
                        'Service "{}" publishes {} port {} to the host — reachable from outside'.format(
                            name, RISKY_PORTS[pm.group(1)], pm.group(1)),
                        'Remove the mapping (containers reach it via the network) or bind to "127.0.0.1:{}:{}"'.format(
                            pm.group(1), pm.group(1)),
                    ))
                j += 1
    return findings


# ---------------------------------------------------------------- k8s

def check_k8s(path, lines):
    findings = []
    text = "".join(lines)
    if not re.search(r"(?m)^\s*containers:", text):
        return findings
    has_limits = re.search(r"(?m)^\s*limits:", text) and re.search(r"(?m)^\s*resources:", text)
    if not has_limits:
        m = re.search(r"(?m)^\s*containers:", text)
        line = text[:m.start()].count("\n") + 1
        findings.append(finding(
            "HIGH", "no-resource-limits", path, line,
            "No CPU/memory limits — one runaway pod can starve the whole node",
            "Add resources.limits (cpu, memory) to every container spec",
        ))
    return findings


# ---------------------------------------------------------------- CI

DEPLOY_JOB = re.compile(r"(?i)^(deploy|release|publish|prod|production)")
INSTALL_CMD = re.compile(r"(npm|yarn|pnpm)\s+(ci|install)|pip3?\s+install|bundle\s+install|composer\s+install")


def parse_actions_jobs(lines):
    """{job: {"line": n, "body": [(line_no, text), ...]}} for top-level jobs."""
    jobs = {}
    in_jobs = False
    job_indent = None
    current = None
    for i, raw in enumerate(lines, 1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0:
            in_jobs = bool(re.match(r"^jobs:\s*$", stripped))
            current = None
            continue
        if not in_jobs:
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*$", stripped)
        if m and (job_indent is None or indent <= job_indent):
            job_indent = indent
            current = m.group(1)
            jobs[current] = {"line": i, "body": []}
        elif current:
            jobs[current]["body"].append((i, raw))
    return jobs


def check_ci(path, lines, flavor):
    findings = []
    text = "".join(lines)

    # secrets echoed to logs
    for i, line in enumerate(lines, 1):
        if re.search(r"echo\b.*(\$\{\{\s*secrets\.|\$[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|KEY)[A-Z0-9_]*)", line):
            findings.append(finding(
                "HIGH", "secret-echoed", path, i,
                "Secret written to the build log via echo — logs are widely readable and retained",
                "Never echo secrets; pass them via env to the step that needs them",
            ))

    # dependency / docker layer caching
    uses_install = INSTALL_CMD.search(text)
    uses_docker_build = re.search(r"docker\s+(buildx\s+)?build", text)
    if flavor == "github-actions":
        has_cache = "actions/cache" in text or re.search(r"(?m)^\s*cache:\s*\S", text) or "cache-from" in text
    else:
        has_cache = re.search(r"(?m)^\s*cache:", text) or "cache-from" in text
    if (uses_install or uses_docker_build) and not has_cache:
        anchor = text[:(uses_install or uses_docker_build).start()].count("\n") + 1
        what = "Docker layer" if uses_docker_build and not uses_install else "dependency"
        fix = ("Add an actions/cache step (or setup-node's `cache: npm`); for Docker use buildx --cache-from"
               if flavor == "github-actions" else "Add a `cache:` block keyed on your lockfile")
        findings.append(finding(
            "MEDIUM", "no-ci-caching", path, anchor,
            "No {} caching — every run rebuilds from scratch, slowing builds significantly".format(what),
            fix,
        ))

    if flavor == "github-actions":
        jobs = parse_actions_jobs(lines)
        if len(jobs) > 1:
            for name, job in jobs.items():
                body_text = "".join(t for _, t in job["body"])
                if DEPLOY_JOB.match(name) and not re.search(r"(?m)^\s*needs:", body_text):
                    findings.append(finding(
                        "MEDIUM", "missing-needs", path, job["line"],
                        'Job "{}" has no `needs:` — it can deploy before tests finish (jobs run in parallel)'.format(name),
                        "Add `needs: [test, build]` so deploy waits for upstream jobs",
                    ))
        if re.search(r"(?m)^\s*pull_request:", text) and "pull_request.draft" not in text \
                and "ready_for_review" not in text:
            m = re.search(r"(?m)^\s*pull_request:", text)
            findings.append(finding(
                "LOW", "draft-pr-full-pipeline", path, text[:m.start()].count("\n") + 1,
                "Draft PRs run the full pipeline — wasted minutes on work-in-progress pushes",
                "Gate jobs with `if: github.event.pull_request.draft == false`",
            ))
    return findings


# ---------------------------------------------------------------- driver

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def finding(severity, rule, path, line, message, fix):
    return {"severity": severity, "rule": rule, "path": path,
            "line": line, "message": message, "fix": fix}


def run(root):
    files = scan.scan(root)
    findings = []
    for f in files:
        path = f["path"]
        try:
            with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        findings += check_secrets(path, lines)
        if f["type"] == "env":
            findings += check_env_committed(root, path)
        elif f["type"] == "dockerfile":
            findings += check_dockerfile(path, lines)
        elif f["type"] == "compose":
            findings += check_compose(path, lines)
        elif f["type"] == "k8s":
            findings += check_k8s(path, lines)
        elif f["type"] in ("github-actions", "gitlab-ci"):
            findings += check_ci(path, lines, f["type"])
    findings.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["path"], x["line"]))
    return {"scanned": files, "findings": findings}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(run(root), indent=2))


if __name__ == "__main__":
    main()
