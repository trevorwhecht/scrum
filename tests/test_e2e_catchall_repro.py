"""Repro for job 630: e2e-specs catch-all routes and e2e_full_due retry of error/stale running records."""
import subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))

import board  # noqa: E402
import serve  # noqa: E402

FILES = {
    "src/app/help/[...slug]/page.tsx": "export default () => <p>docs</p>\n",
    "src/app/guide/[[...slug]]/page.tsx": "export default () => <p>guide</p>\n",
    "src/app/order/[id]/page.tsx": "export default () => <p>order</p>\n",
    "playwright.config.ts": "export default { testDir: './e2e' }\n",
    "e2e/install.spec.ts": "test('i', async ({ page }) => { await page.goto('/help/setup/install') })\n",
    "e2e/help-root.spec.ts": "test('h', async ({ page }) => { await page.goto('/help') })\n",
    "e2e/guide-root.spec.ts": "test('g', async ({ page }) => { await page.goto('/guide') })\n",
    "e2e/guide-deep.spec.ts": "test('g', async ({ page }) => { await page.goto('/guide/a/b') })\n",
}


class CatchAllRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        for rel, text in FILES.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "job")
        self.pfile = Path(self.tmp.name) / "project.md"
        self.pfile.write_text("# Project\n- E2E: npx playwright test\n- UI globs: *.tsx src/app/\n")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def change(self, rel):
        p = self.repo / rel
        p.write_text(p.read_text() + "// changed\n")
        self.git("commit", "-q", "-am", f"edit {rel}")
        return board.e2e_specs(self.repo, "main", self.pfile)

    def test_catch_all_route_matches_multi_segment(self):
        out = self.change("src/app/help/[...slug]/page.tsx")
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]), ("scoped", ["e2e/install.spec.ts"], []))
        # a plain [param] still matches exactly one segment
        one = board._route_re("/order/[id]", False)
        self.assertTrue(one.search("page.goto('/order/42')"))
        self.assertFalse(one.search("page.goto('/order/42/edit')"))

    def test_optional_catch_all_route_matches_zero_or_more(self):
        out = self.change("src/app/guide/[[...slug]]/page.tsx")
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]),
                         ("scoped", ["e2e/guide-deep.spec.ts", "e2e/guide-root.spec.ts"], []))
        root = board._route_re("/[[...slug]]", False)
        self.assertTrue(root.search("page.goto('/')"))
        self.assertTrue(root.search("page.goto('/a/b')"))
        self.assertFalse(root.search("page.goto('')"))


class E2eFullDueRetryTest(unittest.TestCase):
    def test_due_retries_error_and_stale_running_after_24h(self):
        due, now = serve.e2e_full_due, 1_000_000
        for result in ("error", "running"):
            self.assertTrue(due({"at": now - 86400, "head": "aaa", "result": result}, "aaa", 0, now), result)
            self.assertFalse(due({"at": now - 3600, "head": "aaa", "result": result}, "aaa", 0, now), result)
        for result in ("pass", "fail"):
            self.assertFalse(due({"at": now - 90000, "head": "aaa", "result": result}, "aaa", 0, now), result)
        self.assertFalse(due({"at": now - 90000, "head": "aaa"}, "aaa", 0, now))


if __name__ == "__main__":
    unittest.main()
