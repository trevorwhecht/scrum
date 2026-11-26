import io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
import serve  # noqa: E402
import shop  # noqa: E402

W = lambda a: shop.Worker(a, 2, ("owa",))
JOBS = {"p": [{"id": "1894-x", "stage": "done"}, {"id": "1900-y", "stage": "aborted"}, {"id": "1950-z", "stage": "build"}]}


def ok(out="0 0\n"):
    return subprocess.CompletedProcess([], 0, out, "")


def load_script(nums, ids):
    ns = {"__name__": "scrum_cleanup_test", "NUMS": nums, "IDS": ids}
    exec(serve.SHOP_CLEANUP_SCRIPT, ns)
    return ns["main"]


class ShopCleanup(unittest.TestCase):
    def setUp(self):
        serve.SHOP_CLEANUP_AT.clear()

    def test_one_call_per_worker_finished_numbers_only(self):
        with mock.patch.object(serve.shop, "workers", return_value=[W("a"), W("b")]), \
                mock.patch.object(serve.board, "cooling_down", return_value=False), \
                mock.patch.object(serve.shop, "run", return_value=ok("2 3\n")) as run:
            got = serve.shop_cleanup(JOBS)
        self.assertEqual(got, {"a": (2, 3), "b": (2, 3)})
        self.assertEqual([c.kwargs["alias"] for c in run.call_args_list], ["a", "b"])
        script = run.call_args_list[0].kwargs["input"]
        self.assertIn("NUMS = ['1894', '1900']", script)
        self.assertNotIn("1950", script)

    def test_number_shared_with_running_job_excluded(self):
        jobs = {"p": [{"id": "7-a", "stage": "done"}], "q": [{"id": "7-b", "stage": "build"}]}
        with mock.patch.object(serve.shop, "workers", return_value=[W("a")]), mock.patch.object(serve.shop, "run") as run:
            self.assertEqual(serve.shop_cleanup(jobs), {})
        run.assert_not_called()

    def test_no_finished_jobs_no_call(self):
        with mock.patch.object(serve.shop, "workers", return_value=[W("a")]), mock.patch.object(serve.shop, "run") as run:
            serve.shop_cleanup({"p": [{"id": "5-a", "stage": "build"}]})
            serve.shop_cleanup({"p": []})
            serve.shop_cleanup({})
        run.assert_not_called()

    def test_down_worker_skipped_next_still_runs(self):
        bad = [subprocess.CompletedProcess([], c, "", "down") for c in (255, 124, 127)]
        with mock.patch.object(serve.shop, "workers", return_value=[W("a"), W("b"), W("c"), W("d")]), \
                mock.patch.object(serve.board, "cooling_down", return_value=False), \
                mock.patch.object(serve.shop, "run", side_effect=[*bad, ok("1 0")]) as run, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            got = serve.shop_cleanup(JOBS)
        self.assertEqual(got, {"d": (1, 0)})
        self.assertEqual(run.call_count, 4)
        self.assertEqual(err.getvalue().count("watchdog:"), 3)

    def test_cleanup_throttled_per_worker(self):
        with mock.patch.object(serve.shop, "workers", return_value=[W("a")]), \
                mock.patch.object(serve.board, "cooling_down", return_value=False), \
                mock.patch.object(serve.shop, "run", return_value=ok()) as run, \
                mock.patch.object(serve.time, "time", side_effect=[1000, 1599, 1601]):
            serve.shop_cleanup(JOBS)
            serve.shop_cleanup(JOBS)
            self.assertEqual(run.call_count, 1)
            serve.shop_cleanup(JOBS)
            self.assertEqual(run.call_count, 2)

    def test_cleanup_off_skips_shop(self):
        with mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="0"), \
                mock.patch.object(serve.shop, "workers", return_value=[W("a")]), \
                mock.patch.object(serve.shop, "run") as run:
            serve.idle_cleanup({})
        run.assert_not_called()

    def idle(self, result):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "scrum").mkdir()
        (tmp / "scrum" / "board.json").write_text(json.dumps({"jobs": JOBS["p"]}))
        with mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="1"), \
                mock.patch.object(serve.board, "projects", return_value={"p": tmp}), \
                mock.patch.object(serve, "live_ids", return_value=set()), \
                mock.patch.object(serve, "listeners", return_value=[]), \
                mock.patch.object(serve, "processes", return_value=[]), \
                mock.patch.object(serve, "docker_tick", return_value=False), \
                mock.patch.object(serve, "shop_cleanup", return_value=result):
            out = []
            with mock.patch.object(serve.board, "log_process", side_effect=lambda *a, **k: out.append((a, k))):
                serve.idle_cleanup({"p": False})
        return out

    def test_idle_cleanup_logs_shop_counts(self):
        self.assertEqual(self.idle({"a": (2, 1), "b": (1, 0)}),
                         [(("Idle cleanup", "cleaned"), {"dev_servers": 0, "orphans": 0, "docker": False,
                                                         "shop_procs": 3, "shop_files": 1})])
        self.assertEqual(self.idle({"a": (0, 0)}), [])

    def test_script_matches_only_finished_job_paths(self):
        main = load_script(["1894"], ["1894-x"])
        me = os.getpid()
        procs = [(10, 1, "node /private/tmp/scrum1894-explore/explore.mjs"), (11, 1, "zsh"),
                 (12, 1, "node /private/tmp/scrum18-explore/a.mjs"), (13, 1, "node /private/tmp/scrum1950-a/x"),
                 (14, 1, "git -C /r/.claude/worktrees/scrum-1894-x status"),
                 (15, 1, "git -C /r/.claude/worktrees/scrum-1894-xy status"),
                 (16, 1, "tail /tmp/scrum1894-log"), (me, 1, "python3 /private/tmp/scrum1894-self")]
        cwds = {11: "/private/tmp/scrum1894-explore", 12: "/private/tmp/scrum1894x"}
        killed = []
        got = main(["1894"], ["1894-x"], procs=procs, cwds=cwds, tmp=tempfile.mkdtemp(), kill=lambda p, s: killed.append((p, s)))
        self.assertEqual(sorted(killed), [(10, 15), (11, 15), (14, 15), (16, 15)])
        self.assertEqual(got, (4, 0))

    def test_script_removes_only_old_finished_files(self):
        main = load_script(["1894"], [])
        tmp = Path(tempfile.mkdtemp())
        now = time.time()
        old, young = now - 2 * 86400, now - 3600
        for name, t in [("1894-old", old), ("scrum1894-old", old), ("1894-new", young), ("1950-old", old),
                        ("other", old), ("scrum1950-old", old)]:
            (tmp / name).write_text("x")
            os.utime(tmp / name, (t, t))
        (tmp / "1894-dir").mkdir()
        (tmp / "1894-dir" / "f").write_text("x")
        os.utime(tmp / "1894-dir", (old, old))
        target = Path(tempfile.mkdtemp())
        (target / "keep").write_text("x")
        (tmp / "scrum1894-link").symlink_to(target)
        os.utime(tmp / "scrum1894-link", (old, old), follow_symlinks=False)
        got = main(["1894"], [], procs=[], cwds={}, tmp=str(tmp), now=now)
        self.assertEqual(sorted(os.listdir(tmp)), ["1894-new", "1950-old", "other", "scrum1950-old"])
        self.assertEqual(got, (0, 4))
        self.assertTrue((target / "keep").exists())


if __name__ == "__main__":
    unittest.main()
