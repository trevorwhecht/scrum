"""Job 964: serve.py's shop_tick sends one held job to the shop Mac whenever a worker has room, and
cloud_tick requeues a shop session that ended without a PR. Every shop.py function is a mock: no test reaches ssh."""
import collections, contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # pulse.log, weekly/ never in the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log (job 903)
os.environ["SCRUM_MUTE"] = "1"
os.environ.pop("SCRUM_SHOP", None)  # a shop Mac sets it; cmd_set refuses lane=fast before B lilguy-fit (job 1400)
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_VM_PRESSURE"] = "1"  # kernel memory pressure normal unless a test says so; no test runs sysctl
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"

FEATURE = "Fix the widget\n"
SPEC = "# Spec\n## Likely files\n- `src/a.py`\n"
READY = {"ready": True, "up": True, "gh": True, "node": True, "claude": True, "accounts": {"main": True, "owa": True}}
SETUP = {"node": "ok", "gh": "ok", "gh login": "ok", "gh git": "ok", "owa links": "ok", "permissions": "ok",
         "account main": "ok", "account owa": "ok", "jev key": "ok"}
SHOP_FNS = ("probe", "ready", "md_sync", "setup", "clone", "stash_dirty", "env_copy", "profile_copy", "start", "run",
            "ended")
PAR = "041-run-all"
AUTO = "# Project\n- Test: x\n- Auto continue: 1\n"


class ShopTickTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.main, self.owa = self.base / "acct-main", self.base / "acct-owa"
        self.main.mkdir()
        self.owa.mkdir()
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.main / "usage.json"), SCRUM_ACCOUNTS=json.dumps(
            [["main", str(self.main), None], ["owa", str(self.owa), [80, 90]]]),
            SCRUM_FREE_RAM="5",  # below MIN_FREE_RAM_PCT: the guard holds work unless a test says otherwise
            SCRUM_REGISTRY=str(self.base / "projects.json"),  # no workers.txt (shopmac only) unless a test writes one
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")  # no insteadOf rewrites the origin URL
        env.start()
        self.addCleanup(env.stop)
        self.week(self.owa, 3600)  # owa's week resets first: pick_account's order puts it first unless a test says otherwise
        serve.SHOP_RETRY_AT.clear()
        self.addCleanup(serve.SHOP_RETRY_AT.clear)
        serve.SHOP_NOTES.clear()
        self.addCleanup(serve.SHOP_NOTES.clear)
        for s in (serve.CLOUD_LAST, serve.SHOP_PROBE_LAST, serve.RUNS, serve.IDLE_SINCE):
            s.clear()
            self.addCleanup(s.clear)
        self.projects = {}
        self.sh = mock.Mock()
        self.sh.probe.return_value = {"up": False, "load": None, "tools": {}}
        self.sh.ready.return_value = READY
        self.sh.md_sync.return_value = True
        self.sh.setup.return_value = dict(SETUP)
        self.sh.clone.return_value = (True, "")
        self.sh.stash_dirty.return_value = []
        self.sh.env_copy.return_value = "copied"
        self.sh.profile_copy.return_value = "copied"
        self.sh.start.return_value = 4242
        self.sh.run.return_value = subprocess.CompletedProcess(["ssh"], 0, "", "")
        self.sh.ended.return_value = None
        for p in (mock.patch.multiple(serve.shop, **{n: getattr(self.sh, n) for n in SHOP_FNS}),
                  mock.patch.object(self.board, "projects", side_effect=lambda: dict(self.projects)),
                  mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: False),
                  mock.patch.object(self.board, "jev_main_only", return_value=None),  # Jev down: the term list decides
                  mock.patch.object(self.board, "branch_pushed", return_value=False),  # job 1414: no pushed scrum/<id>, no ls-remote
                  mock.patch.object(serve, "run_terminal", side_effect=AssertionError("no Terminal window"))):
            p.start()
            self.addCleanup(p.stop)

    # --- fixtures ---
    def week(self, acct, secs):
        """acct's seven-day window resets `secs` from now, nothing else used."""
        (acct / "usage.json").write_text(json.dumps({"rate_limits": {"seven_day": {
            "used_percentage": 10, "resets_at": int(time.time()) + secs}}}))

    def project(self, name, jobs, profile="# Project\n- Test: x\n"):
        """A registered repo `name` (git, origin https://github.com/trevorwhecht/<name>.git) whose board holds `jobs`.
        A job's "feature" key is its feature.md (None: no file; default FEATURE), "likely" its spec.md Likely files."""
        repo = self.base / name
        shutil.rmtree(repo, ignore_errors=True)
        root = repo / "scrum"
        (root / "jobs").mkdir(parents=True)
        (repo / "src").mkdir()  # Likely files under src/ name this repo, not another (board.outside_repo_files)
        (root / "project.md").write_text(profile)
        (root / "backlog.md").write_text("# Backlog\n")
        board = []
        for j in jobs:
            j = dict(j)
            d = root / "jobs" / j["id"]
            d.mkdir()
            feature = j.pop("feature", FEATURE)
            if feature is not None:
                (d / "feature.md").write_text(feature)
            if likely := j.pop("likely", None):
                (d / "spec.md").write_text("# Spec\n## Likely files\n" + "".join(f"- `{p}`\n" for p in likely))
            if j.pop("fit", None):
                (d / "lilguy-fit.json").write_text('{"fit": true, "why": "tiny"}')
            board.append({"updatedAt": self.board.now(), "reason": None, **j})
        (root / "board.json").write_text(json.dumps({"jobs": board}))
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", f"https://github.com/trevorwhecht/{name}.git"],
                       check=True)
        self.projects[name] = repo
        return root

    def runall(self, *kids):
        """A running Run-all parent PAR and its waiting children (each kid a dict with at least an id)."""
        return [{"id": PAR, "stage": "running", "lane": "runall", "children": [k["id"] for k in kids]}] \
            + [{"stage": "waiting", "parent": PAR, **k} for k in kids]

    def queued(self, job_id="050-q", action="start", **extra):
        """A job spawn's gate queued in stage spec, with the queue fields shop dispatch must drop."""
        return {"id": job_id, "stage": "spec", "play_queued": True, "ram_hold": True,
                "queued_launch": {"action": action, "prompt": f"/trevskills-scrum {action} {job_id}", "stage": "spec"},
                **extra}

    def job(self, root, job_id):
        return self.board.find(self.board.read_board(root), job_id)

    def calls(self):
        """The shop functions called so far, in order."""
        return [c[0] for c in self.sh.mock_calls]

    def workers(self, text):
        """This test's workers.txt, beside setUp's SCRUM_REGISTRY."""
        (self.base / "workers.txt").write_text(text)

    def aliases(self, skip=()):
        """The alias= of every shop call so far but those named in `skip`, in order."""
        return [c.kwargs.get("alias") for c in self.sh.mock_calls if c[0] not in skip]

    def tick(self, name="mm"):
        """shop_tick for project `name`: (result, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = self.serve.shop_tick(name, self.projects[name], self.projects[name] / "scrum")
        return got, out.getvalue(), err.getvalue()

    def cloud(self, name="mm", project=None, now=None):
        """cloud_tick for repo `name` (shown as `project`); stderr."""
        root = self.projects[name] / "scrum"
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(self.serve, "spawn") as sp:
            self.serve.cloud_tick(project or name, root, self.board.read_board(root)["jobs"], now=now)
        sp.assert_not_called()  # nothing moved, so no cloud-home session
        return err.getvalue()

    # --- criterion 1: gates and the cap ---
    def test_dispatch_when_guard_passes(self):
        root = self.project("mm", self.runall({"id": "043-a"}))
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM=str(self.board.MIN_FREE_RAM_PCT), SCRUM_CPU_LOAD_PCT="1"):
            got, out, err = self.tick()  # this Mac's guard passes and a worker has room: the shop still takes it
        self.assertEqual((got, err), (True, ""))
        self.assertEqual(out, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n")
        self.assertEqual(self.job(root, "043-a")["stage"], "cloud")

    def test_hot_hand_start_goes_to_shop(self):
        """Job 1312: Trevor's Run now on a hot Mac queues a start launch (board.HeldStart), which shop_tick sends to a
        worker with room whatever this Mac's readings say."""
        root = self.project("mm", [{"id": "050-q", "stage": "spec"}])
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="100", SCRUM_CPU_LOAD_PCT="400", SCRUM_SWAP_PCT="0"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertIsNone(self.serve.spawn("mm", root, "050-q", "start", "/trevskills-scrum start 050-q",
                                                   manual=True))
            self.assertTrue(err.getvalue().startswith("spawn held: mm/050-q start: job 050-q queued, not started on this "
                                                      "Mac: CPU load 400%"), err.getvalue())
            job = self.job(root, "050-q")
            self.assertEqual(job["queued_launch"]["action"], "start")
            self.assertTrue(job["play_queued_manual"])
            self.assertEqual((root / "jobs" / "050-q" / "queue-gates.txt").read_text(), "hot_mac\n")
            self.assertEqual([j["id"] for j in self.serve.held_work("mm", self.board.read_board(root)["jobs"])], ["050-q"])
            got, out, err = self.tick()
        self.assertEqual((got, err), (True, ""))
        self.assertEqual(out, "shop: mm: 050-q: started on shopmac (pid 4242, account owa)\n")
        self.assertEqual(self.job(root, "050-q")["stage"], "cloud")

    def test_dispatch_through_cooldown(self):
        root = self.project("mm", self.runall({"id": "043-a"}))
        flag = self.base / "cooldown"
        flag.write_text("")
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag), SCRUM_FREE_RAM=str(self.board.MIN_FREE_RAM_PCT),
                             SCRUM_CPU_LOAD_PCT="1"):
            got, out, err = self.tick()  # cool-down holds work here, so the shop takes it though the sensors pass
        self.assertEqual((got, err), (True, ""))
        self.assertEqual(out, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n")
        self.assertEqual(self.job(root, "043-a")["stage"], "cloud")

    def test_cooled_worker_gets_no_new_work(self):
        """Job 1185: a worker whose own flag (cooldown-<alias> beside board.cooldown_path()) exists is skipped by
        shop_worker, unprobed, so neither shop_tick nor shop-room.json sends it work; without the flag it is back.
        Its flag never cools this Mac, and this Mac's flag never cools a worker."""
        self.workers("shopmac 2 owa,main\nnewmac 1 main\n")
        flag = self.base / "cooldown"
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag)):
            (self.base / "cooldown-shopmac").write_text("")
            self.assertEqual([w.alias for w, _ in self.serve.shop_worker()], ["newmac"])
            self.assertEqual(self.sh.ready.call_args_list, [mock.call(alias="newmac")], "a cooled worker is not probed")
            self.assertFalse(self.board.cooling_down(), "a worker's flag is not this Mac's cool-down")
            self.serve.write_shop_room()
            self.assertEqual(self.room_file()["workers"], ["newmac"])
            root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                                                  {"id": "044-b", "parallel": True, "likely": ["src/b.py"]}))
            self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on newmac (pid 4242, account main)\n", ""))
            self.sh.reset_mock()
            self.assertEqual(self.tick(), (False, "", ""), "newmac full, shopmac cooled")
            self.assertEqual(self.calls(), [])
            self.assertEqual(self.job(root, "044-b")["stage"], "waiting")
            (self.base / "cooldown-shopmac").unlink()
            flag.write_text("")  # this Mac's cool-down on: the shop still works
            self.assertEqual([w.alias for w, _ in self.serve.shop_worker()], ["shopmac"])
            self.assertEqual(self.tick(), (True, "shop: mm: 044-b: started on shopmac (pid 4242, account owa)\n", ""))

    def test_soft_cooldown_cap_gives_shop_no_worker(self):
        """Job 1308: while soft cool down is at its cap (live sessions plus shop jobs = 4) shop_worker yields nothing;
        under it the worker is back."""
        flag = self.base / "cooldown"
        (self.base / "soft-cooldown").write_text("")
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag)):
            with mock.patch.object(self.board, "live_sessions", return_value=4):
                self.assertEqual(list(self.serve.shop_worker()), [])
            with mock.patch.object(self.board, "live_sessions", return_value=3):
                self.assertEqual([w.alias for w, _ in self.serve.shop_worker()], ["shopmac"])

    def test_cooldown_api_per_worker(self):
        """Job 1185: set_cooldown(on, worker=<alias>) sets only that worker's flag, explicitly on or off; a worker that is
        not a current shop.workers() alias is a 400 that touches nothing; no worker is this Mac's flag, as before.
        machine_status's shop entries carry each worker's cooldown."""
        self.workers("shopmac 2 owa,main\nnewmac 1 main\n")
        flag = self.base / "state" / "cooldown"
        names = lambda: sorted(p.name for p in flag.parent.iterdir()) if flag.parent.is_dir() else []
        bad = (400, {"error": "worker must be a current shop Mac"})
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag)):
            for _ in range(2):  # idempotent
                self.assertEqual(self.serve.set_cooldown(True, "newmac"), (200, {"cooldown": True, "worker": "newmac"}))
            self.assertEqual(names(), ["cooldown-newmac"], "creates the dir and only newmac's flag")
            self.assertEqual([self.board.cooling_down(w) for w in ("newmac", "shopmac", None)], [True, False, False])
            for worker in ("third", "../cooldown", "-newmac", "newmac/x", "", 3, ["newmac"], True):
                with self.subTest(worker=worker):
                    self.assertEqual(self.serve.set_cooldown(False, worker), bad)
                    self.assertEqual(names(), ["cooldown-newmac"], "left as it was")
            self.assertEqual(self.serve.set_cooldown("yes", "newmac"), (400, {"error": "on must be true or false"}))
            self.assertEqual(self.serve.set_cooldown(True), (200, {"cooldown": True}))
            self.assertEqual(names(), ["cooldown", "cooldown-newmac"], "no worker: this Mac's own flag, as before")
            stats = [{"name": "shopmac", "free_ram_pct": 40.0, "cpu_load_pct": 10.0, "cpu_cores": 4, "at": 1000.0},
                     {"name": "newmac", "free_ram_pct": None, "cpu_load_pct": None, "cpu_cores": None, "at": 1000.0}]
            with mock.patch.object(self.serve, "shop_stats", return_value=stats), \
                    mock.patch.object(self.serve, "machine_history", return_value={}):
                status = self.serve.machine_status()
            self.assertEqual([(e["name"], e["cooldown"]) for e in status["shop"]], [("shopmac", False), ("newmac", True)])
            self.assertIs(status["cooldown"], True)
            self.assertEqual(self.serve.set_cooldown(False, "newmac"), (200, {"cooldown": False, "worker": "newmac"}))
            self.assertEqual(names(), ["cooldown"], "removes only newmac's flag")
            self.workers("newmac 1 main\n")  # shopmac left workers.txt: its button is refused, not a stray flag
            self.assertEqual(self.serve.set_cooldown(True, "shopmac"), bad)
            self.assertEqual(names(), ["cooldown"])

    def test_fast_job_goes_before_older_standard_job(self):
        root = self.project("mm", self.runall({"id": "043-a", "lane": "standard"}, {"id": "090-b", "lane": "fast"}))
        flag = self.base / "cooldown"
        flag.write_text("")
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag)):
            self.assertIs(self.tick()[0], True)
        self.assertEqual(self.job(root, "090-b")["stage"], "cloud")
        self.assertEqual(self.job(root, "043-a")["stage"], "waiting")

    def test_two_job_cap_across_boards(self):
        self.assertEqual(self.serve.shop.workers(), [("shopmac", 2, ("owa", "main"))])
        root = self.project("mm", self.runall({"id": "043-a"}))
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main", "lane": "fast"}])
        self.project("bb", [{"id": "020-y", "stage": "cloud", "shop": "12", "account": "owa", "lane": "fast"}])  # fast: job 1314's heavy limit never applies
        self.project("cc", [{"id": "030-z", "stage": "cloud"}])  # a claude.ai session: not on the shop
        self.assertEqual(self.tick(), (False, "", ""))
        self.assertEqual(self.calls(), [], "two shop jobs run: not even ready() is asked")
        self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        self.project("bb", [{"id": "020-y", "stage": "done"}])
        self.assertIs(self.tick()[0], True)
        self.assertEqual(self.job(root, "043-a")["shop"], "4242")

    def test_second_worker_when_first_full(self):
        self.workers("shopmac 2 owa,main\nnewmac 1 main\n")
        root = self.project("mm", self.runall({"id": "043-a"}, {"id": "044-b"}))
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main"},  # no worker: shopmac
                            {"id": "011-x", "stage": "cloud", "shop": "12", "account": "owa", "worker": "shopmac"},
                            {"id": "012-x", "stage": "done", "shop": "13", "worker": "newmac"},
                            {"id": "013-x", "stage": "aborted", "shop": "14", "worker": "newmac"},
                            {"id": "014-x", "stage": "waiting", "shop": "15", "worker": "newmac"}])
        got, out, err = self.tick()
        self.assertEqual((got, out, err), (True, "shop: mm: 043-a: started on newmac (pid 4242, account main)\n", ""))
        self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone", "env_copy", "profile_copy", "start"])
        self.assertEqual(self.aliases(), ["newmac"] * 7, "shopmac is full: never probed")
        job = self.job(root, "043-a")
        self.assertEqual((job["stage"], job["shop"], job["account"], job["worker"]),
                         ("cloud", "4242", "main", "newmac"))
        self.sh.reset_mock()
        self.assertEqual(self.tick(), (False, "", ""))
        self.assertEqual(self.calls(), [], "both workers full")
        self.assertEqual(self.job(root, "044-b")["stage"], "waiting")

    def test_unready_worker_skipped_for_next(self):
        self.workers("shopmac 2 owa,main\nnewmac 2 owa,main\nthird 2 owa,main\n")
        self.sh.ready.side_effect = lambda alias: READY if alias == "newmac" else dict(READY, ready=False)
        root = self.project("mm", self.runall({"id": "043-a"}))
        got, out, err = self.tick()
        self.assertEqual((got, out, err), (True, "shop: mm: 043-a: started on newmac (pid 4242, account owa)\n", ""))
        self.assertEqual(self.sh.ready.call_args_list, [mock.call(alias="shopmac"), mock.call(alias="newmac")],
                         "third is not probed")
        self.assertEqual(self.aliases(skip=("ready",)), ["newmac"] * 6)
        self.assertEqual(self.job(root, "043-a")["worker"], "newmac")

    def test_worker_account_list_limits_pick(self):
        (self.owa / "limit_until").write_text(f"{int(time.time()) + 3600}\n")  # pick_account names only main
        self.workers("solo 1 owa\nnewmac 2 main,owa\n")
        root = self.project("mm", self.runall({"id": "043-a"}))
        self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on newmac (pid 4242, account main)\n", ""))
        self.assertEqual(self.sh.ready.call_args_list, [mock.call(alias="solo"), mock.call(alias="newmac")])
        self.assertEqual((self.sh.start.call_args.args[3], self.job(root, "043-a")["account"]), ("main", "main"))
        with self.subTest("main resets first, but solo lists only owa"):
            (self.owa / "limit_until").unlink()
            self.week(self.main, 60)
            self.workers("solo 1 owa\n")
            self.sh.reset_mock()
            root = self.project("mm", self.runall({"id": "043-a"}))
            self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on solo (pid 4242, account owa)\n", ""))
            self.assertEqual(self.job(root, "043-a")["account"], "owa")
        with self.subTest("solo's ready() lacks owa"):
            self.sh.reset_mock()
            self.sh.ready.return_value = dict(READY, accounts={"owa": False})
            root = self.project("mm", self.runall({"id": "043-a"}))
            self.assertEqual(self.tick(), (False, "", ""))
            self.assertEqual(self.calls(), ["ready"])

    def test_no_workers_no_shop_call(self):
        self.workers("# no worker yet\nzero 0 main\n")
        roots = [self.project("mm", self.runall({"id": "043-a"})),
                 self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main"}])]
        before = [(r / "board.json").read_bytes() for r in roots]
        self.assertEqual(self.tick(), (False, "", ""))
        self.assertEqual(self.calls(), [])
        self.assertEqual([(r / "board.json").read_bytes() for r in roots], before)

    def test_backoff_per_worker(self):
        self.workers("shopmac 2 owa,main\nnewmac 1 main\n")
        self.sh.clone.side_effect = lambda project, url, alias: (alias == "newmac", "")  # clone fails on shopmac only
        root = self.project("mm", self.runall({"id": "043-a"}))
        t0 = time.time()
        self.assertEqual(self.tick(), (False, "", "shop: mm: 043-a: clone failed on shopmac\n"))
        self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        self.assertEqual(list(self.serve.SHOP_RETRY_AT), ["shopmac"])
        self.assertGreaterEqual(self.serve.SHOP_RETRY_AT["shopmac"], t0 + 600)
        self.assertLessEqual(self.serve.SHOP_RETRY_AT["shopmac"], time.time() + 600)
        self.sh.reset_mock()
        self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on newmac (pid 4242, account main)\n", ""))
        self.assertEqual(self.aliases(), ["newmac"] * 7, "no shop call to the backed-off worker")
        self.assertEqual(self.job(root, "043-a")["worker"], "newmac")

    def test_watchdog_runs_shop_tick_in_own_guard(self):
        for name in ("mm", "nn"):
            self.project(name, [])
        order = []
        real = self.board.subprocess.Popen

        def popen(argv, **kw):
            if argv[1:2] != ["-p"]:
                return real(argv, **kw)
            raise AssertionError(f"no claude session: {argv}")

        def shop_tick(project, repo, root):
            order.append(("shop", project, repo, root))
            raise RuntimeError("ssh fell over")

        err = io.StringIO()
        with mock.patch.object(self.serve, "cloud_tick", side_effect=lambda p, *a: order.append(("cloud", p))), \
                mock.patch.object(self.serve, "shop_tick", side_effect=shop_tick), \
                mock.patch.object(self.serve, "prune_worktrees", side_effect=lambda r, *a: order.append(("prune", r))), \
                mock.patch.object(self.serve, "actions_alert", return_value=None), \
                mock.patch.object(self.board.subprocess, "Popen", side_effect=popen), \
                contextlib.redirect_stderr(err):
            self.serve.watchdog_tick()
        mm, nn = self.projects["mm"], self.projects["nn"]
        self.assertEqual(order, [("cloud", "mm"), ("shop", "mm", mm, mm / "scrum"), ("prune", mm),
                                 ("cloud", "nn"), ("shop", "nn", nn, nn / "scrum"), ("prune", nn)])
        lines = err.getvalue().splitlines()
        self.assertEqual([l for l in lines if "ssh fell over" in l],
                         ["watchdog: mm: shop: ssh fell over", "watchdog: nn: shop: ssh fell over"])

    # --- criterion 2: the pool ---
    def test_never_dispatches_excluded_jobs(self):
        plain = "# Project\n- Test: x\n"
        cases = {
            "paused child": (plain, self.runall({"id": "043-a", "paused": True})),
            "lilguy child": (plain, self.runall({"id": "043-a", "feature": "Lane: lilguy\n\nFix the widget\n"})),
            "inline lane, fit, run-all parent": (plain, self.runall({"id": "043-a", "fit": True,
                                                 "feature": "Fix it. Lane: lilguy (tiny)\n"})),
            "fit true under run-all": (plain, self.runall({"id": "043-a", "fit": True})),
            "setup pending launch": (plain, [self.queued(setup="pending")]),
            "digest proposals": (plain, self.runall({"id": "043-a", "feature": "Apply scrum/digests/012/proposals.json\n"})),
            "queued approve": (plain, [self.queued(action="approve")]),
            "base branch": ("# Project\n- Base branch: dev\n- Test: x\n", self.runall({"id": "043-a"})),
            "docker": ("# Project\n- Dev command: DOCKER compose up\n", self.runall({"id": "043-a"})),
        }
        for why, (profile, jobs) in cases.items():
            with self.subTest(why):
                self.sh.reset_mock()
                root = self.project("mm", jobs, profile)
                before = (root / "board.json").read_bytes()
                self.assertEqual(self.tick(), (False, "", ""))
                self.assertEqual(self.calls(), [])
                self.assertEqual((root / "board.json").read_bytes(), before)
        with self.subTest("control: a plain child goes"):
            root = self.project("mm", self.runall({"id": "043-a"}))
            self.assertIs(self.tick()[0], True)

    def test_lowest_id_first(self):
        root = self.project("mm", [self.queued("1000-late")] + self.runall({"id": "999-b"}, {"id": "998-a"}))
        self.assertIs(self.tick()[0], True)
        self.assertEqual([j["id"] for j in self.board.read_board(root)["jobs"] if j["stage"] == "cloud"], ["998-a"])

    # --- criterion 3: the account ---
    def test_account_follows_pick_account_order_with_reserve_and_limit(self):
        ahead = int(time.time()) + 3600
        reserve = {"rate_limits": {"five_hour": {"used_percentage": 85, "resets_at": ahead},
                                   "seven_day": {"used_percentage": 10, "resets_at": ahead + 86400}}}
        sooner = lambda acct: {acct / "usage.json": json.dumps({"rate_limits": {"seven_day": {
            "used_percentage": 10, "resets_at": ahead - 60}}})}
        cases = [("owa resets first", sooner(self.owa), READY, "owa"),
                 ("main resets first", sooner(self.main), READY, "main"),
                 ("main resets first, shop lacks main", sooner(self.main),
                  dict(READY, accounts={"main": False, "owa": True}), "owa"),
                 ("no usage: account order", {}, READY, "main"),
                 ("owa limited", {self.owa / "limit_until": f"{ahead}\n", **sooner(self.owa)}, READY, "main"),
                 ("owa at reserve", {self.owa / "usage.json": json.dumps(reserve), **sooner(self.main)}, READY, "main"),
                 ("owa at reserve but resets first: primary", {self.owa / "usage.json": json.dumps({"rate_limits": {"seven_day": {"used_percentage": 95, "resets_at": ahead}}})}, READY, "owa"),
                 ("both limited", {self.owa / "limit_until": f"{ahead}\n", self.main / "limit_until": f"{ahead}\n"},
                  READY, None),
                 ("shop owa not ready", sooner(self.owa), dict(READY, accounts={"main": True, "owa": False}), "main")]
        for why, files, ready, account in cases:
            with self.subTest(why):
                for d in (self.main, self.owa):
                    for f in d.iterdir():
                        f.unlink()
                for path, text in files.items():
                    path.write_text(text)
                self.sh.reset_mock()
                self.sh.ready.return_value = ready
                root = self.project("mm", self.runall({"id": "043-a"}))
                before = (root / "board.json").read_bytes()
                got, out, err = self.tick()
                if account is None:
                    self.assertEqual((got, out, err), (False, "", ""))
                    self.assertEqual(self.calls(), ["ready"])
                    self.assertEqual((root / "board.json").read_bytes(), before, "the job is unchanged")
                else:
                    self.assertIs(got, True)
                    self.assertEqual(self.job(root, "043-a")["account"], account)
                    self.assertEqual(self.sh.start.call_args.args[3], account)

    # --- criterion 4: the steps and the mark ---
    def test_dispatch_marks_job_cloud_with_pid_and_account(self):
        with self.subTest("waiting child"):
            root = self.project("mm", self.runall({"id": "043-a", "likely": ["src/a.py"]}, {"id": "044-b"}))
            got, out, err = self.tick()
            self.assertEqual((got, err), (True, ""))
            repo = self.projects["mm"]
            self.assertEqual(self.sh.mock_calls, [
                mock.call.ready(alias="shopmac"), mock.call.md_sync(alias="shopmac"), mock.call.setup(alias="shopmac"),
                mock.call.clone("mm", "https://github.com/trevorwhecht/mm.git", alias="shopmac"),
                mock.call.env_copy("mm", str(repo), alias="shopmac"),
                mock.call.profile_copy("mm", str(repo), alias="shopmac"),
                mock.call.start("mm", "043-a", "/trevskills-scrum cloud-job 043-a Fix the widget\n\n\n## Pre-written spec"
                                "\n\n# Spec\n## Likely files\n- `src/a.py`\n", "owa", model="sonnet", alias="shopmac")])
            job = self.job(root, "043-a")
            self.assertEqual((job["stage"], job["shop"], job["account"], job["worker"]),
                         ("cloud", "4242", "owa", "shopmac"))
            self.assertTrue((root / "jobs" / "043-a" / "claimed-at.txt").is_file(), "claimed through cmd_ready")
            self.assertEqual((root / "jobs" / "043-a" / "feature.md").read_text(), FEATURE)
            self.assertEqual(self.job(root, "044-b")["stage"], "waiting", "one dispatch per call")
            self.assertEqual(self.job(root, PAR)["stage"], "running")
        with self.subTest("queued launch, no spec.md, no .env.local, no project.md"):
            self.board.cmd_set(root, "043-a", ["lane=fast"])  # job 1314: shopmac's one heavy slot is free again
            self.sh.reset_mock()
            self.sh.env_copy.return_value = "none"
            self.sh.profile_copy.return_value = "none"
            root = self.project("nn", [self.queued()])
            self.assertIs(self.tick("nn")[0], True)
            self.assertEqual(self.sh.start.call_args, mock.call(
                "nn", "050-q", "/trevskills-scrum cloud-job 050-q Fix the widget\n", "owa", model="sonnet",
                alias="shopmac"))
            job = self.job(root, "050-q")
            self.assertEqual((job["stage"], job["shop"], job["account"], job["worker"]),
                         ("cloud", "4242", "owa", "shopmac"))
            for gone in ("queued_launch", "play_queued", "ram_hold"):
                self.assertNotIn(gone, job)

    def test_shop_field_digits_only(self):
        root = self.project("mm", [{"id": "050-x", "stage": "build"}])
        board_py = ROOT / "skills" / "trevskills-scrum" / "board.py"
        bad = subprocess.run([sys.executable, str(board_py), "--dir", str(root), "set", "050-x", "shop=12a"],
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("shop must match ^[0-9]{1,10}$", bad.stdout + bad.stderr)
        self.assertNotIn("shop", self.job(root, "050-x"))
        for value in ("12345678901", "-1", " 12"):
            with self.subTest(value), self.assertRaises(SystemExit):
                self.board.cmd_set(root, "050-x", [f"shop={value}"])
        self.board.cmd_set(root, "050-x", ["shop=4242"])
        self.assertEqual(self.job(root, "050-x")["shop"], "4242")

    def test_worker_field_shape(self):
        root = self.project("mm", [{"id": "050-x", "stage": "build"}])
        board_py = ROOT / "skills" / "trevskills-scrum" / "board.py"
        bad = subprocess.run([sys.executable, str(board_py), "--dir", str(root), "set", "050-x", "worker=-x"],
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("worker must match ^[A-Za-z0-9][A-Za-z0-9._-]*$", bad.stdout + bad.stderr)
        self.assertNotIn("worker", self.job(root, "050-x"))
        for value in ("user@host", "new mac", ".x", "-oProxyCommand=x"):
            with self.subTest(value), self.assertRaises(SystemExit):
                self.board.cmd_set(root, "050-x", [f"worker={value}"])
        self.assertNotIn("worker", self.job(root, "050-x"))
        self.board.cmd_set(root, "050-x", ["worker=newmac"])
        self.assertEqual(self.job(root, "050-x")["worker"], "newmac")
        self.board.cmd_set(root, "050-x", ["worker="])
        self.assertIsNone(self.job(root, "050-x")["worker"])
        self.assertIn("/shop/worker (empty = null)", board_py.read_text().splitlines()[4], "the set usage line")

    # --- criterion 6: failures ---
    def test_failed_step_leaves_job_held(self):
        cases = {"md-sync": ("md_sync", False), "setup": ("setup", dict(SETUP, gh="failed")),
                 "setup account": ("setup", dict(SETUP, **{"account owa": "not ready"})),
                 "clone": ("clone", (False, "")), "env copy": ("env_copy", "failed"),
                 "profile copy": ("profile_copy", "failed"), "feature.md": (None, None), "start": ("start", None)}
        for why, (fn, value) in cases.items():
            for kind in ("child", "launch"):
                with self.subTest(why, kind=kind):
                    self.serve.SHOP_RETRY_AT.clear()
                    self.sh.reset_mock()
                    self.sh.configure_mock(**{"md_sync.return_value": True, "setup.return_value": dict(SETUP),
                                              "clone.return_value": (True, ""), "env_copy.return_value": "copied",
                                              "profile_copy.return_value": "copied",
                                              "start.return_value": 4242})
                    if fn:
                        getattr(self.sh, fn).return_value = value
                    feature = None if fn is None else FEATURE
                    job_id = "043-a" if kind == "child" else "050-q"
                    root = self.project("mm", self.runall({"id": "043-a", "feature": feature}) if kind == "child"
                                        else [self.queued(feature=feature)])
                    t0 = time.time()
                    got, out, err = self.tick()
                    self.assertEqual((got, out), (False, ""))
                    self.assertEqual(len(err.splitlines()), 1, err)
                    self.assertEqual(err, f"shop: mm: {job_id}: {why.removesuffix(' account')} failed on shopmac\n")
                    job = self.job(root, job_id)
                    if kind == "child":
                        self.assertEqual(job["stage"], "waiting")
                        self.assertFalse((root / "jobs" / job_id / "claimed-at.txt").exists())
                    else:
                        self.assertEqual(job["stage"], "spec")
                        self.assertEqual((job["queued_launch"]["action"], job["play_queued"], job["ram_hold"]),
                                         ("start", True, True))
                    self.assertNotIn("shop", job)
                    self.assertNotIn("start", self.calls()[:-1] if fn == "start" else self.calls())
                    self.sh.reset_mock()
                    self.assertEqual(self.tick(), (False, "", ""))
                    self.assertEqual(self.calls(), [], "backoff: no shop call")
                    self.assertGreaterEqual(self.serve.SHOP_RETRY_AT["shopmac"], t0 + 600)
                    self.assertLessEqual(self.serve.SHOP_RETRY_AT["shopmac"], time.time() + 600)

    # --- job 1415: a clone blocked by dirty tracked files ---
    GIT_ERR = ("error: Your local changes to the following files would be overwritten by merge: "
               "e2e/admin-dashboard-url-state.spec.ts Please commit your changes or stash them before you merge. Aborting")

    def backed_off(self, t0, alias="shopmac"):
        self.assertGreaterEqual(self.serve.SHOP_RETRY_AT[alias], t0 + 600)
        self.assertLessEqual(self.serve.SHOP_RETRY_AT[alias], time.time() + 600)

    def test_dirty_clone_stashed_and_retried_once(self):
        root = self.project("mm", self.runall({"id": "043-a"}))
        self.sh.clone.side_effect = [(False, self.GIT_ERR), (True, "")]
        self.sh.stash_dirty.return_value = ["e2e/admin-dashboard-url-state.spec.ts", "src/b.ts"]
        got, out, err = self.tick()
        self.assertEqual((got, out), (True, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n"))
        self.assertEqual(err, "shop: mm: 043-a: set aside e2e/admin-dashboard-url-state.spec.ts, src/b.ts on shopmac"
                              " (git stash)\n")
        self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone", "stash_dirty", "clone", "env_copy",
                                        "profile_copy", "start"])
        self.assertEqual(self.sh.stash_dirty.call_args, mock.call("mm", "043-a", alias="shopmac"))
        self.assertEqual(self.sh.clone.call_args_list,
                         [mock.call("mm", "https://github.com/trevorwhecht/mm.git", alias="shopmac")] * 2)
        self.assertEqual(self.job(root, "043-a")["stage"], "cloud")
        self.assertEqual(self.serve.SHOP_RETRY_AT, {}, "a retry that worked is no failure: no backoff")

    def test_dirty_clone_not_stashed_while_worker_busy(self):
        for busy in ({"worker": "shopmac"}, {}):  # no worker field: shopmac
            with self.subTest(busy=busy):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.clone.side_effect = [(False, self.GIT_ERR), (True, "")]
                self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main", "lane": "fast",
                                     **busy}])
                root = self.project("mm", self.runall({"id": "043-a", "lane": "fast"}))
                t0 = time.time()
                self.assertEqual(self.tick(), (False, "", f"shop: mm: 043-a: clone failed on shopmac: {self.GIT_ERR}\n"))
                self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone"], "a session there: never stashed")
                self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
                self.backed_off(t0)
        with self.subTest("a bad board hides its shop jobs: never stashed"):
            self.serve.SHOP_RETRY_AT.clear()
            self.sh.reset_mock()
            self.sh.clone.side_effect = [(False, self.GIT_ERR), (True, "")]
            self.project("aa", [])
            root = self.project("mm", self.runall({"id": "043-a"}))
            with mock.patch.object(self.board, "shop_jobs_by_worker", side_effect=[collections.Counter(), SystemExit("bad")]):
                self.assertEqual(self.tick(), (False, "", f"shop: mm: 043-a: clone failed on shopmac: {self.GIT_ERR}\n"))
            self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone"])
            self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main", "worker": "newmac"}])
        for stashed in ([], None):
            with self.subTest(stashed=stashed):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.clone.side_effect = [(False, self.GIT_ERR), (True, "")]
                self.sh.stash_dirty.return_value = stashed
                root = self.project("mm", self.runall({"id": "043-a"}))
                t0 = time.time()
                self.assertEqual(self.tick(), (False, "", f"shop: mm: 043-a: clone failed on shopmac: {self.GIT_ERR}\n"))
                self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone", "stash_dirty"],
                                 "nothing set aside: no retry")
                self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
                self.backed_off(t0)

    def test_clone_retry_failure_is_final(self):
        for kind in ("child", "launch"):
            with self.subTest(kind=kind):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.clone.side_effect = [(False, self.GIT_ERR), (False, "fatal: not a fast-forward"), (True, "")]
                self.sh.stash_dirty.return_value = ["a.ts"]
                job_id = "043-a" if kind == "child" else "050-q"
                root = self.project("mm", self.runall({"id": "043-a"}) if kind == "child" else [self.queued()])
                t0 = time.time()
                self.assertEqual(self.tick(), (False, "", f"shop: mm: {job_id}: set aside a.ts on shopmac (git stash)\n"
                                               f"shop: mm: {job_id}: clone failed on shopmac: fatal: not a fast-forward\n"))
                self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone", "stash_dirty", "clone"])
                job = self.job(root, job_id)
                if kind == "child":
                    self.assertEqual(job["stage"], "waiting")
                    self.assertFalse((root / "jobs" / job_id / "claimed-at.txt").exists())
                else:
                    self.assertEqual((job["stage"], job["queued_launch"]["action"]), ("spec", "start"))
                self.assertNotIn("shop", job)
                self.backed_off(t0)
                self.assertEqual(self.serve.SHOP_NOTES["shopmac"]["kind"], "failed")

    def test_clone_failure_line_carries_git_error(self):
        for why, line in ((self.GIT_ERR, f"shop: mm: 043-a: clone failed on shopmac: {self.GIT_ERR}\n"),
                          ("fatal: repository not found", "shop: mm: 043-a: clone failed on shopmac: fatal: repository not found\n"),
                          ("", "shop: mm: 043-a: clone failed on shopmac\n")):
            with self.subTest(why=why):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.clone.side_effect = None
                self.sh.clone.return_value = (False, why)
                self.project("mm", self.runall({"id": "043-a"}))
                self.assertEqual(self.tick(), (False, "", line))

    def test_shop_note_set_and_cleared(self):
        self.workers("shopmac 2 owa,main\nnewmac 1 main\n")
        self.sh.ready.side_effect = lambda alias: READY if alias == "shopmac" else dict(READY, ready=False)
        self.sh.md_sync.return_value = False
        self.project("mm", self.runall({"id": "043-a"}))
        t0 = time.time()
        self.tick()
        note = self.serve.SHOP_NOTES["shopmac"]
        self.assertEqual((note["text"], note["kind"]), ("mm: 043-a: md-sync failed on shopmac", "failed"))
        self.assertTrue(t0 <= note["at"] <= time.time())
        self.assertEqual(list(self.serve.SHOP_NOTES), ["shopmac"])
        stats = [{"name": "shopmac", "free_ram_pct": 40.0, "cpu_load_pct": 10.0, "cpu_cores": 4, "at": 1000.0},
                 {"name": "newmac", "free_ram_pct": None, "cpu_load_pct": None, "cpu_cores": None, "at": 1000.0}]
        with mock.patch.object(self.serve, "shop_stats", return_value=stats), \
                mock.patch.object(self.serve, "machine_history", return_value={}):
            status = self.serve.machine_status()
        self.assertEqual(status["shop"][0]["note"], {"text": "mm: 043-a: md-sync failed on shopmac", "kind": "failed",
                                                     "at": note["at"]})
        self.assertNotIn("note", status["shop"][1], "no note: the entry keeps its keys")
        self.serve.SHOP_RETRY_AT.clear()
        self.sh.md_sync.return_value = True
        self.assertIs(self.tick()[0], True)
        self.assertEqual(self.serve.SHOP_NOTES, {}, "a dispatch that worked clears the worker's note")
        self.serve.SHOP_RETRY_AT.clear()
        self.sh.clone.side_effect = [(False, self.GIT_ERR), (True, "")]
        self.sh.stash_dirty.return_value = ["a.ts"]
        self.project("aa", [])
        self.project("mm", self.runall({"id": "043-a"}))
        self.assertIs(self.tick()[0], True)
        note = self.serve.SHOP_NOTES["shopmac"]
        self.assertEqual((note["text"], note["kind"]), ("mm: 043-a: set aside a.ts on shopmac (git stash)", "stashed"),
                         "the same tick stashed: its note stays")

    def test_ruff_failure_does_not_block_dispatch(self):
        """Job 1160: ruff only feeds edit-check.py, which skips when ruff is missing, so `ruff: failed` never holds the
        shop; a failed required step or an unready account still stops the dispatch at setup."""
        cases = {"ruff only": (dict(SETUP, ruff="failed"), True),
                 "ruff and gh login": (dict(SETUP, ruff="failed", **{"gh login": "failed"}), False),
                 "ruff and account owa": (dict(SETUP, ruff="failed", **{"account owa": "not ready"}), False)}
        for why, (steps, sent) in cases.items():
            with self.subTest(why):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.setup.return_value = steps
                root = self.project("mm", self.runall({"id": "043-a"}))
                got, out, err = self.tick()
                if sent:
                    self.assertEqual((got, err), (True, ""), "a failed ruff step held the dispatch")
                    self.assertEqual(out, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n")
                    self.assertEqual(self.calls(),
                                     ["ready", "md_sync", "setup", "clone", "env_copy", "profile_copy", "start"])
                    self.assertEqual(self.job(root, "043-a")["stage"], "cloud")
                else:
                    self.assertEqual((got, out, err), (False, "", "shop: mm: 043-a: setup failed on shopmac\n"))
                    self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
                    self.assertNotIn("clone", self.calls())

    def test_refused_mark_kills_remote_session(self):
        def pause(*a, **kw):
            with self.board.locked_board(self.projects["mm"] / "scrum") as b:
                self.board.find(b, "043-a")["paused"] = True
            return 4242

        def run_here(*a, **kw):
            proc = mock.Mock()
            proc.poll.return_value = None
            self.serve.RUNS["mm/043-a"] = {"action": "start", "started": time.time(), "proc": proc, "log": "x"}
            return 4242

        for why, effect in (("paused meanwhile", pause), ("a local run started", run_here)):
            with self.subTest(why):
                self.serve.RUNS.clear()
                self.sh.reset_mock()
                self.sh.start.side_effect = effect
                root = self.project("mm", self.runall({"id": "043-a"}))
                got, out, err = self.tick()
                self.assertEqual((got, out), (False, ""))
                self.assertEqual(self.sh.run.call_args_list, [mock.call("kill 4242", 60, alias="shopmac")])
                self.assertEqual(len(err.splitlines()), 1, err)
                self.assertTrue(err.startswith("shop: mm: 043-a: "), err)
                job = self.job(root, "043-a")
                self.assertEqual(job["stage"], "spec")
                self.assertNotIn("shop", job)

    # --- criterion 7: a sleeping shop ---
    def test_unreachable_shop_skipped_silently(self):
        for name, state in (("asleep", {"ready": False, "up": False, "gh": False, "node": False, "claude": False,
                                        "accounts": {"main": False, "owa": False}}),
                            ("gh logged out", {"ready": False, "up": True, "gh": False, "node": True, "claude": True,
                                               "accounts": {"main": True, "owa": True}})):
            with self.subTest(name):
                self.sh.reset_mock()
                self.sh.ready.return_value = state
                root = self.project("mm", self.runall({"id": "043-a"}))
                before = (root / "board.json").read_bytes()
                self.assertEqual(self.tick(), (False, "", ""))
                self.assertEqual(self.calls(), ["ready"])
                self.assertEqual((root / "board.json").read_bytes(), before)
                self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
                self.assertEqual(self.serve.SHOP_RETRY_AT, {}, "not ready is no failure: no backoff")

    # --- criterion 8: dead shop sessions ---
    def test_dead_shop_session_requeued(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"},
                                   {"id": PAR, "stage": "running", "lane": "bigboy", "children": ["051-k"]},
                                   {"id": "051-k", "stage": "cloud", "parent": PAR, "shop": "4343", "account": "main",
                                    "feature": "Kid work\n"}])
        self.sh.ended.side_effect = lambda project, job_id, pid, alias: "Working on it\nDone for now\n"
        with mock.patch.object(self.board, "gh_api", return_value=[]) as gh:
            self.assertEqual(self.cloud(project="Mm Shown"), "")
        # cmd_cloud_sync ran for real and found no PR; then one close lookup per aborted job, with nothing to close
        self.assertEqual([c.args[1:] for c in gh.call_args_list], [(self.board.CLOUD_PULLS,)] * 3)
        self.assertEqual(self.sh.ended.call_args_list, [mock.call("mm", "050-x", 4242, alias="shopmac"),
                                                        mock.call("mm", "051-k", 4343, alias="shopmac")])
        for job_id in ("050-x", "051-k"):
            job = self.job(root, job_id)
            self.assertEqual((job["stage"], job["reason"]), ("aborted", "requeue: shop session ended without a PR"))
        backlog = (root / "backlog.md").read_text()
        self.assertIn("Fix the widget", backlog, "a parentless job's feature goes back on the backlog")
        self.assertNotIn("Kid work", backlog, "a BigBoy child is aborted without a requeue")
        self.assertFalse((self.owa / "limit_until").exists(), "no limit line: no account marked")

    def test_ended_asks_job_worker(self):
        self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa", "worker": "newmac"},
                            {"id": "051-y", "stage": "cloud", "shop": "4343", "account": "main"},
                            {"id": "052-z", "stage": "cloud"}])
        with mock.patch.object(self.board, "gh_api", return_value=[]):
            self.assertEqual(self.cloud(), "")
        self.assertEqual(self.sh.ended.call_args_list, [mock.call("mm", "050-x", 4242, alias="newmac"),
                                                        mock.call("mm", "051-y", 4343, alias="shopmac")])

    def test_dead_session_usage_limit_noted(self):
        reset = int(time.time()) + 7200
        now = float(int(time.time()))
        cases = [("epoch reset, owa job", "owa", f"Working\nAPI Error: usage limit reached resets_at={reset}\n",
                  self.owa, reset),
                 ("no reset, job with no account", None, "Working\nYou've hit your limit\n", self.main, int(now) + 1800)]
        for why, account, tail, acct_dir, until in cases:
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                for d in (self.main, self.owa):
                    (d / "limit_until").unlink(missing_ok=True)
                job = {"id": "050-x", "stage": "cloud", "shop": "4242"}
                root = self.project("mm", [dict(job, account=account) if account else job])
                self.sh.ended.side_effect = lambda *a, **kw: tail
                with mock.patch.object(self.board, "gh_api", return_value=[]):
                    self.assertEqual(self.cloud(now=now), "")
                self.assertEqual((acct_dir / "limit_until").read_text(), f"{until}\n")
                self.assertEqual(self.job(root, "050-x")["stage"], "aborted")

    def test_usage_limit_skips_job_gone_after_sync(self):
        # job 1414 moved note_limit before the stage check; a job no longer on the board still names no account
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.side_effect = lambda *a, **kw: "Working\nYou've hit your limit\n"

        def sync(r, ended=()):
            with self.board.locked_board(r) as b:
                b["jobs"].clear()
            return {"moved": [], "arrived": [], "error": None}

        with mock.patch.object(self.board, "cmd_cloud_sync", side_effect=sync) as cs:
            self.assertEqual(self.cloud(), "")
        self.assertEqual(cs.call_args, mock.call(root, ended=["050-x"]))
        for d in (self.main, self.owa):
            self.assertFalse((d / "limit_until").exists(), d.name)

    def test_unreachable_shop_leaves_cloud_job(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.return_value = None  # shop asleep, or the pid still runs claude
        with mock.patch.object(self.board, "gh_api", return_value=[]):
            self.assertEqual(self.cloud(), "")
        self.assertEqual(self.job(root, "050-x")["stage"], "cloud")
        self.serve.CLOUD_LAST.clear()
        self.sh.ended.return_value = "Session over\n"
        with mock.patch.object(self.board, "gh_api", side_effect=self.board.GhError("gh down")):
            self.assertEqual(self.cloud(), "cloud-sync: mm: gh down\n")
        self.assertEqual(self.job(root, "050-x")["stage"], "cloud", "a failed sync aborts nothing")

    def test_ended_session_syncs_before_the_poll_is_due(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.return_value = None
        with mock.patch.object(self.board, "gh_api", return_value=[]):
            self.cloud(now=1000.0)  # first poll: due
            self.sh.ended.return_value = "Session over\n"
            self.cloud(now=1030.0)  # 30 s later: probe not yet due, nothing happens
            self.assertEqual(self.job(root, "050-x")["stage"], "cloud")
            self.cloud(now=1061.0)  # probe due, session ended: sync runs although CLOUD_EVERY has not passed
        self.assertEqual(self.job(root, "050-x")["stage"], "aborted")

    def test_merged_shop_job_not_aborted(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        order = []

        def ended(*a, **kw):
            order.append("ended")
            return "Merged it\n"

        def sync(r, ended=()):
            order.append("sync")
            with self.board.locked_board(r) as b:
                self.board.find(b, "050-x").update(stage="done", pr="https://github.com/trevorwhecht/mm/pull/7")
            return {"moved": [{"id": "050-x", "state": "MERGED", "pr": "https://github.com/trevorwhecht/mm/pull/7",
                               "reason": None, "worktree": None, "artifacts": False}], "arrived": [], "error": None}

        self.sh.ended.side_effect = ended
        with mock.patch.object(self.board, "cmd_cloud_sync", side_effect=sync):
            self.assertEqual(self.cloud(), "")
        self.assertEqual(order, ["ended", "sync"])
        job = self.job(root, "050-x")
        self.assertEqual((job["stage"], job["reason"]), ("done", None))
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n")

    # --- job 990: an ended shop job's open unlabelled PR is closed, so the rerun opens no duplicate ---
    @staticmethod
    def pr(job_id, number, state="open", head_repo="trevorwhecht/mm", title=None, merged_at=None):
        """A REST PR for job_id on trevorwhecht/mm with no label."""
        return {"title": title or f"[scrum {job_id}] Fix the widget", "state": state, "number": number,
                "merged_at": merged_at, "labels": [], "html_url": f"https://github.com/trevorwhecht/mm/pull/{number}",
                "user": {"login": "bot"}, "body": "",
                "head": {"ref": f"scrum/{job_id}", "repo": {"full_name": head_repo}},
                "base": {"ref": "main", "repo": {"full_name": "trevorwhecht/mm"}}}

    @staticmethod
    def patches(gh):
        """The pulls/<n> PATCH endpoints gh_api was called with."""
        return [c.args[1] for c in gh.call_args_list if "-X" in c.args]

    def test_ended_shop_job_with_open_pr_brought_home(self):
        # job 1414: the ended session's own open PR is finished work: it comes home as a spec stall, never closed
        for why, tail in (("plain tail", "Opened the PR\n"), ("usage limit in the tail", "Working\nYou've hit your limit\n")):
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                (self.owa / "limit_until").unlink(missing_ok=True)
                root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"},
                                           {"id": PAR, "stage": "running", "lane": "bigboy", "children": ["051-k"]},
                                           {"id": "051-k", "stage": "cloud", "parent": PAR, "shop": "4343",
                                            "account": "owa", "feature": "Kid work\n"}])
                self.sh.ended.side_effect = lambda *a, **kw: tail
                prs = [self.pr("051-k", 12), self.pr("050-x", 11)]
                now = float(int(time.time()))
                with mock.patch.object(self.board, "gh_api", side_effect=lambda repo, ep, *f: {} if f else prs) as gh, \
                        mock.patch.object(self.board, "cloud_worktree", return_value="/wt") as wt, \
                        mock.patch.object(self.board, "artifacts_pushed", return_value=True) as ap:
                    self.assertEqual(self.cloud(now=now), "")  # cloud() asserts no cloud-home spawn
                repo = self.projects["mm"]
                self.assertEqual(wt.call_args_list, [mock.call(repo, "050-x", "scrum/050-x"),
                                                     mock.call(repo, "051-k", "scrum/051-k")])
                for job_id, n in (("050-x", 11), ("051-k", 12)):
                    job, url = self.job(root, job_id), f"https://github.com/trevorwhecht/mm/pull/{n}"
                    reason = f"stalled: shop session ended leaving PR {url} open; its branch scrum/{job_id} is home for the local pipeline"
                    self.assertEqual((job["stage"], job["stalled"], job["reason"], job["pr"], job["base"], job["worktree"],
                                      job["branch"]), ("spec", True, reason, url, "origin/main", "/wt", f"scrum/{job_id}"))
                    self.assertNotIn("shop", job)
                    self.assertNotIn("artifactsPending", job)
                    self.assertIsNone(job.get("lane"))
                self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n", "no requeue")
                self.assertEqual(self.patches(gh), [], "no PR closed")
                self.assertEqual(gh.call_count, 1, "only the sync's own read: no close lookup")
                ap.assert_not_called()
                if why == "plain tail":
                    self.assertFalse((self.owa / "limit_until").exists())
                else:  # the job left stage cloud, yet its session's limit line still marks the account
                    self.assertEqual((self.owa / "limit_until").read_text(),
                                     f"{int(now) + self.serve.AUTO_RESUME_EVERY}\n")

    def test_ended_shop_job_closes_only_own_open_pr(self):
        cases = [("closed", self.pr("050-x", 11, state="closed")),
                 ("merged", self.pr("050-x", 11, state="closed", merged_at="2026-11-18T00:00:00Z")),
                 ("another job id", self.pr("050-x", 11, title="[scrum 050-xy] Other")),
                 ("fork head", self.pr("050-x", 11, head_repo="someone/mm"))]
        for why, pr in cases:
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
                self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
                lists = iter([[], [pr]])  # the sync sees no PR; the close lookup sees this one
                with mock.patch.object(self.board, "gh_api",
                                       side_effect=lambda repo, ep, *f: {} if f else next(lists)) as gh:
                    self.assertEqual(self.cloud(), "")
                self.assertEqual(self.job(root, "050-x")["stage"], "aborted")
                self.assertEqual(gh.call_count, 2, "the sync's read and the close lookup")
                self.assertEqual(self.patches(gh), [])

    def test_merged_pr_any_head_spelling_is_done_not_aborted(self):
        merged = "2026-11-18T00:00:00Z"
        for why, ref, title in (("full head", "scrum/050-x", "[scrum 050-x] Fix"),
                                ("short head, short tag", "scrum/050", "[scrum 050] Fix"),
                                ("full head, no tag", "scrum/050-x", "Fix")):
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
                self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
                pr = self.pr("050-x", 11, state="closed", title=title, merged_at=merged)
                pr["head"]["ref"] = ref
                with mock.patch.object(self.board, "gh_api", side_effect=lambda repo, ep, *f: {} if f else [pr]), \
                        mock.patch.object(self.board, "merge_refusal", return_value=None), \
                        mock.patch.object(self.board, "artifacts_pushed", return_value=False):
                    self.assertEqual(self.cloud(), "")
                job = self.job(root, "050-x")
                self.assertEqual((job["stage"], job["pr"], job["reason"]),
                                 ("done", "https://github.com/trevorwhecht/mm/pull/11", None))

    def test_merged_fork_pr_still_shop_ended(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
        pr = self.pr("050-x", 11, state="closed", head_repo="someone/mm", merged_at="2026-11-18T00:00:00Z")
        with mock.patch.object(self.board, "gh_api", side_effect=lambda repo, ep, *f: {} if f else [pr]), \
                mock.patch.object(self.board, "merge_refusal", return_value=None), \
                mock.patch.object(self.board, "artifacts_pushed", return_value=False):
            self.cloud()
        job = self.job(root, "050-x")
        self.assertEqual((job["stage"], job["reason"]), ("aborted", "requeue: shop session ended without a PR"))

    def test_pr_close_failure_keeps_abort(self):
        def list_fails(repo, ep, *f):  # the sync's read sees no PR (job 1414: an open one comes home); the lookup fails
            if list_fails.n:
                raise self.board.GhError("gh down")
            list_fails.n += 1
            return []

        def patch_fails(repo, ep, *f):  # the sync's read sees no PR; the lookup finds the open one, whose PATCH fails
            if f:
                raise self.board.GhError("HTTP 403")
            patch_fails.n += 1
            return [] if patch_fails.n == 1 else [self.pr("050-x", 11)]

        for why, fake, err in (("list", list_fails, "gh down"), ("patch", patch_fails, "HTTP 403")):
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                list_fails.n = patch_fails.n = 0
                root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
                self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
                with mock.patch.object(self.board, "gh_api", side_effect=fake):
                    self.assertEqual(self.cloud(), f"cloud-sync: mm: 050-x: PR close failed: {err}\n")
                job = self.job(root, "050-x")
                self.assertEqual((job["stage"], job["reason"]), ("aborted", "requeue: shop session ended without a PR"))

    def test_no_close_when_abort_refused(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
        with mock.patch.object(self.board, "gh_api", return_value=[]) as gh, \
                mock.patch.object(self.board, "_cloud_abort",
                                  side_effect=SystemExit("job 050-x is done, not cloud; left alone")):
            self.assertEqual(self.cloud(), "cloud-sync: mm: 050-x: job 050-x is done, not cloud; left alone\n")
        self.assertEqual(gh.call_count, 1, "only the sync's own read")
        self.assertEqual(self.job(root, "050-x")["stage"], "cloud")

    # --- criterion 9: shop jobs hold their files ---
    def test_ready_shop_mode_claims_one_child(self):
        kids = ({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                {"id": "044-b", "parallel": True, "likely": ["src/b.py"]})
        root = self.project("mm", self.runall(*kids))
        self.assertEqual(self.board.cmd_ready(root, PAR)["ready"], [], "free RAM 5%: a normal call claims nothing")
        self.assertEqual(self.board.cmd_ready(root, PAR, (), shop="044-b")["ready"], ["044-b"])
        self.assertEqual([self.job(root, k)["stage"] for k in ("043-a", "044-b")], ["waiting", "spec"])
        with self.subTest("nothing to claim leaves the parent"):
            root = self.project("mm", self.runall({"id": "043-a", "depends_on": ["044-b"]}, {"id": "044-b"}))
            parent = self.job(root, PAR)
            self.assertEqual(self.board.cmd_ready(root, PAR, (), shop="043-a")["ready"], [])
            self.assertEqual(self.job(root, PAR), parent)
        with self.subTest("the usage cap holds it"):
            ahead = int(time.time()) + 3600
            for d in (self.main, self.owa):
                (d / "limit_until").write_text(f"{ahead}\n")
            root = self.project("mm", self.runall({"id": "043-a"}))
            parent = self.job(root, PAR)
            self.assertEqual(self.board.cmd_ready(root, PAR, (), shop="043-a")["ready"], [])
            self.assertEqual(self.job(root, PAR), parent)
            self.assertEqual(self.job(root, "043-a")["stage"], "waiting")

    def test_ready_shop_mode_keeps_overlap(self):
        cases = {
            "sibling in build shares a file": (self.runall(
                {"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                {"id": "045-c", "stage": "build", "parallel": True, "likely": ["src/a.py"]}), []),
            "parallel: no runs alone": (self.runall(
                {"id": "043-a", "likely": ["src/a.py"]},
                {"id": "045-c", "stage": "build", "parallel": True, "likely": ["src/z.py"]}), []),
            "outside job in build shares a file": (self.runall(
                {"id": "043-a", "parallel": True, "likely": ["src/a.py"]})
                + [{"id": "060-o", "stage": "build", "likely": ["src/a.py"]}], []),
        }
        for why, (jobs, want) in cases.items():
            with self.subTest(why):
                root = self.project("mm", jobs)
                self.assertEqual(self.board.cmd_ready(root, PAR, (), shop="043-a")["ready"], want)
                self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
                # no live session holds it, so the idle claim's only= mode would take it: shop mode holds by stage
                with mock.patch.dict(os.environ, SCRUM_FREE_RAM="100"):
                    self.assertEqual(self.board.cmd_ready(root, PAR, (), only="043-a")["ready"], ["043-a"])

    def test_cloud_job_holds_files_in_idle_claim(self):
        os.environ["SCRUM_FREE_RAM"] = "100"  # this Mac has room: the idle claim runs (setUp's env patch restores it)
        # 043-a has the fewest files, so it goes first unless a busy job holds src/a.py
        for stage, pick in (("cloud", "044-b"), ("done", "043-a")):
            with self.subTest(stage):
                self.serve.IDLE_SINCE.clear()
                root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                                                      {"id": "044-b", "parallel": True,
                                                       "likely": ["src/b.py", "src/c.py"]})
                                    + [{"id": "060-o", "stage": stage, "shop": "4242", "likely": ["src/a.py"]}])
                with mock.patch.object(self.serve, "spawn", return_value="runs/x.log") as spawn:
                    self.assertIs(self.serve.idle_claim("mm", root, self.board.read_board(root)["jobs"]), True)
                self.assertEqual([c.args[2] for c in spawn.call_args_list], [pick])
                self.assertEqual(self.job(root, pick)["stage"], "spec")
        with self.subTest("only= mode: a stage-cloud sibling holds"):
            root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                                                  {"id": "045-c", "stage": "cloud", "parallel": True,
                                                   "likely": ["src/a.py"]}))
            self.assertEqual(self.board.cmd_ready(root, PAR, (), only="043-a")["ready"], [])
            self.assertEqual(self.job(root, "043-a")["stage"], "waiting")

    # --- job 989: a queued launch skips files a running or cloud job holds ---
    def holder(self, kind, likely=("src/a.py",)):
        """Job 060-o holding `likely`, busy as `kind` (live: a serve.py run; watched: review with a live session; cloud;
        done: not busy). Returns its board entry; a live holder is put in RUNS, a watched one in session_alive_fn."""
        stage = {"live": "build", "watched": "review", "cloud": "cloud", "done": "done"}[kind]
        if kind == "live":
            proc = mock.Mock()
            proc.poll.return_value = None
            self.serve.RUNS["mm/060-o"] = {"action": "start", "started": time.time(), "proc": proc, "log": "x"}
        if kind == "watched":
            alive = mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: job["id"] == "060-o")
            alive.start()
            self.addCleanup(alive.stop)
        return {"id": "060-o", "stage": stage, **({"likely": list(likely)} if likely else {})}

    def assert_held(self, root, job_id="050-q"):
        job = self.job(root, job_id)
        self.assertEqual((job["stage"], job["queued_launch"]["action"]), ("spec", "start"))
        self.assertNotIn("shop", job)

    def test_queued_launch_overlapping_busy_job_not_sent(self):
        for kind in ("live", "watched", "cloud"):
            with self.subTest(kind):
                self.serve.RUNS.clear()
                self.sh.reset_mock()
                root = self.project("mm", [self.queued(likely=["src/a.py"]), self.holder(kind)])
                self.assertEqual(self.tick(), (False, "", ""))
                self.sh.start.assert_not_called()
                self.assert_held(root)
        with self.subTest("control: a done holder holds nothing"):
            self.serve.RUNS.clear()
            root = self.project("mm", [self.queued(likely=["src/a.py"]), self.holder("done")])
            self.assertIs(self.tick()[0], True)
            self.assertEqual(self.job(root, "050-q")["stage"], "cloud")

    def test_overlap_skips_to_next_pool_entry(self):
        root = self.project("mm", [self.queued("050-q", likely=["src/a.py"]), self.queued("051-r", likely=["src/b.py"]),
                                   self.holder("cloud")])
        got, out, err = self.tick()
        self.assertEqual((got, out, err), (True, "shop: mm: 051-r: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual(self.job(root, "051-r")["stage"], "cloud")
        self.assert_held(root)

    def test_unreadable_files_wait_while_busy(self):
        cases = [("unreadable launch, busy holder", None, ["src/z.py"], "cloud", False),
                 ("unreadable launch, nothing busy", None, ["src/z.py"], "done", True),
                 ("busy holder with unreadable files", ["src/a.py"], None, "cloud", False)]
        for why, mine, theirs, kind, sent in cases:
            with self.subTest(why):
                self.sh.reset_mock()
                root = self.project("mm", [self.queued(**({"likely": mine} if mine else {})),
                                           self.holder(kind, theirs)])
                self.assertIs(self.tick()[0], sent)
                if sent:
                    self.assertEqual(self.job(root, "050-q")["stage"], "cloud")
                else:
                    self.sh.start.assert_not_called()
                    self.assert_held(root)

    def test_no_launch_no_overlap_work(self):
        with mock.patch.object(self.serve, "busy_files", side_effect=AssertionError("overlap work")), \
                mock.patch.object(self.board, "machine_ok", side_effect=AssertionError("sensor read")):
            self.project("mm", [self.holder("cloud")])
            self.assertEqual(self.tick(), (False, "", ""), "no held job: no sensor read, no overlap work")
        with mock.patch.object(self.serve, "busy_files", side_effect=AssertionError("overlap work")):
            root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/b.py"]})
                                + [self.holder("cloud")])
            self.assertIs(self.tick()[0], True, "a child only: cmd_ready checks it, no busy list")
            self.assertEqual(self.job(root, "043-a")["stage"], "cloud")

    # --- job 1141: with nothing held, the shop claims new work the way auto-continue's `next` does ---
    def backlog(self, root, *lines, specs=None):
        """root's backlog.md with these open item lines; specs maps an item's text to its pre-written spec."""
        (root / "backlog.md").write_text("# Backlog\n" + "".join(f"- [ ] {line}\n" for line in lines))
        for text, spec in (specs or {}).items():
            path = self.board.spec_path(root, text)
            path.parent.mkdir(exist_ok=True)
            path.write_text(spec)

    def test_new_work_claimed_when_nothing_held(self):
        flag = self.base / "cooldown"
        for why, env in (("this Mac's guard holds", {}), ("cool down", {"SCRUM_COOLDOWN": str(flag)})):
            with self.subTest(why):
                flag.write_text("")
                self.sh.reset_mock()
                root = self.project("mm", [], AUTO)
                self.backlog(root, "Fix the gadget {p:3}", "Polish the knob {p:5}",
                             specs={"Polish the knob": SPEC, "Fix the gadget": SPEC.replace("a.py", "b.py").replace("# Spec", "# Spec\nLane: fast")})
                with mock.patch.dict(os.environ, env):
                    got, out, err = self.tick()
                self.assertEqual((got, out, err),
                                 (True, "shop: mm: 001-polish-the-knob: started on shopmac (pid 4242, account owa)\n", ""))
                self.assertEqual(self.calls(), ["ready", "md_sync", "setup", "clone", "env_copy", "profile_copy", "start"])
                self.assertEqual(self.sh.start.call_args.args[1:], (
                    "001-polish-the-knob", "/trevskills-scrum cloud-job 001-polish-the-knob Polish the knob\n\n\n"
                    "## Pre-written spec\n\n# Spec\n## Likely files\n- `src/a.py`\n", "owa"))
                job = self.job(root, "001-polish-the-knob")
                self.assertEqual((job["stage"], job["shop"], job["account"], job["worker"], job["started_by"]),
                                 ("cloud", "4242", "owa", "shopmac", "shop"))
                self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [ ] Fix the gadget {p:3}\n"
                                 "- [x] Polish the knob {p:5} → 001-polish-the-knob\n", "one claim per tick")
                self.assertEqual((root / "jobs" / "001-polish-the-knob" / "feature.md").read_text(), "Polish the knob\n")
        with self.subTest("the next tick claims the next item, then the worker is full"):
            self.assertEqual(self.tick(), (True, "shop: mm: 002-fix-the-gadget: started on shopmac (pid 4242, account owa)\n", ""))
            self.backlog(root, "Sand the lid")
            self.sh.reset_mock()
            self.assertEqual(self.tick(), (False, "", ""))
            self.assertEqual(self.calls(), [], "two shop jobs run: not even ready() is asked")
            self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [ ] Sand the lid\n")

    def test_held_work_goes_before_new_work(self):
        root = self.project("mm", self.runall({"id": "043-a"}), AUTO)
        self.backlog(root, "Polish the knob")
        self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [ ] Polish the knob\n")
        with self.subTest("a held child waiting on files still holds new work"):
            root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                                                  {"id": "045-c", "stage": "build", "parallel": True,
                                                   "likely": ["src/a.py"]}), AUTO)
            self.backlog(root, "Polish the knob")
            self.assertEqual(self.tick(), (False, "", ""))
            self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [ ] Polish the knob\n")
            self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        with self.subTest("held work the shop never takes does not hold new work"):
            root = self.project("mm", self.runall({"id": "043-a", "paused": True}), AUTO)
            self.backlog(root, "Polish the knob")
            self.assertEqual(self.tick(), (True, "shop: mm: 044-polish-the-knob: started on shopmac (pid 4242, account owa)\n", ""))
            self.assertEqual(self.job(root, "043-a")["stage"], "waiting")

    def test_new_work_follows_auto_continue_rules(self):
        def run_all():
            proc = mock.Mock()
            proc.poll.return_value = None
            self.serve.RUNS["mm/run-all"] = {"action": "run-all", "started": time.time(), "proc": proc, "log": "x"}

        cases = {  # why: (profile, backlog line, other board's jobs, setup)
            "no Auto continue line": ("# Project\n- Test: x\n", "Polish the knob", [], None),
            "its run-all session runs": (AUTO, "Polish the knob", [], run_all),
            "only a Human setup item": (AUTO, "Polish the knob {setup: buy a knob}", [], None),
        }
        for why, (profile, line, other, setup) in cases.items():
            with self.subTest(why):
                self.serve.RUNS.clear()
                self.sh.reset_mock()
                root = self.project("mm", [], profile)
                self.backlog(root, line)
                self.project("aa", other)
                if setup:
                    setup()
                before = [(root / f).read_bytes() for f in ("board.json", "backlog.md")]
                self.assertEqual(self.tick(), (False, "", ""))
                self.assertEqual(self.calls(), [])
                self.assertEqual([(root / f).read_bytes() for f in ("board.json", "backlog.md")], before)
        with self.subTest("control: the same board with none of them"):
            self.serve.RUNS.clear()
            root = self.project("mm", [], AUTO)
            self.backlog(root, "Polish the knob")
            self.project("aa", [])
            self.assertIs(self.tick()[0], True)

    def test_new_work_ignores_this_macs_queue_wait(self):
        """Job 1310: a job at `waiting: E2E queue` or Check queue on this Mac does not hold the shop's claim."""
        for reason in ("waiting: E2E queue (held)", "waiting: Check queue (held)"):
            with self.subTest(reason):
                self.serve.RUNS.clear()
                root = self.project("mm", [], AUTO)
                self.backlog(root, "Polish the knob")
                self.project("aa", [{"id": "010-x", "stage": "check", "reason": reason}])
                self.assertIs(self.tick()[0], True)
                self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [x] Polish the knob → 001-polish-the-knob\n")

    def test_new_work_skips_items_the_shop_never_takes(self):
        root = self.project("mm", [], AUTO)
        skipped = ["Lane: lilguy, fix the typo {p:5}", "Apply scrum/digests/012/proposals.json {p:5}",
                   "Tiny spec fix {p:5}", "Fix the mac thing. Runs on: main. {p:5}"]
        self.backlog(root, *skipped, "Fix the gadget {p:3}",
                     specs={"Tiny spec fix": "# Spec\nLane: lilguy\n\n## Likely files\n- `src/z.py`\n"})
        self.assertEqual(self.tick(), (True, "shop: mm: 001-fix-the-gadget: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n" + "".join(f"- [ ] {s}\n" for s in skipped)
                         + "- [x] Fix the gadget {p:3} → 001-fix-the-gadget\n")
        self.sh.reset_mock()
        self.assertEqual(self.tick(), (False, "", ""), "only items the shop never takes are left")
        self.sh.start.assert_not_called()

    def test_new_work_skips_items_overlapping_busy_jobs(self):
        root = self.project("mm", [self.holder("cloud")], AUTO)  # 060-o holds src/a.py
        held = ["Touch a {p:5}", "Touch `src/a.py` again {p:4}", "Vague fix {p:4}"]
        self.backlog(root, *held, "Touch b {p:3}", specs={"Touch a": SPEC, "Touch b": SPEC.replace("a.py", "b.py")})
        self.assertEqual(self.tick(), (True, "shop: mm: 061-touch-b: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n" + "".join(f"- [ ] {s}\n" for s in held)
                         + "- [x] Touch b {p:3} → 061-touch-b\n")
        with self.subTest("control: nothing busy, the top item goes"):
            root = self.project("mm", [self.holder("done")], AUTO)
            self.backlog(root, *held, specs={"Touch a": SPEC})
            self.assertEqual(self.tick()[1], "shop: mm: 061-touch-a: started on shopmac (pid 4242, account owa)\n")

    def test_failed_new_work_dispatch_becomes_held_launch(self):
        for fn, value, step in (("clone", (False, ""), "clone"), ("start", None, "start")):
            with self.subTest(step):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.configure_mock(**{"clone.return_value": (True, ""), "start.return_value": 4242})
                getattr(self.sh, fn).return_value = value
                root = self.project("mm", [], AUTO)
                self.backlog(root, "Polish the knob")
                self.assertEqual(self.tick(), (False, "", f"shop: mm: 001-polish-the-knob: {step} failed on shopmac\n"))
                job = self.job(root, "001-polish-the-knob")
                self.assertEqual((job["stage"], job["queued_launch"]),
                                 ("spec", {"action": "start", "prompt": "/trevskills-scrum start 001-polish-the-knob",
                                           "stage": "spec"}))
                self.assertTrue(job["play_queued"])
                self.assertNotIn("shop", job)
                self.assertEqual((root / "backlog.md").read_text(),
                                 "# Backlog\n- [x] Polish the knob → 001-polish-the-knob\n", "the claim is kept")
                self.assertEqual([j["id"] for j in self.serve.held_work("mm", self.board.read_board(root)["jobs"])],
                                 ["001-polish-the-knob"])
                self.serve.SHOP_RETRY_AT.clear()  # the backoff is over: the shop sends it as held work
                self.sh.configure_mock(**{"clone.return_value": (True, ""), "start.return_value": 4242})
                self.assertEqual(self.tick(), (True, "shop: mm: 001-polish-the-knob: started on shopmac (pid 4242, account owa)\n", ""))
                job = self.job(root, "001-polish-the-knob")
                self.assertEqual(job["stage"], "cloud")
                self.assertNotIn("queued_launch", job)

    # --- job 1155: the Runs on tag and shop-room.json ---
    def room_file(self):
        return json.loads((self.base / "shop-room.json").read_text())

    def test_shop_room_file_lists_workers_with_room(self):
        self.workers("shopmac 2 owa,main\nnewmac 1 main\nthird 1 owa\n")
        self.sh.ready.side_effect = lambda alias: dict(READY, ready=False) if alias == "third" else READY
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main"}])  # shopmac: 1 of 2
        t0 = time.time()
        self.serve.write_shop_room()
        room = self.room_file()
        self.assertEqual(room["workers"], ["shopmac", "newmac"])
        self.assertTrue(t0 <= room["at"] <= time.time())
        self.assertEqual(self.sh.ready.call_args_list, [mock.call(alias=a) for a in ("shopmac", "newmac", "third")])
        self.assertEqual(self.calls(), ["ready"] * 3, "no ssh beyond shop.ready's cached answer")
        self.assertEqual(sorted(p.name for p in self.base.iterdir() if p.name.startswith("shop-room")), ["shop-room.json"])
        self.assertTrue(self.board.shop_room(self.project("mm", self.runall({"id": "043-a"}))))

    def test_shop_room_file_empty_when_down_full_or_backoff(self):
        self.workers("shopmac 2 owa,main\nnewmac 1 main\nthird 1 owa\nfourth 1 owa\n")
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main"},  # shopmac full
                            {"id": "011-x", "stage": "cloud", "shop": "12", "account": "owa"}])
        self.serve.SHOP_RETRY_AT["newmac"] = time.time() + 600  # backed off
        self.sh.ready.side_effect = lambda alias: dict(READY, ready=False) if alias == "third" \
            else dict(READY, accounts={"main": True, "owa": False})  # third down; fourth lists only owa, not ready
        self.serve.write_shop_room()
        self.assertEqual(self.room_file()["workers"], [])
        self.assertEqual(self.sh.ready.call_args_list, [mock.call(alias="third"), mock.call(alias="fourth")],
                         "a full or backed-off worker is not probed")
        self.assertFalse(self.board.shop_room(self.project("mm", self.runall({"id": "043-a"}))))
        with self.subTest("under unittest with the registry not moved, nothing is written"):
            (self.base / "shop-room.json").unlink()
            with mock.patch.dict(os.environ), \
                    mock.patch.object(self.board, "registry_path", return_value=self.base / "projects.json"):
                del os.environ["SCRUM_REGISTRY"]
                self.serve.write_shop_room()
            self.assertFalse((self.base / "shop-room.json").exists())

    def test_shop_room_empty_and_silent_on_a_bad_board(self):
        """A bad board.json hides that board's shop jobs, so the file says no room (cmd_ready claims here) instead of
        raising; the watchdog's per-project loop reports that board."""
        self.workers("shopmac 2 owa,main\n")
        self.project("aa", [])
        (self.base / "shop-room.json").write_text('{"at": %d, "workers": ["shopmac"]}' % time.time())
        (self.project("bb", []) / "board.json").write_text("{not json")
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.serve.write_shop_room()
        self.assertEqual(self.room_file()["workers"], [])
        self.assertEqual(err.getvalue(), "")

    def test_shop_room_rewritten_after_dispatch(self):
        self.workers("shopmac 1 owa,main\n")
        root = self.project("mm", self.runall({"id": "043-a"}))
        seen, real = [], self.serve.write_shop_room

        def write():
            real()
            seen.append((self.room_file()["workers"], self.job(root, "043-a")["stage"]))

        with mock.patch.object(self.serve, "write_shop_room", side_effect=write), \
                mock.patch.object(self.serve, "cloud_tick"), mock.patch.object(self.serve, "prune_worktrees"), \
                mock.patch.object(self.serve, "actions_alert", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.serve.watchdog_tick()
        self.assertEqual(seen, [(["shopmac"], "waiting"), ([], "cloud")],
                         "once before the project loop, again after the dispatch filled shopmac")
        self.assertEqual(self.job(root, "043-a")["worker"], "shopmac")

    def test_runall_any_child_goes_to_shop(self):
        root = self.project("mm", self.runall({"id": "043-a", "parallel": True, "likely": ["src/a.py"]},
                                              {"id": "044-b", "parallel": True, "likely": ["src/b.py"],
                                               "feature": "Separate the art in PhotoCraft\n"}))
        self.serve.write_shop_room()
        with mock.patch.object(self.board, "ram_room", return_value=5), \
                mock.patch.dict(os.environ, SCRUM_FREE_RAM="100"):  # this Mac has room too
            self.assertEqual(self.board.cmd_ready(root, PAR)["ready"], ["044-b"], "the main child is claimed here")
        self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        self.assertIn("shop_first_since", self.job(root, "043-a"))
        self.assertEqual(self.tick(), (True, "shop: mm: 043-a: started on shopmac (pid 4242, account owa)\n", ""))
        job = self.job(root, "043-a")
        self.assertEqual((job["stage"], job["runs_on"], job["worker"]), ("cloud", "any", "shopmac"))
        self.assertNotIn("shop_first_since", job)

    def test_queued_start_of_shop_job_stays_queued_locally(self):
        os.environ["SCRUM_FREE_RAM"] = "100"  # this Mac has room (setUp's env patch restores it)
        shop_job = self.queued("050-q", feature="Runs on: shop\n\nFix the widget\n")
        root = self.project("mm", [shop_job, self.queued("051-r")])
        with mock.patch.object(self.serve, "spawn", return_value="runs/x.log") as spawn:
            self.assertIs(self.serve.play_queue_tick("mm", root, self.board.read_board(root)["jobs"]), True)
        self.assertEqual([c.args[2] for c in spawn.call_args_list], ["051-r"], "only the untagged launch starts here")
        self.assert_held(root)
        self.assertTrue(self.job(root, "050-q")["play_queued"])
        root = self.project("mm", [shop_job] + self.runall({"id": "043-a", "feature": "Runs on: shop\n"}))
        with mock.patch.object(self.serve, "spawn", return_value="runs/x.log") as spawn:
            self.assertIs(self.serve.idle_claim("mm", root, self.board.read_board(root)["jobs"]), False)
        spawn.assert_not_called()
        self.assert_held(root)
        self.assertEqual(self.job(root, "043-a")["stage"], "waiting")
        with self.subTest("control: an untagged queued start goes"):
            self.serve.IDLE_SINCE.clear()
            root = self.project("mm", [self.queued("051-r")])
            with mock.patch.object(self.serve, "spawn", return_value="runs/x.log") as spawn:
                self.assertIs(self.serve.idle_claim("mm", root, self.board.read_board(root)["jobs"]), True)
            self.assertEqual([c.args[2] for c in spawn.call_args_list], ["051-r"])

    def test_start_now_on_queued_shop_job_stays_queued(self):
        os.environ["SCRUM_FREE_RAM"] = "100"  # this Mac has room (setUp's env patch restores it)

        def click(job):
            root = self.project("mm", [job])
            with mock.patch.object(self.serve, "spawn", return_value="runs/x.log") as spawn:
                got = self.serve.Handler.route(None, "mm", root, "/jobs/050-q/resume", {"manual": True})
            return root, got, spawn

        root, got, spawn = click(self.queued("050-q", feature="Runs on: shop\n\nFix the widget\n"))
        spawn.assert_not_called()
        self.assertEqual(got, (202, {"id": "050-q", "action": "resume", "queued": True,
                                     "message": self.serve.PLAY_QUEUED}))
        job = self.job(root, "050-q")
        self.assertEqual((job["stage"], job["play_queued"], job["queued_launch"]),
                         ("spec", True, {"action": "start", "prompt": "/trevskills-scrum start 050-q", "stage": "spec"}))
        for feature in ("Runs on: any\n\nFix the widget\n", "Runs on: main\n\nFix the widget\n", FEATURE):
            with self.subTest(feature=feature):
                _, got, spawn = click(self.queued("050-q", feature=feature))
                self.assertEqual(got, (202, {"id": "050-q", "action": "resume"}))
                self.assertEqual([(c.args[2:4], c.kwargs) for c in spawn.call_args_list],
                                 [(("050-q", "start"), {"manual": True})])
        with self.subTest("a queued resume launch of a shop job is not blocked"):
            _, got, spawn = click(self.queued("050-q", action="resume", feature="Runs on: shop\n\nFix the widget\n"))
            self.assertEqual(got, (202, {"id": "050-q", "action": "resume"}))
            self.assertEqual([(c.args[2:4], c.kwargs) for c in spawn.call_args_list],
                             [(("050-q", "resume"), {"manual": True})])

    def test_shop_job_dispatched_when_room(self):
        root = self.project("mm", [self.queued("050-q", feature="Runs on: shop\n\nFix the widget\n")])
        self.assertEqual(self.tick(), (True, "shop: mm: 050-q: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual((self.job(root, "050-q")["stage"], self.job(root, "050-q")["runs_on"]), ("cloud", "shop"))

    def test_main_job_never_dispatched(self):
        root = self.project("mm", self.runall({"id": "043-a", "feature": "Runs on: main\n\nFix the widget\n"},
                                              {"id": "044-b", "feature": "Separate the art in PhotoCraft\n"},
                                              {"id": "045-c"})
                            + [self.queued("040-q", feature="Tell them by iMessage\n")])
        self.assertEqual(self.tick(), (True, "shop: mm: 045-c: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual(self.sh.start.call_count, 1)
        self.assertNotIn("PhotoCraft", self.sh.start.call_args.args[2])
        self.assertEqual({j: self.job(root, j).get("runs_on") for j in ("040-q", "043-a", "044-b", "045-c")},
                         {"040-q": "main", "043-a": "main", "044-b": "main", "045-c": "any"})
        self.assertEqual([self.job(root, j)["stage"] for j in ("043-a", "044-b")], ["waiting", "waiting"])
        self.assert_held(root, "040-q")
        with self.subTest("a pool of main jobs only sends nothing"):
            self.sh.reset_mock()
            self.assertEqual(self.tick(), (False, "", ""))
            self.assertEqual(self.calls(), ["ready"])
            self.assertEqual(self.serve.SHOP_RETRY_AT, {})

    def test_new_work_skips_item_naming_main_only_term(self):
        root = self.project("mm", [], AUTO)
        skipped = ["Separate the art in PhotoCraft {p:5}", "Tidy the copy {p:5}"]
        self.backlog(root, *skipped, "Fix the gadget {p:3}",
                     specs={"Tidy the copy": "# Spec\nSend it by iMessage.\n\n## Likely files\n- `src/z.py`\n"})
        inside, asked, real = [], [], self.board.cmd_next

        def cmd_next(*a, **kw):
            inside.append(True)
            try:
                return real(*a, **kw)
            finally:
                inside.pop()

        with mock.patch.object(self.board, "cmd_next", side_effect=cmd_next), \
                mock.patch.object(self.board, "jev_main_only", side_effect=lambda *a: asked.append(bool(inside))):
            self.assertEqual(self.tick(), (True, "shop: mm: 001-fix-the-gadget: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual(asked, [False], "Jev asked once, after the claim, never under cmd_next's lock")
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n" + "".join(f"- [ ] {s}\n" for s in skipped)
                         + "- [x] Fix the gadget {p:3} → 001-fix-the-gadget\n")

    def test_fresh_claim_tagged_main_stays_local_without_backoff(self):
        root = self.project("mm", [], AUTO)
        self.backlog(root, "Polish the knob")
        with mock.patch.object(self.board, "jev_main_only", return_value=True):  # Jev: it needs this Mac
            self.assertEqual(self.tick(), (False, "", ""))
        self.assertEqual(self.calls(), ["ready"], "no shop step")
        self.assertEqual(self.serve.SHOP_RETRY_AT, {})
        job = self.job(root, "001-polish-the-knob")
        self.assertEqual((job["stage"], job["runs_on"], job["queued_launch"]),
                         ("spec", "main", {"action": "start", "prompt": "/trevskills-scrum start 001-polish-the-knob",
                                           "stage": "spec"}))
        self.assertTrue(job["play_queued"])
        self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n- [x] Polish the knob → 001-polish-the-knob\n")
        self.sh.reset_mock()
        self.assertEqual(self.tick(), (False, "", ""), "the held main job is never sent")
        self.sh.start.assert_not_called()

    def test_board_with_activity_runs_on_fields(self):
        root = self.project("mm", self.runall({"id": "043-a", "feature": "Runs on: shop\n\nFix the widget\n"},
                                              {"id": "044-b", "runs_on": "main"}, {"id": "045-c"},
                                              {"id": "046-d", "stage": "cloud", "shop": "11", "runs_on": "shop"})
                            + [self.queued("050-q", feature="Runs on: shop\n"),
                               self.queued("051-r", action="approve", runs_on="shop"),
                               {"id": "060-x", "stage": "done", "runs_on": "any"}])
        data = self.serve.board_with_activity(root, "mm")
        self.assertEqual({j["id"]: (j.get("runsOn"), j.get("shopWait")) for j in data["jobs"]},
                         {PAR: (None, None), "043-a": ("shop", True), "044-b": ("main", None), "045-c": (None, None),
                          "046-d": ("shop", None), "050-q": ("shop", True), "051-r": ("shop", None),
                          "060-x": ("any", None)})

    # --- job 1314: this Mac's heavy cap and the shop worker's heavy limit ---
    STARTED = [{"id": "001-a", "stage": "build"}, {"id": "002-b", "stage": "check"}]  # two started heavy jobs: this Mac is at its cap

    def two_live(self):
        """Job 1381: heavy_count stops at live_sessions(); two live sessions let STARTED fill the cap."""
        live = mock.patch.object(self.board, "live_sessions", return_value=2)
        live.start()
        self.addCleanup(live.stop)

    def test_heavy_cap_shop_sends_heavy_before_fast(self):
        """At this Mac's cap shop_tick sends a heavy held job before a fast one; below it, fast goes first."""
        self.two_live()
        for name, started, want in (("at the cap", self.STARTED, "060-h"), ("below the cap", self.STARTED[:1], "070-f")):
            with self.subTest(name):
                self.sh.reset_mock()
                root = self.project("mm", [*started, self.queued("060-h"), self.queued("070-f", lane="fast")])
                got, out, err = self.tick()
                self.assertEqual((got, out, err), (True, f"shop: mm: {want}: started on shopmac (pid 4242, account owa)\n", ""))
                self.assertEqual(self.job(root, want)["stage"], "cloud")

    def test_heavy_cap_worker_with_heavy_job_gets_light_one(self):
        """A worker running one heavy job skips the heavy job in the pool and takes the first light one."""
        self.two_live()
        running = {"id": "010-c", "stage": "cloud", "shop": "11", "worker": "shopmac", "account": "main",
                   "likely": ["src/z.py"]}  # files known: a cloud job with none would hold every launch
        root = self.project("mm", [*self.STARTED, running, self.queued("060-h", likely=["src/a.py"]),
                                   self.queued("070-f", lane="fast", likely=["src/b.py"])])
        got, out, err = self.tick()
        self.assertEqual((got, out, err), (True, "shop: mm: 070-f: started on shopmac (pid 4242, account owa)\n", ""))
        self.assertEqual(self.job(root, "060-h")["stage"], "spec", "the heavy job waits")
        with self.subTest("a pool of heavy jobs only: nothing is sent"):
            self.sh.reset_mock()
            root = self.project("mm", [*self.STARTED, running, self.queued("060-h", likely=["src/a.py"])])
            self.assertEqual(self.tick(), (False, "", ""))
            self.assertEqual(self.job(root, "060-h")["stage"], "spec")
            self.assertNotIn("start", self.calls())

    def test_heavy_cap_serve_launches_hold_heavy_and_start_light(self):
        self.two_live()
        os.environ["SCRUM_FREE_RAM"] = "100"
        serve, board = self.serve, self.board
        with self.subTest("idle_claim"):
            serve.IDLE_SINCE.clear()
            root = self.project("mm", [*self.STARTED, self.queued("050-q"), self.queued("051-r", lane="fast")])
            with mock.patch.object(serve, "spawn", return_value="runs/x.log") as spawn:
                self.assertIs(serve.idle_claim("mm", root, board.read_board(root)["jobs"]), True)
            self.assertEqual([c.args[2] for c in spawn.call_args_list], ["051-r"], "the heavy start waits for the shop")
            serve.IDLE_SINCE.clear()
            root = self.project("mm", [*self.STARTED, self.queued("050-q")])
            with mock.patch.object(serve, "spawn", return_value="runs/x.log") as spawn:
                self.assertIs(serve.idle_claim("mm", root, board.read_board(root)["jobs"]), False)
            spawn.assert_not_called()
            self.assertIn("queued_launch", self.job(root, "050-q"))
        for lane, started in (("standard", False), ("fast", True)):
            with self.subTest(f"wake_waiting {lane}"):
                root = self.project("mm", [*self.STARTED, {"id": "059-d", "stage": "done"},
                                           {"id": "060-w", "stage": "waiting", "lane": lane, "depends_on": ["059-d"]}])
                with mock.patch.object(serve, "spawn") as spawn, mock.patch.object(board, "machine_ok", return_value=None), \
                        mock.patch.object(board, "ram_room", return_value=5), \
                        mock.patch.object(board, "pick_account", return_value=(None, None)):
                    serve.wake_waiting("mm", root)
                self.assertEqual([c.args[2] for c in spawn.call_args_list], ["060-w"] if started else [])
                self.assertEqual(self.job(root, "060-w")["stage"], "spec" if started else "waiting")
        for line, started in (("[5] Rebuild everything", False), ("[2] Polish the knob", True)):
            with self.subTest(f"auto_continue_tick {line}"):
                root = self.project("mm", list(self.STARTED), AUTO)
                self.backlog(root, line)
                with mock.patch.object(serve, "spawn") as spawn, mock.patch.object(board, "machine_ok", return_value=None), \
                        mock.patch.object(board, "live_sessions", return_value=2), mock.patch.object(serve, "running", return_value=False), \
                        mock.patch.object(board, "pick_account", return_value=(None, None)):
                    serve.auto_continue_tick({"mm": False})
                self.assertEqual(spawn.call_count, 1 if started else 0)


if __name__ == "__main__":
    unittest.main()
