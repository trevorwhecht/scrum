// gitguard: the user-level PreToolUse hook that refuses a chat's Bash `git commit` on main/master in a registered
// repo's main checkout. A port of board.py's git_guard_reason (job 607) to skip Python's start-up on every Bash call.
// It never blocks Claude Code on an error: no output and exit 0.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// active equals board.py ACTIVE: the stages an interactive session can pause in (tests/test_gitguard.py pins it).
var active = []string{"spec", "build", "check", "review", "approve", "merging", "deploying"}

// `git`, its -C/-c options, then the commit subcommand (not commit-tree, not `--grep commit`). Group 1: the options.
// Go has no lookaround: the trailing class consumes one char where board.py's lookahead did not; only the match start
// and group 1 are read, so the result is the same.
var (
	gitCommitRE = regexp.MustCompile(`\bgit((?:\s+-[cC]\s+\S+)*)\s+commit(?:\s|$|[;&|)])`)
	cdRE        = regexp.MustCompile(`(?:^|[^\w.-])cd\s+([^\s;&|]+)`)
	dashCRE     = regexp.MustCompile(`-C\s+(\S+)`)
	ttyRE       = regexp.MustCompile(`^ttys[0-9]+$`)
)

// runCmd and readFile are the only ways out to processes and files; tests swap them to count calls.
var (
	runCmd   = execOut
	readFile = os.ReadFile
)

// errAbort: a process could not run (missing, timed out), which board.py let escape as an exception: allow.
var errAbort = errors.New("abort")

type event map[string]any

func main() {
	run(os.Stdin, os.Stdout)
	os.Exit(0)
}

