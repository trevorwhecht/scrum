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
	"strings"
	"time"
)

// `git`, its -C/-c options, then the commit subcommand (not commit-tree, not `--grep commit`). Group 1: the options.
// Go has no lookaround: the trailing class consumes one char where board.py's lookahead did not; only the match start
// and group 1 are read, so the result is the same.
var (
	gitCommitRE = regexp.MustCompile(`\bgit((?:\s+-[cC]\s+\S+)*)\s+commit(?:\s|$|[;&|)])`)
	cdRE        = regexp.MustCompile(`(?:^|[^\w.-])cd\s+([^\s;&|]+)`)
	dashCRE     = regexp.MustCompile(`-C\s+(\S+)`)
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
		return // fast path: no git, no file read
	}
	reason := guardReason(ev)
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
// checkout, else "". Scrum-launched sessions are not exempt (job 957): no scrum path commits on main through a Bash
// call.
func guardReason(ev event) string {
	cmd := command(ev)
	m := gitCommitRE.FindStringSubmatchIndex(cmd)
	cwd, _ := ev["cwd"].(string)
	if m == nil || cwd == "" {
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
	return "Refused: git commit on " + branch + " in the " + filepath.Base(top) + " main checkout from a chat. " +
		"A commit left unpushed on main blocks every scrum merge in that repo. Save the change through a scrum job " +
		"instead: /trevskills-scrum lilguy <what to save> (Lane: lilguy — knowledge save). " +
		"Trevor can still commit by hand from his own terminal."
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
