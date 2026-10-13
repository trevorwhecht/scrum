import os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallTest(unittest.TestCase):
    def run_install(self, home):
        return subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                              env={**os.environ, "CLAUDE_HOME": str(home), "CODEX_HOME": str(home / "codex")})

    def test_install_links_skill_and_agents_and_is_rerunnable(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            for _ in range(2):
                self.assertEqual(self.run_install(home).returncode, 0)
            self.assertEqual((home / "skills" / "trevskills-scrum").resolve(), ROOT / "skills" / "trevskills-scrum")
            for agent in (ROOT / "agents").glob("*.md"):
                self.assertEqual((home / "agents" / agent.name).resolve(), agent)
            self.assertEqual((home / "codex" / "AGENTS.md").resolve(), ROOT / "codex" / "AGENTS.md")

    def test_install_refuses_to_clobber_a_real_file(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "agents").mkdir(parents=True)
            real = home / "agents" / "scrum-builder.md"
            real.write_text("mine")
            result = self.run_install(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing", result.stderr)
            self.assertEqual(real.read_text(), "mine")

    def test_install_refuses_to_clobber_real_codex_agents_md(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "codex").mkdir()
            real = home / "codex" / "AGENTS.md"
            real.write_text("mine")
            result = self.run_install(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing", result.stderr)
            self.assertEqual(real.read_text(), "mine")
            self.assertFalse((home / "skills").exists(), "a refusal must link nothing")
            self.assertFalse((home / "agents").exists(), "a refusal must link nothing")


if __name__ == "__main__":
    unittest.main()
