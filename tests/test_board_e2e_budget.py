"""Job 1311: job E2E time budget. View-folder scoping, a 10 min --global-timeout on the job form of e2e-specs, the
Playwright log parser e2e_budget and the one deduped speed-up backlog item cmd_e2e_budget files."""
import io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.pop("SCRUM_SHOP", None)  # a shop Mac sets it; backlog-add without --job is refused there (job 1504)
os.environ.pop("CLAUDE_CODE_REMOTE", None)  # a cloud session sets it; same refusal
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"
E2E_CMD = "npm run test:e2e"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                   capture_output=True)


class E2eViewScopeTest(unittest.TestCase):
    FILES = {
        "src/app/admin/dashboard/page.tsx": "import OrdersTable from './views/orders/OrdersTable'\n"
                                            "import PayrollTable from './views/payroll/PayrollTable'\n"
                                            "export default () => <OrdersTable />\n",
        "src/app/admin/dashboard/views/orders/OrdersTable.tsx": "export default () => <table />\n",
        "src/app/admin/dashboard/views/payroll/PayrollTable.tsx": "export default () => <table />\n",
        "playwright.config.ts": "export default { testDir: './e2e' }\n",
        "e2e/a.spec.ts": "test('a', async ({ page }) => { await page.goto('/admin/dashboard?view=orders') })\n",
        "e2e/b.spec.ts": "test('b', async ({ page }) => { await page.goto('/admin/dashboard?view=inks') })\n",
        "e2e/c.spec.ts": "test('c', async ({ page }) => { await page.goto('/admin/dashboard?subview=orders') })\n",
        "e2e/d.spec.ts": "test('d', async ({ page }) => { await page.goto('/admin/dashboard?view=orders-archive') })\n",
    }

    def setUp(self):
        env = mock.patch.dict(os.environ, {"SCRUM_PW_CHANNEL": ""})  # a shop Mac sets it; commands here have no --config
        env.start()
        self.addCleanup(env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        for rel, text in self.FILES.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        git(self.repo, "checkout", "-q", "-b", "job")
        self.pfile = Path(self.tmp.name) / "project.md"
        self.pfile.write_text(f"# Project\n- E2E: {E2E_CMD}\n- UI globs: *.tsx src/app/\n")

    def change(self, *rels):
        for rel in rels:
            p = self.repo / rel
            p.write_text(p.read_text() + "// changed\n")
        git(self.repo, "commit", "-q", "-am", "edit")

    def test_view_folder_maps_to_view_specs(self):
        self.change("src/app/admin/dashboard/views/orders/OrdersTable.tsx")
        out = board.e2e_specs(self.repo, "main", self.pfile)
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]), ("scoped", ["e2e/a.spec.ts"], []))
        self.assertEqual(out["command"], "npm run test:e2e -- e2e/a.spec.ts")

    def test_view_folder_without_view_spec_falls_back_to_route(self):
        self.change("src/app/admin/dashboard/views/payroll/PayrollTable.tsx")
        out = board.e2e_specs(self.repo, "main", self.pfile)
        self.assertEqual((out["mode"], out["specs"]),
                         ("scoped", ["e2e/a.spec.ts", "e2e/b.spec.ts", "e2e/c.spec.ts", "e2e/d.spec.ts"]))

    def test_changed_spec_left_out_of_budgeted_run(self):
        self.change("src/app/admin/dashboard/page.tsx", "e2e/b.spec.ts")
        out = board.e2e_specs(self.repo, "main", self.pfile, budget=True)
        self.assertEqual(out["specs"], ["e2e/a.spec.ts", "e2e/c.spec.ts", "e2e/d.spec.ts"])
        self.assertEqual(out["command"],
                         "npm run test:e2e -- --global-timeout=600000 e2e/a.spec.ts e2e/c.spec.ts e2e/d.spec.ts")
        plain = board.e2e_specs(self.repo, "main", self.pfile)
        self.assertEqual(plain["specs"], ["e2e/a.spec.ts", "e2e/b.spec.ts", "e2e/c.spec.ts", "e2e/d.spec.ts"])
        self.assertEqual(plain["command"],
                         "npm run test:e2e -- e2e/a.spec.ts e2e/b.spec.ts e2e/c.spec.ts e2e/d.spec.ts")

    def test_changed_spec_only_leaves_budgeted_run_empty(self):
        self.change("src/app/admin/dashboard/views/orders/OrdersTable.tsx", "e2e/a.spec.ts")
        out = board.e2e_specs(self.repo, "main", self.pfile, budget=True)
        self.assertEqual((out["mode"], out["command"], out["specs"]), ("none", None, []))

    def test_job_form_budgets_worktree_form_does_not(self):
        self.change("src/app/admin/dashboard/views/orders/OrdersTable.tsx")
        root = Path(self.tmp.name) / "scrum"
        root.mkdir()
        (root / "project.md").write_text(self.pfile.read_text())
        job = board.cmd_new(root, "Budget")
        board.cmd_set(root, job, [f"worktree={self.repo}", "base=main"])
        self.assertEqual(board.cmd_e2e_specs(root, job)["command"],
                         "npm run test:e2e -- --global-timeout=600000 e2e/a.spec.ts")
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(root), "e2e-specs", "--worktree",
                              str(self.repo), "--base", "main", "--project", str(self.pfile)],
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout)["command"], "npm run test:e2e -- e2e/a.spec.ts")


