import json, os, subprocess, sys, tempfile, threading, time, unittest, urllib.parse, urllib.request, urllib.error
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))

# A fake `claude`: records its argv, and answers estimate prompts with a fixed estimate.
STUB = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
if any("estimating" in a for a in sys.argv):
    print("Looking around...\n{\"points\": 5, \"why\": \"several files\"}")
else:
    import time; time.sleep(1.5)  # a job run stays "running" long enough to test double clicks
'''

BUILDER = "---\nname: scrum-builder\ndescription: Builds: the spec.\ntools: Read, Bash\nmodel: opus\n---\n\nBody <b>here</b>.\n"
REVIEWER = "---\nname: scrum-review-ui\nmodel: sonnet\nskills:\n    - frontend-design:frontend-design\n---\nReview.\n"


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.stub_log = base / "calls.jsonl"
        stub = base / "claude"
        stub.write_text(STUB)
        stub.chmod(0o755)
        os.environ.update(SCRUM_CLAUDE=str(stub), STUB_LOG=str(cls.stub_log), SCRUM_REGISTRY=str(base / "projects.json"))
        import serve  # noqa: E402  (reads SCRUM_CLAUDE at import)
        serve.CLAUDE = str(stub)  # another test class may have imported serve first
        cls.serve = serve
        cls.root = base / "repo" / "scrum"
        (cls.root / "jobs").mkdir(parents=True)
        (cls.root / "backlog.md").write_text("# Backlog\n- [ ] [3] Dark mode\n- [ ] CSV export\n")
        serve.board.cmd_register(base / "repo")
        cls.server = serve.make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        os.environ.pop("SCRUM_REGISTRY", None)
        cls.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                   data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(r) as res:
                return res.status, json.loads(res.read() or b"null") if "json" in res.headers.get("Content-Type", "") else None
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def calls(self):
        return [json.loads(l) for l in self.stub_log.read_text().splitlines()] if self.stub_log.exists() else []

    def wait_for(self, cond, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_serves_dashboard_projects_and_project_files_only(self):
        self.assertEqual(self.req("GET", "/dashboard.html")[0], 200)
        self.assertEqual(self.req("GET", "/api/projects"), (200, [{"name": "repo"}]))
        self.serve.board.cmd_new(self.root, "visible")
        self.assertEqual(self.req("GET", "/p/repo/board.json")[0], 200)
        for bad in ("/p/repo/../../calls.jsonl", "/p/repo/%2e%2e/%2e%2e/calls.jsonl", "/p/nope/board.json", "/../../etc/passwd"):
            self.assertEqual(self.req("GET", bad)[0], 404, bad)
        self.assertEqual(self.req("GET", "/api/p/nope/backlog")[0], 404)

    def test_get_backlog(self):
        code, items = self.req("GET", "/api/p/repo/backlog")
        self.assertEqual(code, 200)
        self.assertEqual(items[0]["text"], "Dark mode")

    def test_add_triggers_estimate_that_lands_in_backlog(self):
        code, items = self.req("POST", "/api/p/repo/backlog", {"op": "add", "text": "Export PDF"})
        self.assertEqual(code, 200)
        self.assertIsNone(items[-1]["points"])
        self.assertTrue(self.wait_for(lambda: self.serve.board.backlog_items(self.root)[-1]["points"] == 5))
        est = [c for c in self.calls() if any("Export PDF" in a for a in c)][0]
        self.assertIn("--model", est)
        self.assertEqual(est[est.index("--model") + 1], "sonnet")

    def test_edit_rejects_bad_points_with_400(self):
        self.assertEqual(self.req("POST", "/api/p/repo/backlog", {"op": "edit", "index": 0, "points": 4})[0], 400)
        self.assertEqual(self.req("POST", "/api/p/repo/backlog", {"op": "edit", "index": 0, "points": 8})[0], 200)

    def test_writes_need_json_and_localhost(self):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/p/repo/backlog", method="POST",
                                   data=b"op=delete&index=0", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        e.exception.close()
        self.assertEqual(e.exception.code, 403)
        self.assertEqual(self.req("POST", "/api/p/repo/backlog", {"op": "delete", "index": 0}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/p/repo/backlog", {"op": "delete", "index": 0}, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.serve.board.backlog_items(self.root)[0]["text"], "Dark mode")

    def test_run_now_claims_item_writes_feature_and_starts_claude(self):
        code, out = self.req("POST", "/api/p/repo/backlog/run", {"index": 1})
        self.assertEqual(code, 202)
        job_id = out["id"]
        self.assertEqual((self.root / "jobs" / job_id / "feature.md").read_text(), "CSV export\n")
        self.assertTrue(self.wait_for(lambda: any(f"/trevskills-scrum start {job_id}" in a for c in self.calls() for a in c)))
        self.assertEqual(self.req("POST", "/api/p/repo/backlog/run", {"index": 1})[0], 400)  # already claimed

    def test_approve_only_for_needs_human_and_passes_migration_confirmation(self):
        job_id = self.serve.board.cmd_new(self.root, "refunds")
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/approve", {})[0], 409)  # stage is spec
        self.serve.board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=Hard stop: schema — prisma/schema.prisma"])
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/approve", {"migrated": True})[0], 202)
        self.assertTrue(self.wait_for(lambda: any(f"/trevskills-scrum approve {job_id}" in a and "migrate" in a
                                                  for c in self.calls() for a in c)))
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/approve", {})[0], 409)  # already running
        code, runs = self.req("GET", "/api/runs")
        self.assertEqual(code, 200)
        self.assertIn(job_id, {r["id"] for r in runs})

    def test_rework_needs_feedback(self):
        job_id = self.serve.board.cmd_new(self.root, "rework me")
        self.serve.board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=blocked: x"])
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/rework", {"feedback": "  "})[0], 400)
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/rework", {"feedback": "use the existing helper"})[0], 202)
        self.assertEqual(self.req("POST", "/api/p/repo/jobs/..%2F..%2Fx/rework", {"feedback": "x"})[0], 400)

    def test_abort_stops_running_job_and_can_requeue(self):
        job_id = self.serve.board.cmd_new(self.root, "abort me")
        self.serve.board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=blocked: x"])
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/rework", {"feedback": "try again"})[0], 202)
        self.assertTrue(self.serve.running("repo", job_id))
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/abort", {"requeue": True})[0], 200)
        self.assertTrue(self.wait_for(lambda: not self.serve.running("repo", job_id)))
        self.assertEqual([j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id][0]["stage"], "aborted")
        self.assertIn("abort me", [i["text"] for i in self.serve.board.backlog_items(self.root) if not i["done"]])
        self.assertEqual(self.req("POST", f"/api/p/repo/jobs/{job_id}/abort", {})[0], 400)  # already aborted

    # --- runlog, Open terminal, activity line ---
    def job(self, title, *pairs):
        job_id = self.serve.board.cmd_new(self.root, title)
        if pairs:
            self.serve.board.cmd_set(self.root, job_id, list(pairs))
        return job_id

    def patch_board(self, job_id, **fields):
        """Write fields straight into board.json, past board.py's checks, as a hand-edited board would."""
        path = self.root / "board.json"
        data = json.loads(path.read_text())
        next(j for j in data["jobs"] if j["id"] == job_id).update(fields)
        path.write_text(json.dumps(data))

    def terminal(self, job_id, headers=None):
        with mock.patch.object(self.serve.subprocess, "run") as run, mock.patch.object(self.serve.subprocess, "Popen") as popen:
            run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
            code, out = self.req("POST", f"/api/p/repo/jobs/{job_id}/terminal", {}, headers)
        return code, out, run, popen

    def test_spawn_records_runlog(self):
        job_id = self.job("runlog me")
        with mock.patch.object(self.serve.subprocess, "Popen") as popen:
            self.serve.spawn("repo", self.root, job_id, "start", "x")
            self.serve.spawn("repo", self.root, "999-not-on-board", "start", "x")  # failure is ignored
        self.addCleanup(lambda: [self.serve.RUNS.pop(f"repo/{i}", None) for i in (job_id, "999-not-on-board")])
        self.assertEqual(popen.call_count, 2)
        job = next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)
        self.assertRegex(job["runlog"], rf"^runs/\d{{8}}-\d{{6}}-start-{job_id}\.log$")
        self.assertEqual(job["runlog"], self.serve.RUNS[f"repo/{job_id}"]["log"])

    def test_terminal_apple_terminal_passes_tty_as_argv(self):
        code, out, run, popen = self.terminal(self.job("tab", "tty=ttys004", "term=Apple_Terminal"))
        self.assertEqual(code, 200, out)
        argv = run.call_args.args[0]
        self.assertEqual((argv[0], argv[1], argv[-1]), ("osascript", "-e", "/dev/ttys004"))
        self.assertIn("on run argv", argv[2])
        self.assertIn("set index of w to 1", argv[2])
        self.assertNotIn("ttys004", argv[2])
        self.assertNotIn("shell", run.call_args.kwargs)
        code, out, run, _ = self.terminal(self.job("iterm", "tty=ttys005", "term=iTerm.app"))
        self.assertEqual(code, 200)
        self.assertEqual(run.call_args.args[0][-1], "/dev/ttys005")
        self.assertIn('application "iTerm"', run.call_args.args[0][2])

    def test_terminal_ghostty_returns_message(self):
        code, out, run, _ = self.terminal(self.job("ghost", "tty=ttys006", "term=ghostty"))
        self.assertEqual(code, 200)
        self.assertEqual(run.call_args.args[0], ["open", "-a", "Ghostty"])
        self.assertIn("ttys006", out["message"])

    def test_terminal_headless_tails_log(self):
        (self.root / "runs").mkdir(exist_ok=True)
        (self.root / "runs" / "h.log").write_text("x")
        code, out, run, _ = self.terminal(self.job("headless", "runlog=runs/h.log"))
        self.assertEqual(code, 200, out)
        argv = run.call_args.args[0]
        self.assertEqual((argv[0], argv[-1]), ("osascript", os.path.realpath(self.root / "runs" / "h.log")))
        self.assertIn("quoted form of", argv[2])

    def test_terminal_none_errors(self):
        code, out, run, popen = self.terminal(self.job("nothing"))
        self.assertTrue(400 <= code < 500)
        run.assert_not_called(); popen.assert_not_called()

    def test_terminal_rejects_bad_id(self):
        for bad in ("999-missing", "..%2F..%2Fx", "BAD"):
            code, _, run, popen = self.terminal(bad)
            self.assertTrue(400 <= code < 500, bad)
            run.assert_not_called(); popen.assert_not_called()

    def test_terminal_rejects_bad_tty(self):
        for fields in ({"tty": "ttys1; rm -rf ~"}, {"tty": "/dev/ttys1"}, {"tty": 5},
                       {"tty": "ttys1", "term": "xterm"}):
            job_id = self.job("bad tty")
            self.patch_board(job_id, **fields)
            code, _, run, popen = self.terminal(job_id)
            self.assertTrue(400 <= code < 500, fields)
            run.assert_not_called(); popen.assert_not_called()

    def test_terminal_rejects_log_outside_runs(self):
        runs = self.root / "runs"
        runs.mkdir(exist_ok=True)
        link = runs / "escape.log"
        if not link.is_symlink():
            link.symlink_to(self.root / "board.json")
        for log in ("runs/../board.json", "runs/escape.log", "runs/missing.log", "../calls.jsonl"):
            job_id = self.job("bad log")
            self.patch_board(job_id, runlog=log)
            code, _, run, popen = self.terminal(job_id)
            self.assertTrue(400 <= code < 500, log)
            run.assert_not_called(); popen.assert_not_called()

    def test_terminal_rejects_foreign_origin(self):
        job_id = self.job("origin", "tty=ttys007")
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            code, _, run, popen = self.terminal(job_id, headers)
            self.assertEqual(code, 403)
            run.assert_not_called(); popen.assert_not_called()

    def activity_of(self, job_id):
        code, data = self.req("GET", "/p/repo/board.json")
        self.assertEqual(code, 200)
        return next(j for j in data["jobs"] if j["id"] == job_id).get("activity")

    def touch(self, rel, text, ahead):
        path = self.root / "jobs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        t = time.time() + ahead
        os.utime(path, (t, t))

    def test_activity_line_counts_reviews(self):
        job_id = self.job("reviews", "stage=review")
        self.assertEqual(self.activity_of(job_id)["text"], "reviewers working")
        self.touch(f"{job_id}/round-1/review-security.md", "VERDICT: PASS\n", 5)
        self.touch(f"{job_id}/round-1/review-ui.md", "VERDICT: PASS\n", 6)
        act = self.activity_of(job_id)
        self.assertEqual(act["text"], "reviewers 2/4 done")
        self.assertAlmostEqual(act["at"], time.time() + 6, delta=2)

    def test_activity_line_check_fail(self):
        job_id = self.job("checks", "stage=check")
        self.touch(f"{job_id}/round-1/check.md", "CHECK: PASS\n", 3)
        self.touch(f"{job_id}/round-2/check.md", "CHECK: FAIL\n", 4)
        self.assertEqual(self.activity_of(job_id)["text"], "check FAIL (attempt 2)")

    def test_activity_line_pr_and_done(self):
        job_id = self.job("pr", "stage=merging", "pr=https://x/1")
        self.assertEqual(self.activity_of(job_id)["text"], "CI running")
        self.serve.board.cmd_set(self.root, job_id, ["stage=needs-human"])
        self.assertEqual(self.activity_of(job_id)["text"], "PR ready")
        self.serve.board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertIsNone(self.activity_of(job_id))

    def test_activity_line_builder_commit(self):
        wt = Path(self.tmp.name) / "wt-activity"
        job_id = self.job("commit")
        later = "@" + str(int(time.time()) + 30)  # newer than updatedAt, so the commit wins
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": later, "GIT_AUTHOR_DATE": later}
        wt.mkdir()
        for args in (["init", "-q", "-b", f"scrum/{job_id}"],
                     ["-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "--allow-empty", "-m", "Add <b>|thing</b>"]):
            out = subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
        self.serve.board.cmd_set(self.root, job_id, [f"worktree={wt}", "stage=build"])
        self.assertEqual(self.activity_of(job_id)["text"], "builder committed: Add <b>|thing</b>")
        self.serve.board.cmd_set(self.root, job_id, ["worktree=/nonexistent/wt"])  # missing worktree is ignored
        self.assertEqual(self.activity_of(job_id)["text"], "builder working")

    def fake_agents_and_claude_home(self):
        """A temp agents dir and a fake CLAUDE_HOME with user skills and user- and project-scope plugins."""
        base = Path(self.tmp.name) / self.id().rsplit(".", 1)[1]
        self.agents = base / "agents"
        self.agents.mkdir(parents=True)
        (self.agents / "scrum-builder.md").write_text(BUILDER)
        (self.agents / "scrum-review-ui.md").write_text(REVIEWER)
        home = base / "claude"
        for d in (home / "skills" / "grill-me", home / "skills" / "find-skills", home / "skills" / "no-skill-md"):
            d.mkdir(parents=True)
        (home / "skills" / "grill-me" / "SKILL.md").write_text("x")
        (home / "skills" / "find-skills" / "SKILL.md").write_text("x")
        for plugin, skill in (("superpowers", "brainstorming"), ("frontend-design", "frontend-design"), ("project-only", "nope")):
            (base / plugin / "skills" / skill).mkdir(parents=True)
            (base / plugin / "skills" / skill / "SKILL.md").write_text("x")
        (home / "plugins").mkdir()
        self.plugins = home / "plugins" / "installed_plugins.json"
        self.plugins.write_text(json.dumps({"version": 2, "plugins": {
            "superpowers@official": [{"scope": "user", "installPath": str(base / "superpowers")},
                                     {"scope": "user", "installPath": str(base / "superpowers")}],
            "frontend-design@official": [{"scope": "user", "installPath": str(base / "frontend-design")}],
            "project-only@official": [{"scope": "project", "installPath": str(base / "project-only")}]}}))
        patcher = mock.patch.dict(os.environ, SCRUM_AGENTS_DIR=str(self.agents), CLAUDE_HOME=str(home))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_agents_api_lists_agents_with_frontmatter_and_body(self):
        self.fake_agents_and_claude_home()
        code, agents = self.req("GET", "/api/agents")
        self.assertEqual(code, 200)
        self.assertEqual(agents, [
            {"name": "scrum-builder", "model": "opus", "tools": "Read, Bash", "description": "Builds: the spec.",
             "skills": [], "body": "\nBody <b>here</b>.\n"},
            {"name": "scrum-review-ui", "model": "sonnet", "tools": "", "description": "",
             "skills": ["frontend-design:frontend-design"], "body": "Review.\n"}])

    def test_skills_api_lists_user_and_plugin_skills(self):
        self.fake_agents_and_claude_home()
        want = [{"name": "find-skills", "source": "user"}, {"name": "frontend-design:frontend-design", "source": "frontend-design"},
                {"name": "grill-me", "source": "user"}, {"name": "superpowers:brainstorming", "source": "superpowers"}]
        self.assertEqual(self.req("GET", "/api/skills"), (200, want))
        for broken in ("{not json", json.dumps({"plugins": [1]})):
            self.plugins.write_text(broken)
            self.assertEqual(self.req("GET", "/api/skills"), (200, [want[0], want[2]]))
        self.plugins.unlink()
        self.assertEqual(self.req("GET", "/api/skills"), (200, [want[0], want[2]]))

    def test_add_skill_writes_frontmatter_list_and_is_idempotent(self):
        self.fake_agents_and_claude_home()
        code, agent = self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "grill-me"})
        self.assertEqual((code, agent["skills"]), (200, ["grill-me"]))
        self.assertEqual((self.agents / "scrum-builder.md").read_text(),
                         BUILDER.replace("model: opus\n", "model: opus\nskills:\n  - grill-me\n"))
        self.assertEqual(self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "superpowers:brainstorming"})[0], 200)
        after_two = (self.agents / "scrum-builder.md").read_text()
        self.assertIn("skills:\n  - grill-me\n  - superpowers:brainstorming\n---\n", after_two)
        self.assertEqual(self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "grill-me"})[0], 200)  # no-op
        self.assertEqual((self.agents / "scrum-builder.md").read_text(), after_two)
        # An existing block list keeps its indent; the one-line form becomes a block list.
        self.assertEqual(self.req("POST", "/api/agents/scrum-review-ui/skills", {"skill": "find-skills"})[0], 200)
        self.assertEqual((self.agents / "scrum-review-ui.md").read_text(),
                         REVIEWER.replace("frontend-design\n", "frontend-design\n    - find-skills\n", 1))
        (self.agents / "scrum-builder.md").write_text(BUILDER.replace("model: opus\n", "model: opus\nskills: grill-me\n"))
        self.assertEqual(self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "find-skills"})[1]["skills"],
                         ["grill-me", "find-skills"])
        self.assertIn("skills:\n  - grill-me\n  - find-skills\n---", (self.agents / "scrum-builder.md").read_text())

    def test_add_skill_skips_blank_and_comment_lines_in_block(self):
        self.fake_agents_and_claude_home()
        path = self.agents / "scrum-builder.md"
        cases = [  # (skills block as written, expected block after adding grill-me)
            ("skills:\n# picked by hand\n\n    - a\n    - b\n", "skills:\n# picked by hand\n\n    - a\n    - b\n    - grill-me\n"),
            ("skills:\n  - a\n  # note\n  - b\n", "skills:\n  - a\n  # note\n  - b\n  - grill-me\n"),
            ("skills:\n  - a\n  - b\n\n# next up\ncolor: blue\n", "skills:\n  - a\n  - b\n  - grill-me\n\n# next up\ncolor: blue\n"),
            ("skills:\n  # none yet\n\n", "skills:\n  - grill-me\n  # none yet\n\n"),
        ]
        for block, want in cases:
            path.write_text(BUILDER.replace("model: opus\n", "model: opus\n" + block))
            code, agent = self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "grill-me"})
            expected = ["grill-me"] if "- a" not in block else ["a", "b", "grill-me"]
            self.assertEqual((code, agent["skills"]), (200, expected), block)
            self.assertEqual(path.read_text(), BUILDER.replace("model: opus\n", "model: opus\n" + want), block)
            self.assertEqual(self.serve.read_agent(path)["skills"], expected, block)

    def test_add_skill_rejects_unknown_agent_unknown_skill_and_foreign_origin(self):
        self.fake_agents_and_claude_home()
        before = {p.name: p.read_text() for p in self.agents.iterdir()}
        (self.agents.parent / "outside.md").write_text(BUILDER)
        for name in ("nope", "..%2Foutside", "..", "scrum-builder.md"):
            self.assertEqual(self.req("POST", f"/api/agents/{name}/skills", {"skill": "grill-me"})[0], 404, name)
        for skill in ("not-installed", "project-only:nope", "no-skill-md", None, ["grill-me"]):
            self.assertEqual(self.req("POST", "/api/agents/scrum-builder/skills", {"skill": skill})[0], 400, skill)
        url = f"http://127.0.0.1:{self.port}/api/agents/scrum-builder/skills"
        r = urllib.request.Request(url, method="POST", data=b"{nope", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        e.exception.close()
        self.assertEqual(e.exception.code, 400)
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            self.assertEqual(self.req("POST", "/api/agents/scrum-builder/skills", {"skill": "grill-me"}, headers)[0], 403)
        r = urllib.request.Request(url, method="POST", data=b'{"skill": "grill-me"}', headers={"Content-Type": "text/plain"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        e.exception.close()
        self.assertEqual(e.exception.code, 403)
        self.assertEqual({p.name: p.read_text() for p in self.agents.iterdir()}, before)
        self.assertEqual((self.agents.parent / "outside.md").read_text(), BUILDER)


SECRET = "sk-planted-secret-123"


class AiSettingsTest(unittest.TestCase):
    """A fake home: CLAUDE_HOME, ~/.claude.json, one registered project, one listed only in ~/.claude.json, one found by
    the walk, plus .claude dirs under node_modules and Library that the walk must skip."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = self.home = Path(os.path.realpath(self.tmp.name)) / "home"
        self.user, self.managed = home / ".claude", Path(self.tmp.name) / "managed"
        self.reg, self.listed, self.walked = home / "reg", home / "listed", home / "code" / "x"
        for d in (self.user / "commands", self.reg / "scrum", self.reg / ".claude" / "commands", self.listed, self.walked / ".claude",
                  home / "node_modules" / "y" / ".claude", home / "Library" / "z" / ".claude", self.managed):
            d.mkdir(parents=True)
        (self.user / "commands" / "c.md").write_text("user c")
        (self.reg / ".claude" / "commands" / "c.md").write_text("project c <script>alert(1)</script>")
        (self.reg / ".mcp.json").write_text(json.dumps({"mcpServers": {"dup": {"command": "p"}}}))
        (home / ".claude.json").write_text(json.dumps({
            "mcpServers": {"dup": {"command": "u", "env": {"API": SECRET}, "headers": {"X": SECRET}}},
            "projects": {str(self.reg): {"mcpServers": {"dup": {"command": "l"}}}, str(self.listed): {},
                         str(home / "gone"): {}, str(home): {}}}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(self.reg)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(self.user), CLAUDE_MANAGED_DIR=str(self.managed),
                                  SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        self.serve = serve
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_address[1]}{path}") as res:
                body = res.read().decode()
                return res.status, json.loads(body), body
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None, ""

    def scope(self, sid):
        code, data, _ = self.get(f"/api/ai-settings?scope={urllib.parse.quote(sid)}")
        self.assertEqual(code, 200, sid)
        return {c["key"]: c for c in data["categories"]}, [c["key"] for c in data["categories"]]

    def item(self, item_id):
        return self.get(f"/api/ai-settings/item?id={urllib.parse.quote(item_id)}")

    def test_scope_discovery(self):
        code, data, _ = self.get("/api/ai-settings")
        self.assertEqual(code, 200)
        self.assertEqual(data["global"], [{"id": "global", "label": "Global"}])
        self.assertEqual(data["registered"], [{"id": "r:reg", "label": "reg"}])
        self.assertEqual([s["label"] for s in data["mac"]], ["code/x", "listed"])

    def test_inventory_counts(self):
        (self.user / "skills" / "s").mkdir(parents=True)
        (self.user / "skills" / "s" / "SKILL.md").write_text("x")
        (self.user / "skills" / "no-md").mkdir()
        for sub in ("agents", "rules", "projects/-p/memory"):
            (self.user / sub).mkdir(parents=True)
        (self.user / "agents" / "a.md").write_text("x")
        (self.user / "rules" / "r.md").write_text("x")
        (self.user / "CLAUDE.md").write_text("x")
        (self.user / "projects" / "-p" / "memory" / "m.md").write_text("x")
        (self.user / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": []}], "PreToolUse": [{"matcher": "Bash", "hooks": []}]}}))
        (self.user / "plugins").mkdir()
        (self.user / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"p@x": [{"scope": "user", "installPath": "/nope"}]}}))
        (self.reg / "CLAUDE.md").write_text("x")
        (self.reg / "CLAUDE.local.md").write_text("x")
        (self.reg / ".claude" / "settings.local.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": []}]}}))
        (self.managed / "managed-settings.json").write_text("{}")
        order = ["skills", "mcp", "commands", "agents", "rules", "config", "hooks", "plugins", "settings"]
        want = {"global": [1, 1, 1, 1, 1, 2, 2, 1, 2], "r:reg": [1, 3, 2, 1, 1, 4, 3, 1, 3],
                "m:code/x": [1, 1, 1, 1, 1, 2, 2, 1, 2], "m:listed": [1, 1, 1, 1, 1, 2, 2, 1, 2]}
        for sid, counts in want.items():
            cats, keys = self.scope(sid)
            self.assertEqual(keys, order, sid)
            self.assertEqual([cats[k]["count"] for k in order], counts, sid)
            for c in cats.values():
                self.assertEqual(c["count"], len(c["items"]))
                for it in c["items"]:
                    self.assertTrue({"id", "name", "scope", "path", "status"} <= set(it), it)
                    self.assertIn(it["scope"], ("managed", "local", "project", "user"))
        cats, _ = self.scope("r:reg")
        self.assertEqual([i["scope"] for i in cats["settings"]["items"]], ["managed", "local", "user"])
        self.assertEqual(sorted(i["name"] for i in cats["hooks"]["items"]), ["PreToolUse · Bash", "Stop · *", "Stop · *"])
        self.assertEqual(self.get("/api/ai-settings?scope=nope")[0], 404)
        self.assertEqual(self.get("/api/ai-settings?scope=m:node_modules/y")[0], 404)

    def test_missing_and_malformed_sources(self):
        for f in (self.home / ".claude.json", self.reg / ".mcp.json"):
            f.write_text("{not json")
        (self.user / "settings.json").write_text("[1, 2]")
        (self.reg / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": "nope", "Pre": [1]}}))
        (self.user / "plugins").mkdir()
        (self.user / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": [1]}))
        (self.managed / "managed-mcp.json").write_text(json.dumps({"mcpServers": "x"}))
        cats, _ = self.scope("r:reg")
        self.assertEqual({k: c["count"] for k, c in cats.items()},
                         {"skills": 0, "mcp": 0, "commands": 2, "agents": 0, "rules": 0, "config": 0, "hooks": 0, "plugins": 0, "settings": 1})
        code, data, _ = self.get("/api/ai-settings")
        self.assertEqual((code, [s["label"] for s in data["mac"]]), (200, ["code/x"]))

    def test_precedence(self):
        cats, _ = self.scope("r:reg")
        self.assertEqual({(i["scope"], i["status"]) for i in cats["mcp"]["items"]},
                         {("local", "wins"), ("project", "overridden"), ("user", "overridden")})
        self.assertEqual({(i["scope"], i["status"]) for i in cats["commands"]["items"]}, {("project", "wins"), ("user", "overridden")})
        cats, _ = self.scope("global")
        self.assertEqual([(i["scope"], i["status"]) for i in cats["mcp"]["items"]], [("user", "")])

    def test_item_detail(self):
        cats, _ = self.scope("r:reg")
        cmd = next(i for i in cats["commands"]["items"] if i["scope"] == "project")
        code, data, _ = self.item(cmd["id"])
        self.assertEqual((code, data["path"], data["content"]), (200, str(self.reg / ".claude" / "commands" / "c.md"),
                                                                 "project c <script>alert(1)</script>"))
        local = next(i for i in cats["mcp"]["items"] if i["scope"] == "local")
        code, data, _ = self.item(local["id"])
        self.assertEqual((code, json.loads(data["content"]), data["path"]), (200, {"command": "l"}, str(self.home / ".claude.json")))

    def test_item_rejects_unknown_and_traversal(self):
        for bad in ("", "nope", "global|commands|user|/etc/passwd|passwd", "../../etc/passwd",
                    f"r:reg|config|project|{self.reg}/../../../../etc/passwd|passwd", "m:../..|config|project|/etc/hosts|hosts"):
            self.assertEqual(self.item(bad)[0], 404, bad)

    def test_secrets_redacted(self):
        (self.reg / ".mcp.json").write_text(json.dumps({"mcpServers": {"dup": {"command": "p", "env": {"K": SECRET}},
                                                                       "h": {"url": "u", "headers": {"Authorization": SECRET}}}}))
        (self.managed / "managed-mcp.json").write_text(json.dumps({"mcpServers": {"m": {"env": {"K": SECRET}}}}))
        (self.user / "settings.json").write_text(json.dumps({"env": {"PLAIN": SECRET}, "nested": [{"my_api-key": SECRET, "apiKey": SECRET}],
                                                             "x": {"Password": SECRET, "ok": "visible"}}))
        _, _, body = self.get("/api/ai-settings?scope=r%3Areg")
        self.assertNotIn(SECRET, body)
        cats, _ = self.scope("r:reg")
        for cat in ("mcp", "settings"):
            for it in cats[cat]["items"]:
                code, data, body = self.item(it["id"])
                self.assertEqual(code, 200)
                self.assertNotIn(SECRET, body, it["id"])
        settings = next(i for i in cats["settings"]["items"] if i["scope"] == "user")
        content = json.loads(self.item(settings["id"])[1]["content"])
        self.assertEqual(content, {"env": {"PLAIN": "[redacted]"}, "nested": [{"my_api-key": "[redacted]", "apiKey": "[redacted]"}],
                                   "x": {"Password": "[redacted]", "ok": "visible"}})

    def test_read_only(self):
        snap = lambda: {p: p.stat().st_mtime_ns for p in self.home.rglob("*")}
        before = snap()
        self.get("/api/ai-settings")
        for sid in ("global", "r:reg", "m:listed", "m:code/x"):
            cats, _ = self.scope(sid)
            for c in cats.values():
                for it in c["items"]:
                    self.item(it["id"])
        self.assertEqual(snap(), before)

    # --- page 2: saving Markdown instruction files, with backup and undo ---

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"} | (headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.server.server_address[1]}{path}", method="POST", headers=h,
                                   data=json.dumps(body).encode())
        try:
            with urllib.request.urlopen(r) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def backups(self):
        d = self.user / "backups" / "ai-settings"
        return sorted(d.iterdir()) if d.is_dir() else []

    def plant_markdown(self):
        """{label: (path, item)} for a user CLAUDE.md, a project CLAUDE.local.md, a user rule and a memory file."""
        (self.user / "rules").mkdir()
        (self.user / "projects" / "p" / "memory").mkdir(parents=True)
        files = {"claude": self.user / "CLAUDE.md", "local": self.reg / "CLAUDE.local.md",
                 "rule": self.user / "rules" / "x.md", "memory": self.user / "projects" / "p" / "memory" / "m.md"}
        for label, f in files.items():
            f.write_text(f"old {label}\r\nline")
        items = [i for c in self.scope("r:reg")[0].values() for i in c["items"]]
        return {label: (f, next(i for i in items if i["path"] == str(f))) for label, f in files.items()}

    def save(self, it, content, version=None):
        return self.post("/api/ai-settings/save", {"id": it["id"], "content": content,
                                                    "version": version or self.item(it["id"])[1]["version"]})

    def test_save_writes_file_and_backup(self):
        for label, (f, it) in self.plant_markdown().items():
            self.assertTrue(it["editable"], label)
            before, old = len(self.backups()), self.item(it["id"])[1]
            self.assertTrue(old["editable"])
            code, data = self.save(it, f"new {label}")
            self.assertEqual((code, data["content"], f.read_text()), (200, f"new {label}", f"new {label}"), label)
            self.assertNotEqual(data["version"], old["version"])
            self.assertEqual(len(self.backups()), before + 1, label)
            newest = [b for b in self.backups() if b.name.endswith(urllib.parse.quote(str(f), safe=""))]
            self.assertEqual(newest[-1].read_bytes(), f"old {label}\r\nline".encode(), label)

    def test_save_follows_symlinked_rule(self):
        (self.user / "rules").mkdir()
        target = self.reg / "shared.md"
        target.write_text("old")
        (self.user / "rules" / "s.md").symlink_to(target)
        it = next(i for i in self.scope("global")[0]["rules"]["items"] if i["name"] == "s")
        self.assertEqual(self.save(it, "new")[0], 200)
        self.assertTrue((self.user / "rules" / "s.md").is_symlink())
        self.assertEqual(target.read_text(), "new")

    def test_save_rejects_non_editable_unknown_and_crafted_ids(self):
        (self.user / "skills" / "s").mkdir(parents=True)
        (self.user / "skills" / "s" / "SKILL.md").write_text("x")
        (self.user / "agents").mkdir()
        (self.user / "agents" / "a.md").write_text("x")
        (self.user / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": []}]}}))
        (self.reg / ".claude" / "settings.local.json").write_text("{}")
        (self.user / "plugins").mkdir()
        (self.user / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"p@x": []}}))
        (self.managed / "managed-settings.json").write_text("{}")
        planted = self.plant_markdown()
        snap = lambda: {p: p.stat().st_mtime_ns for p in [*self.home.rglob("*"), *self.managed.rglob("*")]}
        before = snap()
        cats, _ = self.scope("r:reg")
        for cat in ("settings", "hooks", "mcp", "plugins", "skills", "commands", "agents"):
            self.assertTrue(cats[cat]["items"], cat)
            for it in cats[cat]["items"]:
                self.assertFalse(it["editable"], it["id"])
                self.assertEqual(self.save(it, "pwned")[0], 403, it["id"])
                self.assertEqual(self.post("/api/ai-settings/undo", {"id": it["id"]})[0], 403, it["id"])
        for bad in ("nope", "", None, 5, "global|config|user|/etc/passwd|x", f"r:reg|config|local|{self.home / '.claude.json'}|x",
                    f"global|rules|user|{self.user}/rules/../../.claude.json|x"):
            self.assertEqual(self.post("/api/ai-settings/save", {"id": bad, "content": "pwned", "version": "1"})[0], 404, bad)
            self.assertEqual(self.post("/api/ai-settings/undo", {"id": bad})[0], 404, bad)
        _, it = planted["rule"]
        for content in (None, 5, ["x"], {"a": 1}):
            self.assertEqual(self.save(it, content)[0], 400, content)
        self.assertEqual(snap(), before)
        self.assertEqual(self.backups(), [])

    def test_save_conflict_when_file_changed(self):
        f, it = self.plant_markdown()["claude"]
        version = self.item(it["id"])[1]["version"]
        f.write_text("changed by an agent")
        os.utime(f, ns=(int(version) + 5_000_000, int(version) + 5_000_000))
        self.assertEqual(self.save(it, "mine", version)[0], 409)
        self.assertEqual(f.read_text(), "changed by an agent")
        self.assertEqual(self.backups(), [])

    def test_undo_restores_last_backup(self):
        planted = self.plant_markdown()
        f, it = planted["rule"]
        self.assertEqual(self.post("/api/ai-settings/undo", {"id": it["id"]})[0], 404)
        self.assertEqual(self.save(planted["claude"][1], "other file")[0], 200)  # another path's backup is ignored
        self.assertEqual(self.save(it, "new")[0], 200)
        code, data = self.post("/api/ai-settings/undo", {"id": it["id"]})
        self.assertEqual((code, data["content"], f.read_bytes()), (200, "old rule\r\nline", b"old rule\r\nline"))
        mine = [b for b in self.backups() if b.name.endswith(urllib.parse.quote(str(f), safe=""))]
        self.assertEqual([b.read_bytes() for b in mine], [b"old rule\r\nline", b"new"])

    def test_save_and_undo_need_json_and_localhost(self):
        f, it = self.plant_markdown()["rule"]
        version = self.item(it["id"])[1]["version"]
        body = {"id": it["id"], "content": "pwned", "version": version}
        for path in ("/api/ai-settings/save", "/api/ai-settings/undo"):
            for headers in ({"Content-Type": "text/plain"}, {"Origin": "https://evil.example"}, {"Host": "evil.example"}):
                self.assertEqual(self.post(path, body, headers)[0], 403, (path, headers))
        self.assertEqual(f.read_bytes(), b"old rule\r\nline")
        self.assertEqual(self.backups(), [])


if __name__ == "__main__":
    unittest.main()
