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