class E2eBudgetCommandTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"SCRUM_PW_CHANNEL": ""})  # a shop Mac sets it
        env.start()
        self.addCleanup(env.stop)

    def test_budget_command_shapes(self):
        c = board._e2e_command
        self.assertEqual(c("npm run test:e2e", ["e2e/a.spec.ts"], budget=True),
                         "npm run test:e2e -- --global-timeout=600000 e2e/a.spec.ts")
        self.assertEqual(c("npm run test:e2e", budget=True), "npm run test:e2e -- --global-timeout=600000")
        self.assertEqual(c("E2E_PORT=3005 npx playwright test", budget=True),
                         "E2E_PORT=3005 npx playwright test --global-timeout=600000")
        self.assertEqual(c("FOO=1 node run-e2e.js", budget=True), "FOO=1 node run-e2e.js")
        self.assertEqual(c("npm run test:e2e", ["e2e/a.spec.ts"]), "npm run test:e2e -- e2e/a.spec.ts")
        self.assertEqual(c("npm run test:e2e"), "npm run test:e2e")
        with mock.patch.dict(os.environ, {"SCRUM_PW_CHANNEL": "chrome"}):
            self.assertEqual(c("npm run test:e2e", ["e2e/a.spec.ts"], budget=True),
                             'npm run test:e2e -- --global-timeout=600000 --config '
                             '"$HOME/.claude/skills/trevskills-e2e/channel.config.mjs" e2e/a.spec.ts')


OVER_LOG = """Running 70 tests using 1 worker

  ✓  1 [chromium] › e2e/orders.spec.ts:12:5 › opens the orders view (3.2s)
  ✓  2 [chromium] › e2e/orders.spec.ts:40:5 › edits an order (1.1m)
  ✓  3 [chromium] › e2e/inks.spec.ts:8:3 › lists inks (460ms)
  ✓  4 [chromium] › e2e/payroll.spec.ts:5:1 › pays (20.0s)
  ✘  5 [chromium] › e2e/payroll.spec.ts:30:1 › slow one (15.5s)
  ✓  6 [chromium] › e2e/payroll.spec.ts:30:1 › slow one (retry #1) (14.5s)
Timed out waiting 600s for the test suite to run

  1 interrupted
    [chromium] › e2e/big.spec.ts:3:1 › big
  2 flaky
    [chromium] › e2e/payroll.spec.ts:30:1 › slow one
  27 did not run
  40 passed (10.0m)
"""

NORMAL_LOG = """Running 5 tests using 1 worker

  ✓  1 [chromium] › e2e/a.spec.ts:1:1 › a (2.0s)
  ✘  2 [chromium] › e2e/b.spec.ts:1:1 › b (5.0s)

  1 failed
    [chromium] › e2e/b.spec.ts:1:1 › b
  4 passed (12.3s)
"""


