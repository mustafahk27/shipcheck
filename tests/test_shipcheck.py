"""shipcheck test suite — stdlib unittest, no dependencies.

Run: python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import fix  # noqa: E402
import report  # noqa: E402
import rules  # noqa: E402
import scan  # noqa: E402

DEMO = os.path.join(REPO_ROOT, "demo")

FIXABLE = {"no-restart-policy", "exposed-port", "missing-needs",
           "draft-pr-full-pipeline", "env-committed"}


def write(root, rel, content):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shipcheck-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class TestScan(TmpDirTest):
    def test_demo_classification(self):
        found = {f["path"]: f["type"] for f in scan.scan(DEMO)}
        self.assertEqual(found, {
            "bad-compose.yml": "compose",
            "bad-dockerfile": "dockerfile",
            "bad-workflow.yml": "github-actions",
        })

    def test_detects_by_location_and_content(self):
        write(self.tmp, "Dockerfile", "FROM node:22\n")
        write(self.tmp, ".github/workflows/deploy.yml", "on: push\njobs:\n  a:\n    steps: []\n")
        write(self.tmp, "k8s/deploy.yaml", "apiVersion: apps/v1\nkind: Deployment\n")
        write(self.tmp, ".gitlab-ci.yml", "build:\n  script: [make]\n")
        write(self.tmp, ".env", "A=b\n")
        write(self.tmp, ".env.example", "A=\n")  # must be skipped
        types = {f["path"]: f["type"] for f in scan.scan(self.tmp)}
        self.assertEqual(types.get("Dockerfile"), "dockerfile")
        self.assertEqual(types.get(os.path.join(".github", "workflows", "deploy.yml")),
                         "github-actions")
        self.assertEqual(types.get(os.path.join("k8s", "deploy.yaml")), "k8s")
        self.assertEqual(types.get(".gitlab-ci.yml"), "gitlab-ci")
        self.assertEqual(types.get(".env"), "env")
        self.assertNotIn(".env.example", types)

    def test_clean_project_scans_empty(self):
        write(self.tmp, "src/app.py", "print('hello')\n")
        self.assertEqual(scan.scan(self.tmp), [])

    def test_skips_vendored_dirs(self):
        write(self.tmp, "node_modules/pkg/Dockerfile", "FROM node\n")
        write(self.tmp, ".claude/skills/x/demo/bad-dockerfile", "FROM node:latest\n")
        self.assertEqual(scan.scan(self.tmp), [])


class TestRulesOnDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = rules.run(DEMO)
        cls.findings = cls.result["findings"]

    def test_all_expected_rules_fire(self):
        fired = {f["rule"] for f in self.findings}
        self.assertEqual(fired, {
            "hardcoded-secret", "unpinned-latest", "runs-as-root",
            "no-healthcheck", "no-digest-pin", "no-restart-policy",
            "exposed-port", "secret-echoed", "no-ci-caching",
            "missing-needs", "draft-pr-full-pipeline",
        })

    def test_severity_counts(self):
        counts = {}
        for f in self.findings:
            counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        self.assertEqual(counts, {"CRITICAL": 5, "HIGH": 7, "MEDIUM": 7, "LOW": 2})

    def test_findings_sorted_by_severity(self):
        order = [rules.SEVERITY_ORDER[f["severity"]] for f in self.findings]
        self.assertEqual(order, sorted(order))

    def test_secret_values_redacted(self):
        for f in self.findings:
            if f["rule"] == "hardcoded-secret":
                self.assertNotIn("hunter2hunter2", f["message"])
                self.assertNotIn("super-secret-jwt-signing-key-123", f["message"])


class TestSecretFalsePositives(TmpDirTest):
    def check(self, dockerfile_line):
        write(self.tmp, "Dockerfile",
              "FROM node:22.12-alpine@sha256:abc\nUSER node\nHEALTHCHECK CMD true\n"
              + dockerfile_line + "\n")
        return [f for f in rules.run(self.tmp)["findings"] if f["rule"] == "hardcoded-secret"]

    def test_variable_reference_not_flagged(self):
        self.assertEqual(self.check("ENV DB_PASSWORD=${DB_PASSWORD}"), [])

    def test_template_expression_not_flagged(self):
        self.assertEqual(self.check("ENV API_TOKEN={{ secrets.API_TOKEN }}"), [])

    def test_placeholder_not_flagged(self):
        self.assertEqual(self.check("ENV ADMIN_PASSWORD=changeme123"), [])

    def test_comment_not_flagged(self):
        self.assertEqual(self.check("# ENV OPENAI_API_KEY=sk-proj-Ab12Cd34Ef56Gh78Ij90Kl12"), [])

    def test_real_literal_is_flagged(self):
        self.assertEqual(len(self.check("ENV JWT_SECRET=actual-literal-secret-1234")), 1)


class TestK8s(TmpDirTest):
    MANIFEST = ("apiVersion: apps/v1\nkind: Deployment\nspec:\n  template:\n    spec:\n"
                "      containers:\n        - name: api\n          image: myapp:1.0\n")

    def test_missing_limits_flagged(self):
        write(self.tmp, "deploy.yaml", self.MANIFEST)
        fired = {f["rule"] for f in rules.run(self.tmp)["findings"]}
        self.assertIn("no-resource-limits", fired)

    def test_with_limits_clean(self):
        write(self.tmp, "deploy.yaml", self.MANIFEST +
              "          resources:\n            limits:\n              memory: 512Mi\n")
        fired = {f["rule"] for f in rules.run(self.tmp)["findings"]}
        self.assertNotIn("no-resource-limits", fired)


class TestEnvCommitted(TmpDirTest):
    def git(self, *args):
        subprocess.run(["git"] + list(args), cwd=self.tmp, check=True,
                       capture_output=True)

    def env_findings(self):
        return [f for f in rules.run(self.tmp)["findings"] if f["rule"] == "env-committed"]

    def test_no_repo_no_gitignore_flagged(self):
        write(self.tmp, ".env", "X=y\n")
        self.assertEqual(len(self.env_findings()), 1)

    def test_no_repo_gitignored_clean(self):
        write(self.tmp, ".env", "X=y\n")
        write(self.tmp, ".gitignore", ".env\n")
        self.assertEqual(self.env_findings(), [])

    def test_repo_untracked_unignored_flagged(self):
        write(self.tmp, ".env", "X=y\n")
        self.git("init", "-q")
        found = self.env_findings()
        self.assertEqual(len(found), 1)
        self.assertIn("not gitignored", found[0]["message"])

    def test_repo_gitignored_clean(self):
        write(self.tmp, ".env", "X=y\n")
        write(self.tmp, ".gitignore", ".env\n")
        self.git("init", "-q")
        self.assertEqual(self.env_findings(), [])

    def test_repo_tracked_flagged_as_committed(self):
        write(self.tmp, ".env", "X=y\n")
        self.git("init", "-q")
        self.git("add", ".env")
        found = self.env_findings()
        self.assertEqual(len(found), 1)
        self.assertIn("committed to git", found[0]["message"])


class TestAutoFix(TmpDirTest):
    def setUp(self):
        super().setUp()
        for name in os.listdir(DEMO):
            shutil.copy(os.path.join(DEMO, name), self.tmp)

    def test_fix_clears_fixable_rules(self):
        before = {f["rule"] for f in rules.run(self.tmp)["findings"]}
        self.assertTrue(FIXABLE - {"env-committed"} <= before)
        out = fix.run(self.tmp)
        self.assertGreater(len(out["applied"]), 0)
        after = {f["rule"] for f in rules.run(self.tmp)["findings"]}
        self.assertEqual(after & FIXABLE, set())

    def test_fix_is_idempotent(self):
        fix.run(self.tmp)
        second = fix.run(self.tmp)
        self.assertEqual(second["applied"], [])

    def test_dry_run_touches_nothing(self):
        before = rules.run(self.tmp)["findings"]
        fix.run(self.tmp, dry_run=True)
        self.assertEqual(rules.run(self.tmp)["findings"], before)

    def test_fixed_compose_keeps_service_structure(self):
        fix.run(self.tmp)
        with open(os.path.join(self.tmp, "bad-compose.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count("restart: unless-stopped"), 3)
        self.assertIn('"127.0.0.1:5432:5432"', text)
        self.assertIn('"127.0.0.1:6379:6379"', text)


class TestReport(unittest.TestCase):
    def test_terminal_render_contains_summary(self):
        result = rules.run(DEMO)
        out = report.render_terminal(result, DEMO)
        self.assertIn("shipcheck — pre-flight audit", out)
        self.assertIn("Scanned: 3 files", out)
        self.assertIn("[CRITICAL]", out)

    def test_markdown_render_is_table(self):
        result = rules.run(DEMO)
        md = report.render_markdown(result)
        self.assertIn("| Severity | Location | Issue | Fix |", md)
        self.assertIn("### Files scanned", md)

    def test_clean_run_reports_all_clear(self):
        tmp = tempfile.mkdtemp(prefix="shipcheck-clean-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        result = rules.run(tmp)
        out = report.render_terminal(result, tmp)
        self.assertIn("No infrastructure files found", out)


if __name__ == "__main__":
    unittest.main()
