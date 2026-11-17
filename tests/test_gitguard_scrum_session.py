"""Job 957 repro: the git-guard hook must refuse a scrum-launched session's `git commit` on main in a registered
repo's main checkout (CLAUDE_NOTIFIER_DISABLE set, or the session owning an ACTIVE board job).

Runs TestScrumSessionCommitOnMainRefused against the live gitguard/main.go, copied into a temp module, so this file
never touches the Go package the fix edits."""
import shutil, subprocess, tempfile, unittest
from pathlib import Path

GITGUARD = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "gitguard"

REPRO_GO = r'''package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestScrumSessionCommitOnMainRefused(t *testing.T) {
	base := t.TempDir()
	repo := filepath.Join(base, "trevorhecht-skills")
	for _, args := range [][]string{{"init", "-q", "-b", "main", repo},
		{"-C", repo, "commit", "-q", "--allow-empty", "-m", "first"}} {
		out, err := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	os.Mkdir(filepath.Join(repo, "scrum"), 0o755)
	reg := filepath.Join(base, "projects.json")
	os.WriteFile(reg, []byte(`["`+repo+`"]`), 0o644)
	t.Setenv("SCRUM_REGISTRY", reg)
	ev := event{"hook_event_name": "PreToolUse", "tool_name": "Bash",
		"tool_input": map[string]any{"command": "git commit -m x"}, "cwd": repo}
	board := filepath.Join(repo, "scrum", "board.json")

	t.Setenv("CLAUDE_NOTIFIER_DISABLE", "1")
	if guardReason(ev, "??", 0) == "" {
		t.Errorf("CLAUDE_NOTIFIER_DISABLE=1 (scrum-launched session): commit on main allowed, want denied")
	}
	t.Setenv("CLAUDE_NOTIFIER_DISABLE", "")
	os.WriteFile(board, []byte(`{"jobs": [{"id": "950", "stage": "spec", "pid": 111}]}`), 0o644)
	if guardReason(ev, "??", 111) == "" {
		t.Errorf("session pid owns an ACTIVE job: commit on main allowed, want denied")
	}
	os.WriteFile(board, []byte(`{"jobs": [{"id": "950", "stage": "build", "tty": "ttys004"}]}`), 0o644)
	if guardReason(ev, "ttys004", 222) == "" {
		t.Errorf("session tty owns a pid-less ACTIVE job: commit on main allowed, want denied")
	}

	// Still allowed for a scrum session: a job worktree on scrum/<id>.
	t.Setenv("CLAUDE_NOTIFIER_DISABLE", "1")
	wt := filepath.Join(base, "wt")
	if out, err := exec.Command("git", "-C", repo, "worktree", "add", "-q", "-b", "scrum/957-x", wt).CombinedOutput(); err != nil {
		t.Fatalf("worktree: %v %s", err, out)
	}
	wtev := event{"hook_event_name": "PreToolUse", "tool_name": "Bash",
		"tool_input": map[string]any{"command": "git commit -m x"}, "cwd": wt}
	if r := guardReason(wtev, "??", 0); r != "" {
		t.Errorf("scrum session commit in a job worktree: denied, want allowed: %s", r)
	}
}
'''


class GitGuardScrumSessionTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("go"), "go is not installed")
    def test_scrum_session_commit_on_main_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("go.mod", "main.go"):
                shutil.copy(GITGUARD / name, Path(tmp) / name)
            (Path(tmp) / "repro_test.go").write_text(REPRO_GO)
            result = subprocess.run(["go", "test", "-count=1", "-run", "^TestScrumSessionCommitOnMainRefused$", "."],
                                    cwd=tmp, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