class E2eBudgetParseTest(unittest.TestCase):
    def test_parse_over_budget_log(self):
        self.assertEqual(board.e2e_budget(OVER_LOG), {
            "over_budget": True, "passed": 42, "failed": 0, "not_run": 28,
            "slowest": [["e2e/orders.spec.ts", 69.2], ["e2e/payroll.spec.ts", 50.0], ["e2e/inks.spec.ts", 0.5]],
            "line": "E2E: over budget, 42 passed, 28 not run"})

    def test_parse_normal_log(self):
        out = board.e2e_budget(NORMAL_LOG)
        self.assertEqual((out["over_budget"], out["passed"], out["failed"], out["not_run"]), (False, 4, 1, 0))
        self.assertEqual(out["slowest"], [["e2e/b.spec.ts", 5.0], ["e2e/a.spec.ts", 2.0]])

    def test_parse_slowest_keeps_five(self):
        log = "".join(f"  ✓  {n} [chromium] › e2e/s{n}.spec.ts:1:1 › t ({n}s)\n" for n in range(1, 8))
        self.assertEqual([s[0] for s in board.e2e_budget(log)["slowest"]],
                         ["e2e/s7.spec.ts", "e2e/s6.spec.ts", "e2e/s5.spec.ts", "e2e/s4.spec.ts", "e2e/s3.spec.ts"])

    def test_parse_empty_log(self):
        self.assertEqual(board.e2e_budget(""), {
            "over_budget": False, "passed": 0, "failed": 0, "not_run": 0, "slowest": [],
            "line": "E2E: over budget, 0 passed, 0 not run"})


class E2eBudgetBacklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(Path(self.tmp.name) / "projects.json")})
        env.start()
        self.addCleanup(env.stop)
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        self.log = Path(self.tmp.name) / "e2e.log"
        self.log.write_text(OVER_LOG)

    def open_items(self):
        return [i["text"] for i in board.read_backlog(self.root)[1] if not i["done"]]

    def test_over_budget_adds_one_item(self):
        out = board.cmd_e2e_budget(self.root, "1764-slow-run", self.log)
        text = ("Speed up the slowest job E2E spec files: e2e/orders.spec.ts 69.2s, e2e/payroll.spec.ts 50s, "
                "e2e/inks.spec.ts 0.5s (job 1764-slow-run E2E ran past the 10 min budget)")
        self.assertEqual(out["backlog"], text)
        self.assertEqual(out["line"], "E2E: over budget, 42 passed, 28 not run")
        self.assertEqual(self.open_items(), [text])

    def test_second_over_budget_run_dedupes(self):
        board.cmd_e2e_budget(self.root, "1764-slow-run", self.log)
        self.assertIsNone(board.cmd_e2e_budget(self.root, "1765-slow-run", self.log)["backlog"])
        self.assertEqual(len(self.open_items()), 1)

    def test_failed_test_adds_nothing(self):
        self.log.write_text(OVER_LOG.replace("  27 did not run", "  1 failed\n  27 did not run"))
        out = board.cmd_e2e_budget(self.root, "1764-slow-run", self.log)
        self.assertEqual((out["over_budget"], out["failed"], out["backlog"]), (True, 1, None))
        self.log.write_text(NORMAL_LOG.replace("  1 failed\n", ""))
        self.assertIsNone(board.cmd_e2e_budget(self.root, "1764-slow-run", self.log)["backlog"])
        self.assertEqual(self.open_items(), [])

    def test_e2e_budget_on_worker_writes_followup(self):
        """Job 1504: a shop run's backlog.md never comes home, so the slow-E2E item goes to the job's followups."""
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Existing\n")
        before = (self.root / "backlog.md").read_bytes()
        with mock.patch.dict(os.environ, {"SCRUM_SHOP": "1"}):
            out = board.cmd_e2e_budget(self.root, "1764-slow-run", self.log)
        text = ("Speed up the slowest job E2E spec files: e2e/orders.spec.ts 69.2s, e2e/payroll.spec.ts 50s, "
                "e2e/inks.spec.ts 0.5s (job 1764-slow-run E2E ran past the 10 min budget)")
        self.assertEqual(out["backlog"], text)
        self.assertEqual((self.root / "backlog.md").read_bytes(), before)
        followups = self.root / "jobs" / "1764-slow-run" / "followups"
        self.assertEqual([p.name for p in followups.iterdir()], ["add-1.md"])
        self.assertEqual((followups / "add-1.md").read_text(), f"Backlog: add\nItem: {text}\n")

    def test_missing_log_exits(self):
        with self.assertRaises(SystemExit):
            board.cmd_e2e_budget(self.root, "1764-slow-run", Path(self.tmp.name) / "nope.log")

    def test_cli_prints_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(sys, "argv", ["board.py", "--dir", str(self.root), "e2e-budget",
                                                                   "1764-slow-run", str(self.log)]):
            board.main()
        out = json.loads(buf.getvalue())
        self.assertEqual((out["over_budget"], out["passed"], out["not_run"]), (True, 42, 28))
        self.assertTrue(out["backlog"].startswith("Speed up the slowest job E2E spec files: e2e/orders.spec.ts 69.2s"))


if __name__ == "__main__":
    unittest.main()
