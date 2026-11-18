package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// fixture: a registered repo named trevorhecht-skills on main, like board.py's GitGuardTest.
type fixture struct {
	t    *testing.T
	base string
	repo string
	reg  string
}

func setup(t *testing.T) *fixture {
	t.Helper()
	base := t.TempDir()
	f := &fixture{t: t, base: base, repo: filepath.Join(base, "trevorhecht-skills"), reg: filepath.Join(base, "projects.json")}
	f.git("init", "-q", "-b", "main", f.repo)
	f.git("-C", f.repo, "commit", "-q", "--allow-empty", "-m", "first")
	if err := os.Mkdir(filepath.Join(f.repo, "scrum"), 0o755); err != nil {
		t.Fatal(err)
	}
	f.register(f.repo)
	t.Setenv("SCRUM_REGISTRY", f.reg)
	t.Setenv("CLAUDE_NOTIFIER_DISABLE", "") // a scrum-launched test run has it set; a chat does not
	return f
}

func (f *fixture) git(args ...string) {
	f.t.Helper()
	out, err := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@t"}, args...)...).CombinedOutput()
	if err != nil {
		f.t.Fatalf("git %v: %v %s", args, err, out)
	}
}

func (f *fixture) register(paths ...string) {
	data, _ := json.Marshal(paths)
	f.write(f.reg, string(data))
}

func (f *fixture) write(path, text string) {
	f.t.Helper()
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		f.t.Fatal(err)
	}
}

func (f *fixture) event(command, cwd, tool string) event {
	if cwd == "" {
		cwd = f.repo
	}
	if tool == "" {
		tool = "Bash"
	}
	return event{"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": map[string]any{"command": command}, "cwd": cwd}
}

func (f *fixture) commit() event { return f.event("git commit -m x", "", "") }

func assertDenied(t *testing.T, reason, branch, label string) {
	t.Helper()
	if reason == "" {
		t.Fatalf("%s: allowed, want denied", label)
	}
	for _, phrase := range []string{"trevorhecht-skills", "on " + branch, "unpushed on main blocks every scrum merge",
		"/trevskills-scrum lilguy <what to save>", "Lane: lilguy — knowledge save",
		"Trevor can still commit by hand from his own terminal"} {
		if !strings.Contains(reason, phrase) {
			t.Errorf("%s: reason lacks %q: %s", label, phrase, reason)
		}
	}
}

func assertAllowed(t *testing.T, reason, label string) {
	t.Helper()
	if reason != "" {
		t.Errorf("%s: denied, want allowed: %s", label, reason)
	}
}

func TestReasonTextMatchesBoardPy(t *testing.T) {
	f := setup(t)
	want := "Refused: git commit on main in the trevorhecht-skills main checkout from a chat. A commit left unpushed " +
		"on main blocks every scrum merge in that repo. Save the change through a scrum job instead: " +
		"/trevskills-scrum lilguy <what to save> (Lane: lilguy — knowledge save). " +
		"Trevor can still commit by hand from his own terminal."
	if got := guardReason(f.commit()); got != want {
		t.Fatalf("reason\n got %q\nwant %q", got, want)
	}
}

func TestDeniesCommitOnMainInRegisteredCheckout(t *testing.T) {
	f := setup(t)
	other := f.base
	cases := []struct{ label, command, cwd string }{
		{"plain", "git commit -m x", ""},
		{"-C abs", "git -C " + f.repo + " commit -m x", other},
		{"-C relative", "git -C trevorhecht-skills commit -m x", other},
		{"cd then commit", "cd " + f.repo + " && git add -A && git commit -m x", other},
		{"-c option", "git -c user.name=x commit", ""},
		{"last cd wins", "cd a;cd " + f.repo + " && git commit -m x", other},
	}
	for _, c := range cases {
		assertDenied(t, guardReason(f.event(c.command, c.cwd, "")), "main", c.label)
	}
	f.git("-C", f.repo, "branch", "-m", "master")
	assertDenied(t, guardReason(f.commit()), "master", "master")
}

func TestAllowsOtherBranchesWorktreesUnregisteredAndNonCommits(t *testing.T) {
	for _, v := range []string{"", "1"} { // a chat, then a scrum-launched session
		t.Run("CLAUDE_NOTIFIER_DISABLE="+v, func(t *testing.T) { allowsOtherBranches(t, v) })
	}
}

