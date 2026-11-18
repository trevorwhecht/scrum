"""The edit-check PostToolUse hook (skills/trevskills-scrum/edit-check.py): checks a scrum-repo file at the edit."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "skills" / "trevskills-scrum" / "edit-check.py"
BAD_PY = "def f(:\n    pass\n"
FAILING_CONTRACTS = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('pinned phrase gone')\n"


class EditCheckHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def repo(self, name, marker=True, git=".git dir"):
        root = self.tmp / name
        root.mkdir()
        if git == ".git dir":
            (root / ".git").mkdir()
        else:  # a linked worktree has a .git file
            (root / ".git").write_text("gitdir: /elsewhere\n")
        if marker:
            (root / "skills" / "trevskills-scrum").mkdir(parents=True)
            (root / "skills" / "trevskills-scrum" / "board.py").write_text("")
        return root

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_hook(self, path=None, stdin=None, path_env=None):
        stdin = stdin if stdin is not None else json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})
        env = {**os.environ, "PATH": path_env if path_env is not None else os.environ.get("PATH", "")}
        return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=60)

    def assertSilentPass(self, result):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_bad_py_in_marker_repo_exits_2_and_outside_exits_0(self):
        bad = self.write(self.repo("scrum") / "skills" / "trevskills-scrum" / "serve.py", BAD_PY)
        result = self.run_hook(bad)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SyntaxError", result.stderr)
        self.assertLessEqual(len(result.stderr.splitlines()), 20)
        self.assertEqual(result.stdout, "")
        # a job worktree (.git file) with the marker is checked too
        self.assertEqual(self.run_hook(self.write(self.repo("wt", git=".git file") / "x.py", BAD_PY)).returncode, 2)
        # the same file in a repo without the marker, or in no repo at all: exit 0, silent
        self.assertSilentPass(self.run_hook(self.write(self.repo("other", marker=False) / "serve.py", BAD_PY)))
        self.assertSilentPass(self.run_hook(self.write(self.tmp / "loose" / "serve.py", BAD_PY)))

    def test_clean_py_in_marker_repo_exits_0_silently(self):
        self.assertSilentPass(self.run_hook(self.write(self.repo("scrum") / "board2.py", "import os\nprint(os.sep)\n")))

    @unittest.skipUnless(shutil.which("ruff"), "ruff is not installed")
    def test_undefined_name_fails_with_ruff_and_passes_without_it(self):
        typo = self.write(self.repo("scrum") / "x.py", "def f():\n    return undefined_thing\n")
        result = self.run_hook(typo)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("F821", result.stderr)
        self.assertSilentPass(self.run_hook(typo, path_env=str(self.tmp / "no-ruff-here")))

    def test_contract_md_runs_test_contracts(self):
        root = self.repo("scrum")
        self.write(root / "tests" / "test_contracts.py", FAILING_CONTRACTS)
        for rel in ("agents/scrum-builder.md", "skills/trevskills-scrum/SKILL.md", "skills/trevskills-scrum/lanes/merge.md"):
            result = self.run_hook(self.write(root / rel, "x"))
            self.assertEqual(result.returncode, 2, rel)
            self.assertIn("pinned phrase gone", result.stderr)
            self.assertLessEqual(len(result.stderr.splitlines()), 20)
        for rel in ("README.md", "docs/agents/x.md", "skills/trevskills-scrum/lanes/sub/x.md", "skills/trevskills-e2e/SKILL.md"):
            self.assertSilentPass(self.run_hook(self.write(root / rel, "x")))
        self.write(root / "tests" / "test_contracts.py", FAILING_CONTRACTS.replace("self.fail('pinned phrase gone')", "pass"))
        self.assertSilentPass(self.run_hook(root / "agents" / "scrum-builder.md"))

    def test_unreadable_input_exits_0(self):
        for stdin in ("", "{not json", "[1]", '{"tool_input": {}}', '{"tool_input": {"file_path": 3}}'):
            self.assertSilentPass(self.run_hook(stdin=stdin))
        self.assertSilentPass(self.run_hook(self.repo("scrum") / "gone.py"))  # a deleted file


if __name__ == "__main__":
    unittest.main()
