"""Repro for job 263: a running Run-all parent parked on needs-human children (none stalled, none waiting, nothing
alive) counts busy in watchdog_tick forever, so auto continue never starts another run-all (with Focus on, nowhere)."""
import json, os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"


class ParkedParentReproTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        self.base = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.base / "no-usage.json"))
        env.start(); self.addCleanup(env.stop)
        for s in (serve.ORPHAN_RESPAWN, serve.STALL_RESUMED, serve.AUTO_RESUME):
            s.clear(); self.addCleanup(s.clear)
        self.projects = {}

    def project(self, name, jobs=()):
        root = self.base / name / "scrum"
        (root / "jobs").mkdir(parents=True)
        (root / "project.md").write_text("# Project\n- Test: x\n- Auto continue: 1\n")
        (root / "backlog.md").write_text("# Backlog\n- [x] 074 shipped item\n- [x] 080 shipped item\n- [ ] Open item\n")
        (root / "board.json").write_text(json.dumps({"jobs": [{"updatedAt": self.board.now(), "reason": None, **j}
                                                              for j in jobs]}))
        self.projects[name] = root.parent
        return root

    def parked(self):
        kids = [("060-a", "done", None), ("074-b", "needs-human", "applied by hand; git-excluded"),
                ("075-c", "aborted", None), ("080-d", "needs-human", "Pick a layout?")]
        parent = {"id": "054-run-all", "stage": "running", "lane": "runall", "children": [k[0] for k in kids]}
        return [parent] + [{"id": i, "stage": st, "reason": r, "parent": "054-run-all"} for i, st, r in kids]

    def run_alls(self):
        with mock.patch.object(self.board, "projects", return_value=self.projects), \
                mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(self.serve, "running", return_value=False), \
                mock.patch.object(self.serve, "spawn") as spawn:
            self.serve.watchdog_tick()
        return [c.args for c in spawn.call_args_list if c.args[2] == "run-all"]

    def test_parked_runall_parent_does_not_block_auto_continue(self):
        for second in (False, True):
            with self.subTest(second=second):
                self.projects.clear()
                root = self.project(f"p{int(second)}", jobs=self.parked())
                if second:
                    self.project(f"other{int(second)}")  # a second opted-in, idle project, ranked below
                self.assertEqual(self.run_alls()[:1],  # rank 1 goes first; the second project starts after it
                                 [(f"p{int(second)}", root, "run-all", "run-all", "/trevskills-scrum run-all")],
                                 "a parent parked on Trevor must not count busy")

if __name__ == "__main__":
    unittest.main()
