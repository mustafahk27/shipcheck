#!/usr/bin/env python3
"""shipcheck scanner — discovers infrastructure files in a repository.

Usage: python3 scan.py [path]
Prints a JSON list of {"path": ..., "type": ...} objects.

File types: dockerfile, compose, k8s, github-actions, gitlab-ci, nginx, env
"""

import json
import os
import re
import sys

SKIP_DIRS = {
    ".git", ".claude", "node_modules", "vendor", "dist", "build", "target",
    "__pycache__", ".venv", "venv", ".tox", ".next", ".terraform",
}

YAML_EXTS = (".yml", ".yaml")


def read_head(path, size=4096):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(size)
    except OSError:
        return ""


def classify(path):
    """Return the infra file type for a path, or None if not an infra file."""
    name = os.path.basename(path).lower()

    if name == ".env" or (name.startswith(".env.") and not name.endswith(".example")):
        return "env"

    if "dockerfile" in name and not name.endswith(YAML_EXTS):
        return "dockerfile"

    if name == ".gitlab-ci.yml":
        return "gitlab-ci"

    if name.endswith(YAML_EXTS):
        norm = path.replace(os.sep, "/")
        if "compose" in name:
            return "compose"
        if "/.github/workflows/" in norm:
            return "github-actions"
        head = read_head(path)
        # Workflow files outside .github/ (e.g. demo fixtures): jobs + on triggers
        if re.search(r"^jobs:", head, re.M) and re.search(r"^(on|'on'|\"on\"):", head, re.M):
            return "github-actions"
        if re.search(r"^apiVersion:", head, re.M) and re.search(r"^kind:", head, re.M):
            return "k8s"
        if re.search(r"^services:", head, re.M):
            return "compose"
        return None

    if name == "nginx.conf" or (name.endswith(".conf") and "server" in read_head(path)):
        return "nginx"

    # Extensionless files that look like Dockerfiles
    if "." not in name and re.match(r"\s*(#.*\n\s*)*FROM\s+\S+", read_head(path)):
        return "dockerfile"

    return None


def scan(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        # don't skip .github — we need workflows
        if ".github" not in dirnames and os.path.isdir(os.path.join(dirpath, ".github")):
            dirnames.append(".github")
        for fn in sorted(filenames):
            path = os.path.join(dirpath, fn)
            ftype = classify(path)
            if ftype:
                found.append({"path": os.path.relpath(path, root), "type": ftype})
    return found


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(scan(root), indent=2))


if __name__ == "__main__":
    main()
