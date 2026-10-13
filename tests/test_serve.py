import json, os, sys, tempfile, threading, time, unittest, urllib.request, urllib.error
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


if __name__ == "__main__":
    unittest.main()