func allowsOtherBranches(t *testing.T, notifier string) {
	f := setup(t)
	t.Setenv("CLAUDE_NOTIFIER_DISABLE", notifier)
	for _, command := range []string{"git status", "git commit-tree HEAD^{tree} -m x", "git log --grep commit"} {
		assertAllowed(t, guardReason(f.event(command, "", "")), command)
	}
	assertAllowed(t, guardReason(f.event("git commit -m x", "", "Edit")), "non-Bash tool")
	wt := filepath.Join(f.base, "wt")
	f.git("-C", f.repo, "worktree", "add", "-q", "-b", "scrum/607-x", wt)
	assertAllowed(t, guardReason(f.event("git commit -m x", wt, "")), "linked worktree")
	f.git("-C", wt, "checkout", "-q", "--detach")
	f.git("-C", f.repo, "checkout", "-q", "scrum/607-x")
	assertAllowed(t, guardReason(f.commit()), "other branch")
	f.git("-C", f.repo, "checkout", "-q", "--detach")
	assertAllowed(t, guardReason(f.commit()), "detached HEAD")
	f.git("-C", f.repo, "checkout", "-q", "main")
	assertDenied(t, guardReason(f.commit()), "main", "back on main")
	f.register(filepath.Join(f.base, "elsewhere"))
	assertAllowed(t, guardReason(f.commit()), "unregistered repo")
}

func TestScrumSessionsAreNotExempt(t *testing.T) {
	f := setup(t)
	for _, v := range []string{"1", "yes", "True", "0", ""} {
		t.Setenv("CLAUDE_NOTIFIER_DISABLE", v)
		assertDenied(t, guardReason(f.commit()), "main", "CLAUDE_NOTIFIER_DISABLE="+v)
	}
	jobs := filepath.Join(f.repo, "scrum", "board.json")
	f.write(jobs, `{"jobs": [{"id": "1", "stage": "merging", "pid": 111, "tty": "ttys004"}]}`)
	assertDenied(t, guardReason(f.commit()), "main", "the orchestrator's own pid")
	f.write(jobs, `{"jobs": [{"id": "1", "stage": "merging", "tty": "ttys004"}]}`)
	assertDenied(t, guardReason(f.commit()), "main", "a pid-less job's tty")
}

func cli(stdin string) string {
	var out bytes.Buffer
	run(strings.NewReader(stdin), &out)
	return out.String()
}

func TestCLIPrintsDenyJSONAndNeverErrors(t *testing.T) {
	f := setup(t)
	ev, _ := json.Marshal(f.commit())
	out := cli(string(ev))
	if strings.Count(out, "\n") != 1 {
		t.Fatalf("want one JSON line, got %q", out)
	}
	var got map[string]map[string]string
	if err := json.Unmarshal([]byte(out), &got); err != nil {
		t.Fatalf("%v: %q", err, out)
	}
	spec, ok := got["hookSpecificOutput"]
	if len(got) != 1 || !ok || len(spec) != 3 || spec["hookEventName"] != "PreToolUse" || spec["permissionDecision"] != "deny" {
		t.Fatalf("bad deny JSON: %q", out)
	}
	assertDenied(t, spec["permissionDecisionReason"], "main", "cli")

	gone := f.commit()
	gone["cwd"] = filepath.Join(f.base, "gone")
	noCwd := f.commit()
	delete(noCwd, "cwd")
	var stdins []string
	for _, e := range []event{gone, noCwd} {
		b, _ := json.Marshal(e)
		stdins = append(stdins, string(b))
	}
	stdins = append(stdins, "not json", "", "null", "[]", `{"tool_name": "Bash", "tool_input": "git commit"}`)
	for _, s := range stdins {
		if got := cli(s); got != "" {
			t.Errorf("stdin %q: got %q, want no output", s, got)
		}
	}
	for _, reg := range []string{"not json", `{"a": 1}`} {
		f.write(f.reg, reg)
		if got := cli(string(ev)); got != "" {
			t.Errorf("registry %q: got %q", reg, got)
		}
	}
	os.Chmod(f.reg, 0)
	if got := cli(string(ev)); got != "" {
		t.Errorf("unreadable registry: got %q", got)
	}
}

func TestPanicIsRecovered(t *testing.T) {
	f := setup(t)
	ev, _ := json.Marshal(f.commit())
	old := readFile
	readFile = func(string) ([]byte, error) { panic("boom") }
	defer func() { readFile = old }()
	if got := cli(string(ev)); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestFastPathSkipsProcessAndFiles(t *testing.T) {
	f := setup(t)
	calls := 0
	oldRun, oldRead := runCmd, readFile
	runCmd = func(name string, args ...string) (string, error) { calls++; return oldRun(name, args...) }
	readFile = func(p string) ([]byte, error) { calls++; return oldRead(p) }
	defer func() { runCmd, readFile = oldRun, oldRead }()
	t.Setenv("SCRUM_REGISTRY", filepath.Join(f.base, "missing", "projects.json"))
	t.Setenv("PATH", t.TempDir())
	ev, _ := json.Marshal(f.event("git status", "", ""))
	if got := cli(string(ev)); got != "" {
		t.Fatalf("got %q", got)
	}
	assertAllowed(t, guardReason(f.event("git status", "", "")), "guardReason git status")
	if calls != 0 {
		t.Fatalf("fast path made %d process/file calls, want 0", calls)
	}
	// The counter works: a commit does reach git (and fails on the empty PATH, so no output).
	ev, _ = json.Marshal(f.commit())
	if got := cli(string(ev)); got != "" || calls == 0 {
		t.Fatalf("commit path: out %q, calls %d", got, calls)
	}
}
