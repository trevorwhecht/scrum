import json, os, shlex, subprocess, tempfile, unittest
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
            self.assertEqual((home / "skills" / "trevskills-e2e").resolve(), ROOT / "skills" / "trevskills-e2e")
            for lane in ("cloud.md", "roadmap.md", "lilguy.md", "runall.md", "debug.md", "bigboy.md"):
                linked = home / "skills" / "trevskills-scrum" / "lanes" / lane
                self.assertTrue(linked.is_file(), lane)
                self.assertEqual(linked.resolve(), ROOT / "skills" / "trevskills-scrum" / "lanes" / lane)
            for agent in (ROOT / "agents").glob("*.md"):
                self.assertEqual((home / "agents" / agent.name).resolve(), agent)
            self.assertEqual((home / "codex" / "AGENTS.md").resolve(), ROOT / "codex" / "AGENTS.md")

    def test_cloud_setup_pulls_an_existing_clone_then_installs_idempotently(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            git = lambda *a, cwd=None: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                                      check=True, capture_output=True, text=True).stdout.strip()
            git("clone", "-q", "--bare", str(ROOT), str(t / "origin.git"))
            git("clone", "-q", str(t / "origin.git"), str(t / "src"))
            env = {**os.environ, "HOME": str(t / "home"), "SCRUM_SRC": str(t / "src"),
                   "CLAUDE_HOME": str(t / "home" / ".claude"), "CODEX_HOME": str(t / "home" / ".codex"), "SCRUM_SKIP_BROWSER": "1"}
            setup = lambda: subprocess.run(["bash", str(ROOT / "cloud" / "setup.sh")], env=env, capture_output=True, text=True)
            first = setup()
            self.assertEqual(first.returncode, 0, first.stderr)
            # A new commit upstream: the second run must fast-forward to it, then reinstall with the same links.
            git("clone", "-q", str(t / "origin.git"), str(t / "other"))
            git("commit", "-q", "--allow-empty", "-m", "upstream", cwd=t / "other")
            git("push", "-q", "origin", "HEAD", cwd=t / "other")
            new = git("rev-parse", "HEAD", cwd=t / "other")
            second = setup()
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(git("rev-parse", "HEAD", cwd=t / "src"), new)
            claude = t / "home" / ".claude"
            self.assertEqual((claude / "skills" / "trevskills-scrum").resolve(), (t / "src" / "skills" / "trevskills-scrum").resolve())
            self.assertEqual((claude / "agents" / "scrum-builder.md").resolve(), (t / "src" / "agents" / "scrum-builder.md").resolve())
            self.assertEqual((t / "home" / ".codex" / "AGENTS.md").resolve(), (t / "src" / "codex" / "AGENTS.md").resolve())

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

    def test_install_refuses_to_clobber_real_skill_dir(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            real = home / "skills" / "trevskills-scrum"
            real.mkdir(parents=True)
            (real / "marker").write_text("mine")
            result = self.run_install(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing", result.stderr)
            self.assertFalse(real.is_symlink())
            self.assertEqual((real / "marker").read_text(), "mine")
            self.assertFalse((home / "agents").exists(), "a refusal must create nothing")
            self.assertFalse((home / "codex").exists(), "a refusal must create nothing")

    def test_install_refuses_to_clobber_real_e2e_skill_dir(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            real = home / "skills" / "trevskills-e2e"
            real.mkdir(parents=True)
            (real / "marker").write_text("mine")
            result = self.run_install(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing", result.stderr)
            self.assertFalse(real.is_symlink())
            self.assertEqual((real / "marker").read_text(), "mine")
            self.assertFalse((home / "skills" / "trevskills-scrum").exists(), "a refusal must link nothing")
            self.assertFalse((home / "agents").exists(), "a refusal must create nothing")
            self.assertFalse((home / "codex").exists(), "a refusal must create nothing")

    def test_install_links_jev_rank(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            self.assertEqual(self.run_install(home).returncode, 0)  # $dest/scripts missing: created and linked
            link = home / "scripts" / "jev-rank.py"
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), ROOT / "skills" / "trevskills-scrum" / "jev-rank.py")
            link.unlink()
            link.symlink_to(home / "elsewhere.py")  # an existing symlink is replaced
            self.assertEqual(self.run_install(home).returncode, 0)
            self.assertEqual(link.resolve(), ROOT / "skills" / "trevskills-scrum" / "jev-rank.py")

    def test_install_keeps_real_jev_rank(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "scripts").mkdir()
            real = home / "scripts" / "jev-rank.py"
            real.write_bytes(b"#!/usr/bin/env python3\nprint('mine')\n")
            result = self.run_install(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(real.is_symlink())
            self.assertEqual(real.read_bytes(), b"#!/usr/bin/env python3\nprint('mine')\n")
            notices = [l for l in (result.stdout + result.stderr).splitlines() if "jev-rank.py" in l and "real file" in l]
            self.assertEqual(len(notices), 1, result.stdout + result.stderr)
            self.assertEqual((home / "agents" / "scrum-builder.md").resolve(), ROOT / "agents" / "scrum-builder.md")
            self.assertEqual((home / "skills" / "trevskills-scrum").resolve(), ROOT / "skills" / "trevskills-scrum")

    def test_install_sets_status_line_only_when_absent(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            settings = home / "settings.json"
            want = {"type": "command", "command": f"python3 {home}/skills/trevskills-scrum/board.py statusline",
                    "refreshInterval": 60}
            # no settings.json: created holding only statusLine; a second run changes nothing
            for _ in range(2):
                self.assertEqual(self.run_install(home).returncode, 0)
                self.assertEqual(json.loads(settings.read_text()), {"statusLine": want})
            # other keys and no statusLine: added, every other key kept
            settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"x": 1}]}}))
            for _ in range(2):
                self.assertEqual(self.run_install(home).returncode, 0)
                self.assertEqual(json.loads(settings.read_text()),
                                 {"model": "opus", "hooks": {"Stop": [{"x": 1}]}, "statusLine": want})
            # an existing statusLine, or invalid JSON: byte-for-byte unchanged
            for text in ('{"statusLine": {"type": "command", "command": "mine"},  "a": 1}\n', "{not json"):
                settings.write_text(text)
                result = self.run_install(home)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(settings.read_text(), text)
                if text == "{not json":
                    self.assertIn("settings.json", result.stderr)
            self.assertEqual(sorted(p.name for p in home.iterdir() if p.name.startswith("settings")), ["settings.json"])

    def test_install_quotes_status_line_path_with_spaces(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "my home" / ".claude"
            home.mkdir(parents=True)
            result = self.run_install(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads((home / "settings.json").read_text())["statusLine"]["command"]
            board = f"{t}/my home/.claude/skills/trevskills-scrum/board.py"
            self.assertEqual(command, "python3 '" + board + "' statusline")
            self.assertEqual(shlex.split(command), ["python3", board, "statusline"])
            run = subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True,
                                 env={**os.environ, "SCRUM_USAGE": str(Path(t) / "usage.json")})
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_install_quotes_status_line_path_with_single_quote(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t) / "it's" / ".claude"
            home.mkdir(parents=True)
            result = self.run_install(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads((home / "settings.json").read_text())["statusLine"]["command"]
            self.assertEqual(shlex.split(command)[1], f"{t}/it's/.claude/skills/trevskills-scrum/board.py")


if __name__ == "__main__":
    unittest.main()
