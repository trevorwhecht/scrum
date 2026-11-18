"""Job 964: serve.py's shop_tick sends one held job to the shop Mac whenever a worker has room, and
cloud_tick requeues a shop session that ended without a PR. Every shop.py function is a mock: no test reaches ssh."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # pulse.log, weekly/ never in the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log (job 903)
os.environ["SCRUM_MUTE"] = "1"
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
SHOP_FNS = ("probe", "ready", "md_sync", "setup", "clone", "env_copy", "profile_copy", "start", "run", "ended")
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
        for s in (serve.CLOUD_LAST, serve.RUNS, serve.IDLE_SINCE):
            s.clear()
            self.addCleanup(s.clear)
        self.projects = {}
        self.sh = mock.Mock()
        self.sh.probe.return_value = {"up": False, "load": None, "tools": {}}
        self.sh.ready.return_value = READY
        self.sh.md_sync.return_value = True
        self.sh.setup.return_value = dict(SETUP)
        self.sh.clone.return_value = True
        self.sh.env_copy.return_value = "copied"
        self.sh.profile_copy.return_value = "copied"
        self.sh.start.return_value = 4242
        self.sh.run.return_value = subprocess.CompletedProcess(["ssh"], 0, "", "")
        self.sh.ended.return_value = None
        for p in (mock.patch.multiple(serve.shop, **{n: getattr(self.sh, n) for n in SHOP_FNS}),
                  mock.patch.object(self.board, "projects", side_effect=lambda: dict(self.projects)),
                  mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: False),
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
        self.project("aa", [{"id": "010-x", "stage": "cloud", "shop": "11", "account": "main"}])
        self.project("bb", [{"id": "020-y", "stage": "cloud", "shop": "12", "account": "owa"}])
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
        self.sh.clone.side_effect = lambda project, url, alias: alias == "newmac"  # clone fails on shopmac only
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
                 "clone": ("clone", False), "env copy": ("env_copy", "failed"),
                 "profile copy": ("profile_copy", "failed"), "feature.md": (None, None), "start": ("start", None)}
        for why, (fn, value) in cases.items():
            for kind in ("child", "launch"):
                with self.subTest(why, kind=kind):
                    self.serve.SHOP_RETRY_AT.clear()
                    self.sh.reset_mock()
                    self.sh.configure_mock(**{"md_sync.return_value": True, "setup.return_value": dict(SETUP),
                                              "clone.return_value": True, "env_copy.return_value": "copied",
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

    def test_merged_shop_job_not_aborted(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        order = []

        def ended(*a, **kw):
            order.append("ended")
            return "Merged it\n"

        def sync(r):
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

    def test_ended_shop_job_closes_open_pr(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"},
                                   {"id": PAR, "stage": "running", "lane": "bigboy", "children": ["051-k"]},
                                   {"id": "051-k", "stage": "cloud", "parent": PAR, "shop": "4343", "account": "main",
                                    "feature": "Kid work\n"}])
        self.sh.ended.side_effect = lambda *a, **kw: "Opened the PR\n"
        prs = [self.pr("051-k", 12), self.pr("050-x", 11)]
        with mock.patch.object(self.board, "gh_api", side_effect=lambda repo, ep, *f: {} if f else prs) as gh:
            self.assertEqual(self.cloud(), "")
        for job_id in ("050-x", "051-k"):
            job = self.job(root, job_id)
            self.assertEqual((job["stage"], job["reason"]), ("aborted", "requeue: shop session ended without a PR"))
        backlog = (root / "backlog.md").read_text()
        self.assertIn("Fix the widget", backlog)
        self.assertNotIn("Kid work", backlog)
        self.assertEqual(self.patches(gh), ["repos/{owner}/{repo}/pulls/11", "repos/{owner}/{repo}/pulls/12"])
        for c in gh.call_args_list:
            if "-X" in c.args:
                self.assertEqual(c.args[2:], ("-X", "PATCH", "-f", "state=closed"))

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
        def list_fails(repo, ep, *f):
            if list_fails.n:
                raise self.board.GhError("gh down")
            list_fails.n += 1
            return [self.pr("050-x", 11)]

        def patch_fails(repo, ep, *f):
            if f:
                raise self.board.GhError("HTTP 403")
            return [self.pr("050-x", 11)]

        for why, fake, err in (("list", list_fails, "gh down"), ("patch", patch_fails, "HTTP 403")):
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                list_fails.n = 0
                root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
                self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
                with mock.patch.object(self.board, "gh_api", side_effect=fake):
                    self.assertEqual(self.cloud(), f"cloud-sync: mm: 050-x: PR close failed: {err}\n")
                job = self.job(root, "050-x")
                self.assertEqual((job["stage"], job["reason"]), ("aborted", "requeue: shop session ended without a PR"))

    def test_no_close_when_abort_refused(self):
        root = self.project("mm", [{"id": "050-x", "stage": "cloud", "shop": "4242", "account": "owa"}])
        self.sh.ended.side_effect = lambda *a, **kw: "Session over\n"
        with mock.patch.object(self.board, "gh_api", return_value=[self.pr("050-x", 11)]) as gh, \
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
                             specs={"Polish the knob": SPEC, "Fix the gadget": SPEC.replace("a.py", "b.py")})
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

        check = {"id": "010-x", "stage": "check", "reason": "waiting: Check queue (held)"}
        cases = {  # why: (profile, backlog line, other board's jobs, setup)
            "no Auto continue line": ("# Project\n- Test: x\n", "Polish the knob", [], None),
            "its run-all session runs": (AUTO, "Polish the knob", [], run_all),
            "finish_first: a job waits on the Check queue": (AUTO, "Polish the knob", [check], None),
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

    def test_new_work_skips_items_the_shop_never_takes(self):
        root = self.project("mm", [], AUTO)
        skipped = ["Lane: lilguy, fix the typo {p:5}", "Apply scrum/digests/012/proposals.json {p:5}",
                   "Tiny spec fix {p:5}"]
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
        for fn, value, step in (("clone", False, "clone"), ("start", None, "start")):
            with self.subTest(step):
                self.serve.SHOP_RETRY_AT.clear()
                self.sh.reset_mock()
                self.sh.configure_mock(**{"clone.return_value": True, "start.return_value": 4242})
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
                self.sh.configure_mock(**{"clone.return_value": True, "start.return_value": 4242})
                self.assertEqual(self.tick(), (True, "shop: mm: 001-polish-the-knob: started on shopmac (pid 4242, account owa)\n", ""))
                job = self.job(root, "001-polish-the-knob")
                self.assertEqual(job["stage"], "cloud")
                self.assertNotIn("queued_launch", job)


if __name__ == "__main__":
    unittest.main()
