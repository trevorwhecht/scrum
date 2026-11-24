"""agent-model-clamp.py: the PreToolUse hook board.spawn wires in through --settings (job 1240).
Each test feeds the script one hook event on stdin with HOME pointed at a temp dir whose .claude/agents links the
repo's agents, so the real frontmatter pins decide."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "trevskills-scrum" / "agent-model-clamp.py"


class AgentModelClampTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        agents = self.home / ".claude" / "agents"
        agents.mkdir(parents=True)
        for md in (ROOT / "agents").glob("*.md"):
            (agents / md.name).symlink_to(md)
        (agents / "scrum-fixture-haiku.md").write_text("---\nname: scrum-fixture-haiku\nmodel: haiku\n---\nbody\n")

    def run_hook(self, stdin):
        return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, text=True, timeout=30,
                              env={**os.environ, "HOME": str(self.home)})

    def event(self, kind, model=None, tool="Agent"):
        tool_input = {"description": "Review UI", "prompt": "Review round 1", "subagent_type": kind}
        if model is not None:
            tool_input["model"] = model
        return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input})

    def assert_untouched(self, stdin):
        out = self.run_hook(stdin)
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))

    def test_review_ui_on_opus_is_clamped_to_sonnet(self):
        out = self.run_hook(self.event("scrum-review-ui", "opus"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "updatedInput": {"description": "Review UI", "prompt": "Review round 1", "subagent_type": "scrum-review-ui",
                             "model": "sonnet"}}})

    def test_pricier_overrides_and_task_tool_are_clamped(self):
        for kind, model, tool, pin in (("scrum-review-code", "fable", "Agent", "sonnet"),
                                       ("scrum-digest-reader", "claude-opus-4-6", "Agent", "sonnet"),
                                       ("scrum-tracker", "opus", "Task", "sonnet"),
                                       ("scrum-fixture-haiku", "sonnet", "Agent", "haiku"),
                                       ("scrum-fixture-haiku", "claude-sonnet-4-5", "Agent", "haiku")):
            out = self.run_hook(self.event(kind, model, tool))
            self.assertEqual(json.loads(out.stdout)["hookSpecificOutput"]["updatedInput"]["model"], pin, (kind, model))

    def test_review_code_with_no_model_is_untouched(self):
        self.assert_untouched(self.event("scrum-review-code"))

    def test_same_or_cheaper_model_is_untouched(self):
        for kind, model in (("scrum-review-code", "sonnet"), ("scrum-review-e2e", "claude-sonnet-4-5"),
                            ("scrum-review-ux", "haiku"), ("scrum-fixture-haiku", "haiku")):
            with self.subTest(kind=kind, model=model):
                self.assert_untouched(self.event(kind, model))

    def test_builder_on_opus_is_untouched(self):
        self.assert_untouched(self.event("scrum-builder", "opus"))

    # Job 1438: a model-less builder call follows its job's Model decision.
    def job(self, feature="Do a thing\n\n## Goal\nx\n", spec=None, log=None):
        d = self.home / "jobs" / "1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "feature.md").write_text(feature)
        if spec is not None:
            (d / "spec.md").write_text(spec)
        if log is not None:
            (d / "jev.log").write_text(log)
        return d

    def builder(self, d):
        stdin = json.dumps({"tool_name": "Agent", "tool_input": {
            "subagent_type": "scrum-builder", "description": "Build", "prompt": f"JOB_DIR={d}\nBuild it."}})
        out = self.run_hook(stdin)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return json.loads(out.stdout)["hookSpecificOutput"]["updatedInput"].get("model") if out.stdout else None

    def test_builder_sonnet_when_jev_log_last_model_line_says_sonnet(self):
        d = self.job(log="t\tmodel\tq\traw\topus\t1\nt\tspec-model\tq\traw\topus\t1\nt\tmodel\tq\traw\tsonnet\t1\n")
        self.assertEqual(self.builder(d), "sonnet")

    def test_builder_opus_when_last_model_line_says_opus_even_if_complex_no(self):
        d = self.job(feature="Complex: no\nx\n", log="t\tmodel\tq\traw\topus\t1\n")
        self.assertIsNone(self.builder(d))

    def test_builder_sonnet_from_complex_no_header_and_logs_it(self):
        d = self.job(feature="Complex: no\nx\n## Goal\n")
        self.assertEqual(self.builder(d), "sonnet")
        fields = (d / "jev.log").read_text().splitlines()[-1].split("\t")
        self.assertEqual((fields[1], fields[4]), ("model", "sonnet"))

    def test_builder_complex_no_from_spec_when_feature_has_no_header(self):
        self.assertEqual(self.builder(self.job(spec="Complex: no\n## AC\n")), "sonnet")

    def test_builder_untouched_without_no_header_or_with_yes(self):
        for feature in ("Plain\n## Goal\n", "Complex: yes\n## Goal\n"):
            self.assertIsNone(self.builder(self.job(feature=feature)))

    def test_builder_with_model_or_bad_job_dir_is_untouched(self):
        d = self.job(feature="Complex: no\n")
        stdin = json.dumps({"tool_name": "Agent", "tool_input": {
            "subagent_type": "scrum-builder", "model": "opus", "prompt": f"JOB_DIR={d}"}})
        self.assert_untouched(stdin)
        for prompt in ("no job dir here", "JOB_DIR=/nonexistent/zzz"):
            self.assert_untouched(json.dumps({"tool_name": "Agent", "tool_input": {
                "subagent_type": "scrum-builder", "prompt": prompt}}))

    def test_non_scrum_agent_is_untouched(self):
        self.assert_untouched(self.event("general-purpose", "opus"))

    def test_garbage_stdin_exits_zero_with_no_output(self):
        for stdin in ("not json{", "", "[1, 2]", json.dumps({"tool_name": "Agent", "tool_input": "x"})):
            with self.subTest(stdin=stdin):
                self.assert_untouched(stdin)

    def test_missing_or_unsafe_agent_name_is_untouched(self):
        for kind in ("scrum-not-an-agent", "scrum-../../etc/passwd", "scrum-review-ui/../scrum-review-ui"):
            with self.subTest(kind=kind):
                self.assert_untouched(self.event(kind, "opus"))

    def test_other_tools_are_untouched(self):
        self.assert_untouched(self.event("scrum-review-ui", "opus", tool="Bash"))


if __name__ == "__main__":
    unittest.main()
