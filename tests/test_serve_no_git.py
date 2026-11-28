"""Job 1362: a registered project kept in a plain folder with no git (project.md `- Git: none`, board.no_git) runs no
git or gh subprocess in its folder from any watchdog pass, the pulse, the weekly digest or the dashboard board, and
logs no `watchdog: <project>:` error; the shop never runs it. A git project is unchanged."""
import io, json, os, re, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # never the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_NET_UP"] = "1"  # the network lookup passes unless a test says so; no test resolves api.anthropic.com
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402

board = serve.board
REAL_RUN = subprocess.run
PROFILE = ("# Project\n- Stack: plain folder\n- Git: none\n- Test: none\n- E2E: npx playwright test\n"
           "- UI globs: motion/**/*.html\n- Dev command: npx serve motion\n")


class NoGitProjectTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.base / "projects.json"),
                              SCRUM_PULSE=str(self.base / "pulse.log"),
                              SCRUM_WINDOWS_FLAGGED=str(self.base / "flagged.json"))
        env.start()
        self.addCleanup(env.stop)
        for cache in (serve.CHECKOUT_ALERT, serve.ACTIONS_ALERT, serve.RUNS, serve.AUTO_RESUME, serve.STALL_RESUMED,
                      serve.ORPHAN_RESPAWN):
            saved = cache.copy()
            cache.clear()
            self.addCleanup(lambda c=cache, s=saved: (c.clear(), c.update(s)))
        self.calls = []  # (argv, cwd) of every subprocess.run

    def project(self, name, profile, jobs):
        repo = self.base / name
        root = repo / "scrum"
        (root / "jobs").mkdir(parents=True)
        (root / "project.md").write_text(profile)
        (root / "backlog.md").write_text("# Backlog\n")
        (root / "board.json").write_text(json.dumps({"jobs": [
            {"updatedAt": board.now(), "reason": None, **j} for j in jobs]}))
        paths = json.loads((self.base / "projects.json").read_text()) if (self.base / "projects.json").exists() else []
        (self.base / "projects.json").write_text(json.dumps(paths + [str(repo)]))
        return repo, root

    def record(self, git_status=b""):
        """A subprocess.run stand-in: every git and gh call is recorded and answered (exit 128, `not a git repository`,
        except `git status`, which prints git_status); anything else is recorded and run for real."""
        def run(argv, *args, **kw):
            argv = [str(a) for a in argv] if isinstance(argv, (list, tuple)) else argv
            self.calls.append((argv, kw.get("cwd")))
            if isinstance(argv, list) and argv and Path(argv[0]).name in ("git", "gh"):
                text = kw.get("text") or kw.get("universal_newlines") or kw.get("encoding")
                if "status" in argv:
                    out = git_status.decode() if text else git_status
                    return subprocess.CompletedProcess(argv, 0, out, "" if text else b"")
                err = "fatal: not a git repository"
                return subprocess.CompletedProcess(argv, 128, "" if text else b"", err if text else err.encode())
            return REAL_RUN(argv, *args, **kw)
        return mock.patch("subprocess.run", side_effect=run)

    def in_folder(self, folder):
        """Each recorded git or gh call whose `-C` path or cwd is folder or inside it."""
        folder = Path(folder).resolve()
        hits = []
        for argv, cwd in self.calls:
            if not isinstance(argv, list) or not argv or Path(argv[0]).name not in ("git", "gh"):
                continue
            paths = [cwd] if cwd else []
            paths += [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-C"]
            if any(Path(p).resolve() == folder or folder in Path(p).resolve().parents for p in paths):
                hits.append((argv, cwd))
        return hits

    def gates_open(self):
        """The machine-wide holds a full E2E run or UI sweep checks before `git status` read as clear, so only the
        project's own state decides whether git runs."""
        return [mock.patch.object(serve, "e2e_queue_free", return_value=True),
                mock.patch.object(serve, "e2e_job_waiting", return_value=False),
                mock.patch.object(serve, "queue_free", return_value=True),
                mock.patch.object(board, "solo_hold", return_value=None)]

    def test_ticks_run_no_git_or_gh_on_a_no_git_project(self):
        repo, root = self.project("edit", PROFILE, [
            {"id": "001-reef-reel", "stage": "build", "lane": "edit", "kind": "edit-animation"}])
        self.assertFalse((repo / ".git").exists())
        err = io.StringIO()
        patches = [self.record(), *self.gates_open(),
                   mock.patch.object(board, "session_alive_fn", return_value=lambda job: False),
                   mock.patch.object(serve, "spawn", return_value=None),
                   mock.patch.object(serve, "run_terminal", return_value=None),
                   mock.patch.object(board, "play")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with redirect_stderr(err):
            serve.watchdog_tick()
            serve.pulse_tick({"edit": True})
            serve.weekly_tick()
            data = serve.board_with_activity(root, "edit")
        self.assertEqual(self.in_folder(repo), [], "no git or gh call may run in a no-git project's folder")
        lines = [l for l in err.getvalue().splitlines() if re.match(r"^watchdog: (?:[\w ]+: )?edit:", l)]
        self.assertEqual(lines, [], err.getvalue())
        self.assertIsNone(data["checkoutAlert"])
        self.assertEqual([j["id"] for j in data["jobs"]], ["001-reef-reel"])
        self.assertEqual(data["jobs"][0]["kind"], "edit-animation", "the card's tag reads the stored kind")
        self.assertTrue(board.shop_project_excluded(root), "the shop never runs a no-git project")
        pulse = [json.loads(l) for l in (self.base / "pulse.log").read_text().splitlines()]
        self.assertIn("edit", pulse[-1]["projects"], "pulse_tick read the no-git project")

    def test_git_project_unchanged(self):
        repo, root = self.project("plain", "# Project\n- Test: x\n- E2E: npx playwright test\n", [])
        self.assertFalse(board.shop_project_excluded(root), "a plain project still goes to the shop")
        self.assertFalse(board.no_git(root))
        patches = [self.record(git_status=b" M app.py\n"), *self.gates_open()]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        serve.e2e_full_tick("plain", repo, root)
        self.assertIn((["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"], None), self.calls)


if __name__ == "__main__":
    unittest.main()