// run reads one PreToolUse event and prints the deny JSON when the commit must be refused. Never panics.
func run(stdin io.Reader, stdout io.Writer) {
	defer func() { recover() }()
	data, err := io.ReadAll(stdin)
	var ev event
	if err != nil || json.Unmarshal(data, &ev) != nil || ev == nil {
		return
	}
	if !gitCommitRE.MatchString(command(ev)) {
		return // fast path: no ps, no git, no file read
	}
	tty, err := callerTTY()
	if err != nil {
		return
	}
	reason := guardReason(ev, tty, callerClaudePID())
	if reason == "" {
		return
	}
	enc := json.NewEncoder(stdout)
	enc.SetEscapeHTML(false)
	enc.Encode(map[string]any{"hookSpecificOutput": map[string]any{
		"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})
}

func command(ev event) string {
	if ev["tool_name"] != "Bash" {
		return ""
	}
	in, _ := ev["tool_input"].(map[string]any)
	s, _ := in["command"].(string)
	return s
}

// guardReason: the deny reason when a Bash `git commit` would land on main/master in a registered repo's main
// checkout from a chat, else "". Pipeline sessions are exempt: CLAUDE_NOTIFIER_DISABLE set (scrum-launched), or an
// ACTIVE job matched to this session (pid when the job records one, else tty). pid 0 = no claude ancestor.
func guardReason(ev event, tty string, pid int) string {
	cmd := command(ev)
	m := gitCommitRE.FindStringSubmatchIndex(cmd)
	cwd, _ := ev["cwd"].(string)
	if m == nil || cwd == "" || notifierDisabled() {
		return ""
	}
	// The commit's directory: the last -C on it, else the last `cd` before it, else cwd; relative to cwd.
	var dirs [][]string
	if m[2] >= 0 {
		dirs = dashCRE.FindAllStringSubmatch(cmd[m[2]:m[3]], -1)
	}
	if len(dirs) == 0 {
		dirs = cdRE.FindAllStringSubmatch(cmd[:m[0]], -1)
	}
	where := cwd
	if len(dirs) > 0 {
		d := expandUser(strings.Trim(dirs[len(dirs)-1][1], `'"`))
		if filepath.IsAbs(d) {
			where = d
		} else {
			where = filepath.Join(cwd, d)
		}
	}
	top, err := git(where, "rev-parse", "--show-toplevel")
	if err != nil {
		return ""
	}
	branch, err := git(where, "symbolic-ref", "--short", "-q", "HEAD")
	if err != nil {
		return ""
	}
	registry := readRegistry()
	if (branch != "main" && branch != "master") || top == "" || !registered(top, registry) {
		return ""
	}
	for _, repo := range registry {
		if sessionOwnsActiveJob(filepath.Join(repo, "scrum", "board.json"), tty, pid) {
			return ""
		}
	}
	return "Refused: git commit on " + branch + " in the " + filepath.Base(top) + " main checkout from a chat. " +
		"A commit left unpushed on main blocks every scrum merge in that repo. Save the change through a scrum job " +
		"instead: /trevskills-scrum lilguy <what to save> (Lane: lilguy — knowledge save). " +
		"Trevor can still commit by hand from his own terminal."
}

// sessionOwnsActiveJob mirrors board.py's any(): jobs are walked in order and a malformed one ends this board's walk.
func sessionOwnsActiveJob(path, tty string, pid int) bool {
	data, err := readFile(path)
	if err != nil {
		return false
	}
	var board map[string]any
	if json.Unmarshal(data, &board) != nil {
		return false
	}
	jobs, ok := board["jobs"].([]any)
	if !ok {
		return false
	}
	for _, j := range jobs {
		job, ok := j.(map[string]any)
		if !ok {
			return false
		}
		stage, _ := job["stage"].(string)
		if !contains(active, stage) {
			continue
		}
		if truthy(job["pid"]) {
			if n, ok := job["pid"].(float64); ok && pid != 0 && n == float64(pid) {
				return true
			}
		} else if ttyRE.MatchString(tty) && job["tty"] == tty {
			return true
		}
	}
	return false
}

func registered(top string, registry []string) bool {
	want := resolve(top)
	for _, r := range registry {
		if resolve(r) == want {
			return true
		}
	}
	return false
}

// resolve stands in for Path.resolve(): symlinks followed when the path exists, else just made absolute.
func resolve(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	if a, err := filepath.Abs(p); err == nil {
		return a
	}
	return p
}

// expandUser covers `~` and `~/...`; `~user` is left as is.
func expandUser(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if home, err := os.UserHomeDir(); err == nil {
			return home + p[1:]
		}
	}
	return p
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// truthy is Python's bool() for a decoded JSON value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case float64:
		return x != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func git(dir string, args ...string) (string, error) {
	out, err := runCmd("git", append([]string{"-C", dir}, args...)...)
	return strings.TrimSpace(out), err
}

// execOut runs a command with board.py's 2 s timeout. A non-zero exit still returns its stdout (subprocess.run
// without check); a command that cannot start or times out returns errAbort.
func execOut(name string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	var exit *exec.ExitError
	if err != nil && (!errors.As(err, &exit) || ctx.Err() != nil) {
		return "", errAbort
	}
	return string(out), nil
}

// callerTTY: the calling terminal's tty, the first ancestor (at most 10 up) with a ttysN, since Claude Code may start
// hooks under a detached parent whose tty is ??. "??" when none has one. An error when ps cannot run.
func callerTTY() (string, error) {
	pid := os.Getppid()
	for i := 0; i < 10; i++ {
		out, err := runCmd("ps", "-o", "ppid=,tty=", "-p", strconv.Itoa(pid))
		if err != nil {
			return "", err
		}
		f := strings.Fields(out)
		if len(f) != 2 {
			break
		}
		if ttyRE.MatchString(f[1]) {
			return f[1], nil
		}
		n, err := strconv.Atoi(f[0])
		if err != nil || n <= 1 {
			break
		}
		pid = n
	}
	return "??", nil
}

// callerClaudePID: the pid of the nearest claude ancestor (at most 10 up); 0 when none or ps fails.
func callerClaudePID() int {
	pid := os.Getppid()
	for i := 0; i < 10; i++ {
		out, err := runCmd("ps", "-o", "ppid=,command=", "-p", strconv.Itoa(pid))
		if err != nil {
			return 0
		}
		s := strings.TrimSpace(out) // Python's .strip().split(None, 1)
		i := strings.IndexFunc(s, unicode.IsSpace)
		if i < 0 {
			return 0
		}
		f := []string{s[:i], strings.TrimLeftFunc(s[i:], unicode.IsSpace)}
		if isClaude(f[1]) {
			return pid
		}
		n, err := strconv.Atoi(f[0])
		if err != nil || n <= 1 {
			return 0
		}
		pid = n
	}
	return 0
}

// isClaude: claude is the program, argv0 named `claude`, a bare `claude` token, or the claude-code package. A path
// that merely passes through `.claude/` (a worktree's dev server) does not count.
func isClaude(command string) bool {
	toks := strings.Fields(command)
	if len(toks) == 0 {
		return false
	}
	argv0 := toks[0][strings.LastIndex(toks[0], "/")+1:]
	return argv0 == "claude" || contains(toks, "claude") || strings.Contains(command, "claude-code")
}

func registryPath() string {
	if p := os.Getenv("SCRUM_REGISTRY"); p != "" {
		return p
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude", "trevskills-scrum", "projects.json")
}

// readRegistry: the registered repo paths; empty when projects.json is unreadable or not a list.
func readRegistry() []string {
	data, err := readFile(registryPath())
	if err != nil {
		return nil
	}
	var list []any
	if json.Unmarshal(data, &list) != nil {
		return nil
	}
	var paths []string
	for _, p := range list {
		if s, ok := p.(string); ok {
			paths = append(paths, s)
		}
	}
	return paths
}

// notifierDisabled: the same test as isDisabled in ~/.claude/hooks/_lib/config.js (the Claude Notifier).
func notifierDisabled() bool {
	v := os.Getenv("CLAUDE_NOTIFIER_DISABLE")
	return v != "" && v != "0" && strings.ToLower(v) != "false"
}
