#!/usr/bin/env python3
"""The scrum's one way to talk to its worker Macs: every remote command goes through `ssh <alias>`, one alias per
workers() line of workers.txt beside projects.json (no file: the one shop MacBook Pro, `shopmac`).

usage: shop.py probe [alias]   (print the cached probe as one JSON line; exit 0 whether the worker is up or down)
       shop.py setup [alias]   (prepare the worker for a scrum job: one `<step>: <result>` line per step; exit 1 when
                                it is down or a step failed)
       shop.py md-sync [alias] (pull the worker's skill clones and copy this Mac's CLAUDE.md, memory notes and plain
                                skill folders there: one line, `md-sync: ok` (exit 0), `md-sync: failed` or
                                `shop: down` (exit 1))
       alias defaults to the first workers() alias, else shopmac.

Every function that makes an ssh call takes alias= (default ALIAS, shopmac); probe and ready() caches are per alias.
run() never raises: a timeout comes back as exit 124, ssh that cannot start (or an alias off PROJECT_RE) as 127, and
ssh's own failure as 255.
probe() is one cached round trip that prints nothing when the shop Mac sleeps. setup(), ready(), env_copy(),
profile_copy() and md_sync() never print a secret or remote output. Dispatch (serve.py's shop_tick and cloud_tick) uses
clone() to clone or fast-forward a project in ~/scrum-work, profile_copy() to give that clone this Mac's project.md and
Render auth file, start() to launch a headless cloud-job session there (the prompt only on stdin) and ended() to read a
finished session's log tail. See lanes/shop.md.
"""
import argparse, io, json, os, posixpath, re, shlex, subprocess, sys, tarfile, time
from collections import namedtuple
from pathlib import Path

ALIAS = "shopmac"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=5")  # after the alias: they win over ~/.ssh/config
PATH_PREFIX = 'export PATH="$HOME/.local/bin:$PATH"; '  # node, gh and claude live there; a non-interactive shell lacks it
PROBE_CMD = "sysctl -n vm.loadavg hw.ncpu; command -v node gh claude; true"  # `true`: a missing tool is not a down Mac
PROBE_TIMEOUT = 10
UP_TTL = 60
DOWN_TTL = 300  # 5 of serve.py's one-minute watchdog ticks per probe of a sleeping shop Mac
TOOLS = ("node", "gh", "claude")

NODE_VERSION = "24.22.3"  # built for macOS 13.5, runs on the shop's macOS 12.7 (checked 2026-11-17)
NODE_SHA256 = "977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7"
GH_VERSION = "2.103.3"
GH_SHA256 = "a2f86418f4350ae6e9ec60d5000bdf7665728436946a97fc27fe50e6ae752682"
INSTALL_TIMEOUT, STEP_TIMEOUT, ACCOUNT_TIMEOUT = 600, 60, 120
IN_TMP = 'd=$(mktemp -d) || exit 1; (cd "$d" && {}); rc=$?; rm -rf "$d"; exit $rc'  # an install's work dir, always removed
NODE_DIR = f"node-v{NODE_VERSION}-darwin-x64"
NODE_INSTALL = IN_TMP.format(
    f"curl -fsSL -o node.tgz https://nodejs.org/dist/v{NODE_VERSION}/{NODE_DIR}.tar.gz"
    f" && echo '{NODE_SHA256}  node.tgz' | shasum -a 256 -c -"
    ' && mkdir -p "$HOME/.local/share" "$HOME/.local/bin" && tar -xzf node.tgz -C "$HOME/.local/share"'
    + "".join(f' && ln -sf "$HOME/.local/share/{NODE_DIR}/bin/{b}" "$HOME/.local/bin/{b}"' for b in ("node", "npm", "npx")))
GH_DIR = f"gh_{GH_VERSION}_macOS_amd64"
GH_INSTALL = IN_TMP.format(
    f"curl -fsSL -o gh.zip https://github.com/cli/cli/releases/download/v{GH_VERSION}/{GH_DIR}.zip"  # -L: it redirects
    f" && echo '{GH_SHA256}  gh.zip' | shasum -a 256 -c -"
    f' && unzip -q gh.zip && mkdir -p "$HOME/.local/bin" && cp {GH_DIR}/bin/gh "$HOME/.local/bin/gh"')
# File storage, never the keychain: the shop's login keychain is locked in SSH sessions (security exits 36).
GH_LOGIN = ("gh auth login --hostname github.com --git-protocol https --with-token --insecure-storage"
            " && chmod 600 ~/.config/gh/hosts.yml")
GIT_HELPER = "git config --global --get-all credential.https://github.com.helper"

# Entries of this Mac's ~/.claude-owa that are links into ~/.claude (read 2026-11-17); its credentials are not.
OWA_LINKS = ("agents", "CLAUDE.md", "commands", "history.jsonl", "hooks", "plugins", "projects", "rules", "scripts",
             "settings.json", "settings.local.json", "skills")
OWA_CHECK = ('mkdir -p "$HOME/.claude-owa" || exit 1; for n in ' + " ".join(OWA_LINKS) + '; do [ -e "$HOME/.claude/$n" ]'
             ' && [ ! -e "$HOME/.claude-owa/$n" ] && [ ! -L "$HOME/.claude-owa/$n" ] && echo "$n"; done; true')
SHOP_ACCOUNTS = {"main": None, "owa": "$HOME/.claude-owa"}  # account: its CLAUDE_CONFIG_DIR (None: claude's default)
ACCOUNT_CHECK = "claude -p 'Reply with the single word ok' --model haiku --max-turns 1"
NO_TOKEN = 3  # the account check's exit code when the account's oauth-token file is missing
TOKEN_HINT = " (run claude setup-token in the shop GUI)"
# This Mac's ~/.claude/settings.json permissions a headless scrum job needs (read 2026-11-17), home paths as {home};
# local-only entries (MCP tools, Chrome, .env.prod, Homebrew, PR merge, safe-reset) are left out. The Edit denies keep
# shop sessions off the docs md_sync() owns.
SHOP_PERMISSIONS = {
    "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebSearch", "WebFetch", "Skill", "Read(/{home}/**)",
              "Read(//tmp/**)", "Read(//private/tmp/**)", "Edit(/{home}/.claude/**/*.md)",
              "Edit(/{home}/.claude-owa/**/*.md)"],
    "deny": ["Bash(git reset:*)", "Bash(git rebase:*)", "Bash(git push --force:*)", "Bash(git push --force-with-lease:*)",
             "Bash(git push -f:*)", "Bash(prisma migrate reset:*)", "Bash(npx prisma migrate reset:*)",
             "Edit(/{home}/.claude/CLAUDE.md)", "Edit(/{home}/.claude/rules/**)",
             "Edit(/{home}/.claude/projects/*/memory/**)", "Edit(/{home}/.claude-owa/CLAUDE.md)",
             "Edit(/{home}/.claude-owa/rules/**)", "Edit(/{home}/.claude-owa/projects/*/memory/**)"],
    "ask": ["Bash(prisma db push:*)", "Bash(npx prisma db push:*)"],
    "additionalDirectories": ["/private/tmp", "{home}/scrum-work", "{home}/.claude", "{home}/.claude-owa"],
}
# Runs on the shop's python3 after a PERMS = ... line: union, never remove; write only on a change, atomically.
MERGE_SCRIPT = r'''
home = os.path.expanduser("~")
path = os.path.realpath(os.path.join(home, ".claude", "settings.json"))
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except FileNotFoundError:
    data = {}
except ValueError:
    sys.exit("settings.json is not valid JSON")
perms = data.setdefault("permissions", {}) if isinstance(data, dict) else None
if not isinstance(perms, dict):
    sys.exit("settings.json: permissions is not an object")
changed = False
for key, entries in PERMS.items():
    have = perms.setdefault(key, [])
    if not isinstance(have, list):
        sys.exit("settings.json: permissions.%s is not a list" % key)
    for entry in entries:
        entry = entry.replace("{home}", home)
        if entry not in have:
            have.append(entry)
            changed = True
if changed:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
print("changed" if changed else "same")
'''
# ponytail: a gh logout or a revoked token stays unseen for up to 10 min of an up shop; setup() clears it, and a
# dispatch that fails on it is the upgrade trigger for a shorter TTL.
READY_TTL = 600
PROJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # also every ssh alias: never `-`-led, never user@host
MAX_RE = re.compile(r"[1-9][0-9]*")  # a workers.txt max jobs; fullmatch
Worker = namedtuple("Worker", "alias max accounts")  # a workers.txt line; accounts: SHOP_ACCOUNTS names, dispatch order
ENV_COPY = ("umask 077 && mkdir -p ~/scrum-work/{p} && cat > ~/scrum-work/{p}/.env.local.tmp"
            " && mv -f ~/scrum-work/{p}/.env.local.tmp ~/scrum-work/{p}/.env.local")
# profile_copy() writes HOME_TOKEN for this Mac's home; the shop's sed puts its own $HOME there.
HOME_TOKEN = "@@SCRUM_SHOP_HOME@@"
# Only into an existing clone: a fake .git would break the next clone(). Then setup step 2's exclude lines, each once.
PROFILE_COPY = ('d="$HOME/scrum-work/{p}"; [ -d "$d/.git" ] || exit 3; mkdir -p "$d/scrum" "$d/.git/info"'
                ' && LC_ALL=C sed "s|{t}|$HOME|g" > "$d/scrum/project.md.tmp"'
                ' && mv -f "$d/scrum/project.md.tmp" "$d/scrum/project.md" || exit 1; x="$d/.git/info/exclude";'
                ' if [ -n "$(tail -c 1 "$x" 2>/dev/null)" ]; then echo >> "$x" || exit 1; fi;'
                ' for l in scrum/ .claude/worktrees/; do grep -qxF "$l" "$x" 2>/dev/null || echo "$l" >> "$x" || exit 1; done')
AUTH_COPY = ("umask 077 && mkdir -p ~/scrum-work/{p}/{d} && cat > ~/scrum-work/{p}/{f}.tmp"
             " && mv -f ~/scrum-work/{p}/{f}.tmp ~/scrum-work/{p}/{f}")  # {d}, {f}: shlex-quoted repo-relative paths
RENDER_AUTH_RE = re.compile(r"^\s*-\s*Render auth:(.*)$", re.M)
REPO_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*")  # fullmatch; .git or not
JOB_RE = re.compile(r"[0-9]{3,}-[a-z0-9-]+")  # board.ID_RE's shape; fullmatch, so a trailing newline fails
# Claude Code ignores a project's .claude/settings.json permissions until the folder is trusted; set the flag in each
# account's .claude.json that exists (tmp file + replace, mode 600). Idempotent. No single quote (it sits inside sh
# '...') and no brace (CLONE goes through str.format).
TRUST_PY = """import json, os, sys
d = os.path.abspath(sys.argv[1])
for f in (os.path.expanduser("~/.claude-owa/.claude.json"), os.path.expanduser("~/.claude.json")):
    if not os.path.exists(f):
        continue
    c = json.load(open(f))
    p = c.setdefault("projects", dict()).setdefault(d, dict())
    if p.get("hasTrustDialogAccepted"):
        continue
    p["hasTrustDialogAccepted"] = True
    with open(os.open(f + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as o:
        json.dump(c, o)
    os.replace(f + ".tmp", f)
"""
TRUST = "python3 -c '" + TRUST_PY + "' \"$d\""
# An existing clone is put back on origin's default branch first (a lilguy shop job leaves it on scrum/<id>).
# The raw origin URL (config, not `remote get-url`, which expands insteadOf) must equal the one asked for. Never resets.
CLONE = ('d="$HOME/scrum-work/{p}"; if [ -d "$d/.git" ]; then [ "$(git -C "$d" config --get remote.origin.url)" = {u} ]'
         ' || exit 3; git -C "$d" fetch origin && git -C "$d" checkout -q "$(git -C "$d" symbolic-ref --short refs/remotes/origin/HEAD'
         ' | sed "s,^origin/,,")" && git -C "$d" merge --ff-only refs/remotes/origin/HEAD;'
         ' else mkdir -p "$HOME/scrum-work" && git clone -- {u} "$d"; fi && ' + TRUST)
SHOP_LOGS = ".git/scrum-shop"  # a session's prompt and log, inside the clone's .git so its worktree stays clean
SHOP_ENV = "export SCRUM_PW_CHANNEL=chrome SCRUM_SHOP=1 CLAUDE_NOTIFIER_DISABLE=1 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0; "
START = ("cd ~/scrum-work/{p} && (umask 077 && mkdir -p {d} && cat > {d}/{j}.prompt) || exit 1; {env}" + SHOP_ENV
         + 'nohup claude -p "$(cat {d}/{j}.prompt)" --permission-mode acceptEdits{model}'
         ' < /dev/null > {d}/{j}.log 2>&1 & echo $!')
# ponytail: liveness is `ps -p` showing claude; a reused pid of another claude keeps a dead job alive until it ends
ENDED = ('ps -p {pid} -o command= | grep -q claude && exit 3; f="$HOME/scrum-work/{p}/{d}/{j}.log"; [ -f "$f" ] || exit 0;'
         ' tail -c 8192 "$f"')

CLONES = ("~/code/scrum", "~/code/trevorhecht-skills")  # the clones the shop's ~/.claude skills, agents and rules link to
MD_PULL = " && ".join(f"git -C {c} pull --ff-only" for c in CLONES)
NOTES_IMPORT = "@~/code/scrum/skills/trevskills-scrum/shop/machine-notes.md"
CLEANUP_MARKER = "$HOME/.md-sync-cleanup-done"
# The shop's login shell is zsh, where a glob that matches nothing is an error, so both scripts run in /bin/sh.
# Back up first; a failed backup exits before any mv and writes no marker. mv, not cp: ~/scrum-probe holds a 54 MB
# node tarball plus node_modules, too slow to copy inside STEP_TIMEOUT.
MD_CLEANUP = "/bin/sh -c " + shlex.quote(f'''[ -e "{CLEANUP_MARKER}" ] && exit 0
b="$HOME/md-sync-backup-$(date +%Y-%m-%d-%H%M%S)"
mkdir -p "$b" || exit 1
if [ -e "$HOME/.claude/CLAUDE.md" ]; then cp "$HOME/.claude/CLAUDE.md" "$b/" || exit 1; fi
for m in "$HOME"/.claude/projects/*/memory; do
  [ -d "$m" ] || continue
  k=$(basename "$(dirname "$m")")
  mkdir -p "$b/projects/$k/memory" && cp -R "$m/." "$b/projects/$k/memory/" || exit 1
done
for f in MACHINES.md code/scrum-multi-machine-spec.md scrum-probe; do
  if [ -e "$HOME/$f" ] || [ -L "$HOME/$f" ]; then mv "$HOME/$f" "$b/" || exit 1; fi
done
touch "{CLEANUP_MARKER}"''')
# stdin is the tar from _md_tar(), unpacked in a temp dir under ~/.claude so each mv is a rename. Every memory dir goes,
# then each project's moves in under the key of the shop's own $HOME/scrum-work/<name> (memory_key() in tr). Each
# skills/<name> replaces the shop's ~/.claude/skills/<name> (a link or an older copy); other shop skills stay.
# ponytail: no remote lock; two syncs at once can nest a memory dir. Add a mkdir lock if dispatch ever syncs in parallel.
MD_COPY = "/bin/sh -c " + shlex.quote('mkdir -p "$HOME/.claude/projects" && export TMPDIR="$HOME/.claude" || exit 1; '
                                      + IN_TMP.format('''tar -xf - && mv -f CLAUDE.md "$HOME/.claude/CLAUDE.md" || exit 1
for m in "$HOME"/.claude/projects/*/memory; do
  if [ -e "$m" ] || [ -L "$m" ]; then rm -rf "$m" || exit 1; fi
done
for p in memory/*; do
  [ -d "$p" ] || continue
  k=$(printf %s "$HOME/scrum-work/$(basename "$p")" | tr -c 'A-Za-z0-9' -)
  mkdir -p "$HOME/.claude/projects/$k" && mv "$p" "$HOME/.claude/projects/$k/memory" || exit 1
done
for s in skills/*; do
  [ -d "$s" ] || continue
  n=$(basename "$s")
  mkdir -p "$HOME/.claude/skills" && rm -rf "$HOME/.claude/skills/$n" && mv "$s" "$HOME/.claude/skills/$n" || exit 1
done'''))

# ponytail: module globals with no lock; add one when a second thread calls probe(). Callers treat the dicts as read-only.
_cache = {}  # alias -> (time.monotonic() of the probe, its result)
_ready = {}  # alias -> (time.monotonic() of the ready() check, its result)
REAL_RUN = subprocess.run  # run() refuses ssh under unittest unless a test replaced subprocess.run


def run(cmd: str, timeout: float, input: str | bytes | None = None, alias: str = ALIAS) -> subprocess.CompletedProcess:
    """Run `cmd` on worker `alias` (a ~/.ssh/config Host). Secrets go in `input` (stdin), never in `cmd`. stdout and
    stderr come back as str. An alias off PROJECT_RE (an ssh option, user@host) returns 127 with no ssh, and so does
    unittest with the real subprocess.run (no test faked it), as a down shop Mac."""
    argv = ["ssh", alias, *SSH_OPTS, PATH_PREFIX + cmd]
    if not PROJECT_RE.fullmatch(alias):
        return subprocess.CompletedProcess(argv, 127, "", "bad ssh alias")
    if "unittest" in sys.modules and subprocess.run is REAL_RUN:  # a watchdog test must never dispatch to the real shop
        return subprocess.CompletedProcess(argv, 127, "", "ssh refused under unittest")
    feed = {"stdin": subprocess.DEVNULL} if input is None else {
        "input": input.encode("utf-8") if isinstance(input, str) else input}
    try:
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, **feed)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"ssh {alias} timed out after {timeout} s")
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", f"ssh {alias} could not start: {e}")
    return subprocess.CompletedProcess(argv, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def probe(alias: str = ALIAS) -> dict:
    """{"up", "load", "tools"} of worker `alias` from one round trip cached per alias; `load` is the 1-minute load as a
    percent of all cores (board.cpu_load_pct's unit) or None when unreadable. Down (any non-zero exit) is silent and
    never raises."""
    now = time.monotonic()
    hit = _cache.get(alias)
    if hit and now - hit[0] < (UP_TTL if hit[1]["up"] else DOWN_TTL):
        return hit[1]
    r = run(PROBE_CMD, PROBE_TIMEOUT, alias=alias)
    lines = r.stdout.splitlines() if r.returncode == 0 else []
    try:
        load = round(float(lines[0].strip("{} ").split()[0]) / int(lines[1]) * 100, 1)
    except (IndexError, ValueError, ZeroDivisionError):
        load = None
    tools = {t: any(line.rsplit("/", 1)[-1] == t for line in lines) for t in TOOLS}
    _cache[alias] = (now, {"up": r.returncode == 0, "load": load, "tools": tools})
    return _cache[alias][1]


def account_env(name: str) -> str:
    """The shell prefix that selects shop account `name` (a SHOP_ACCOUNTS key) and loads its `claude setup-token` file
    in the shop's own shell, so the token never reaches this Mac's argv, stdout or logs. Dispatch puts it before its
    own `claude` command."""
    conf = SHOP_ACCOUNTS[name]
    return ((f'export CLAUDE_CONFIG_DIR="{conf}"; ' if conf else "")
            + f'[ -r {_token_file(name)} ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat {_token_file(name)})"; ')


def _token_file(name: str) -> str:
    return f'"{SHOP_ACCOUNTS[name] or "$HOME/.claude"}/oauth-token"'


def _account(name: str, alias: str) -> str:
    """"ok" when shop account `name` answers a headless `claude -p`, "no token" when its token file is missing, else
    "not ready"."""
    r = run(f"[ -r {_token_file(name)} ] || exit {NO_TOKEN}; {account_env(name)}{ACCOUNT_CHECK}", ACCOUNT_TIMEOUT,
            alias=alias)
    if r.returncode == 0 and "ok" in r.stdout.lower():
        return "ok"
    return "no token" if r.returncode == NO_TOKEN else "not ready"


def _permissions_script() -> str:
    """The Python the shop runs from stdin to merge SHOP_PERMISSIONS into its ~/.claude/settings.json; prints
    `changed` or `same`, and exits non-zero without writing on malformed JSON."""
    return f"import json, os, sys, tempfile\nPERMS = json.loads({json.dumps(SHOP_PERMISSIONS)!r})\n{MERGE_SCRIPT}"


def _done(r: subprocess.CompletedProcess) -> tuple[str, str]:
    return ("changed", "") if r.returncode == 0 else ("failed", f" (exit {r.returncode})")


def _gh_login(alias: str) -> tuple[str, str]:
    """Pipe this Mac's gh token into the shop's gh login on stdin, unless the shop is already logged in."""
    if run("gh auth status", STEP_TIMEOUT, alias=alias).returncode == 0:
        return "ok", ""
    try:
        local = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=STEP_TIMEOUT)
    except OSError:
        return "failed", " (exit 127)"
    except subprocess.TimeoutExpired:
        return "failed", " (exit 124)"
    token = local.stdout.strip()
    if local.returncode or not token:
        return "failed", f" (exit {local.returncode or 1})"
    return _done(run(GH_LOGIN, STEP_TIMEOUT, input=token, alias=alias))


def _gh_git(alias: str) -> tuple[str, str]:
    if "gh auth git-credential" in run(GIT_HELPER, STEP_TIMEOUT, alias=alias).stdout:
        return "ok", ""
    return _done(run("gh auth setup-git", STEP_TIMEOUT, alias=alias))


def _owa_links(alias: str) -> tuple[str, str]:
    r = run(OWA_CHECK, STEP_TIMEOUT, alias=alias)
    if r.returncode:
        return _done(r)
    missing = [n for n in r.stdout.split() if n in OWA_LINKS]
    if not missing:
        return "ok", ""
    return _done(run(" && ".join(f'ln -s "$HOME/.claude/{n}" "$HOME/.claude-owa/{n}"' for n in missing), STEP_TIMEOUT,
                     alias=alias))


def _permissions(alias: str) -> tuple[str, str]:
    r = run("python3 -", STEP_TIMEOUT, input=_permissions_script(), alias=alias)
    if r.returncode:
        return _done(r)
    return ("changed" if "changed" in r.stdout.split() else "ok"), ""  # split: a shell startup line may come first


def _account_step(name: str, alias: str) -> tuple[str, str]:
    a = _account(name, alias)
    return ("ok", "") if a == "ok" else ("not ready", TOKEN_HINT if a == "no token" else "")


def _accounts(alias: str) -> list[str]:
    """The SHOP_ACCOUNTS names on `alias`'s workers() line, in SHOP_ACCOUNTS order; every one when it has no line."""
    line = next((w.accounts for w in workers() if w.alias == alias), SHOP_ACCOUNTS)
    return [n for n in SHOP_ACCOUNTS if n in line]


def setup(alias: str = ALIAS) -> dict[str, str]:
    """Prepare worker `alias` for a scrum job: {step: "ok"|"changed"|"failed"|"not ready"}, printing one
    `<step>: <result>` line per step and never remote output; the account steps cover _accounts(alias). Every step
    checks before it acts, so a second run changes nothing. A down worker prints `shop: down` and returns
    {"shop": "failed"} after the one probe. Drops only this alias's probe and ready() caches."""
    _cache.pop(alias, None)
    _ready.pop(alias, None)
    p = probe(alias)
    if not p["up"]:
        print("shop: down", flush=True)
        return {"shop": "failed"}
    tools = p["tools"]
    steps = {"node": lambda: ("ok", "") if tools["node"] else _done(run(NODE_INSTALL, INSTALL_TIMEOUT, alias=alias)),
             "gh": lambda: ("ok", "") if tools["gh"] else _done(run(GH_INSTALL, INSTALL_TIMEOUT, alias=alias)),
             "gh login": lambda: _gh_login(alias), "gh git": lambda: _gh_git(alias),
             "permissions": lambda: _permissions(alias), "owa links": lambda: _owa_links(alias),
             **{f"account {n}": (lambda n=n: _account_step(n, alias)) for n in _accounts(alias)}}
    out = {}
    for name, step in steps.items():
        out[name], note = step()
        print(f"{name}: {'ok (changed)' if out[name] == 'changed' else out[name]}{note}", flush=True)
    _cache.pop(alias, None)  # the steps changed what probe() and ready() report
    _ready.pop(alias, None)
    return out


def ready(alias: str = ALIAS) -> dict:
    """{"ready", "up", "gh", "node", "claude", "accounts": {<name>: bool for _accounts(alias)}}, all bools, of worker
    `alias`. `ready`: up, gh logged in, node and claude present and at least one account answering. A down worker
    returns all false at once, with no ssh beyond probe()'s cache; an up result is cached per alias for READY_TTL and
    setup(alias) clears it. Prints nothing."""
    p = probe(alias)
    if not p["up"]:
        return {"ready": False, "up": False, "gh": False, "node": False, "claude": False,
                "accounts": {n: False for n in _accounts(alias)}}
    now = time.monotonic()
    hit = _ready.get(alias)
    if hit and now - hit[0] < READY_TTL:
        return hit[1]
    gh = run("gh auth status", STEP_TIMEOUT, alias=alias).returncode == 0
    accounts = {n: _account(n, alias) == "ok" for n in _accounts(alias)}
    node, claude = p["tools"]["node"], p["tools"]["claude"]
    _ready[alias] = (now, {"ready": gh and node and claude and any(accounts.values()), "up": True, "gh": gh,
                           "node": node, "claude": claude, "accounts": accounts})
    return _ready[alias][1]


def env_copy(project: str, repo: str, alias: str = ALIAS) -> str:
    """Copy `<repo>/.env.local` to the shop's `~/scrum-work/<project>/.env.local` over stdin under umask 077:
    "copied", "none" (no .env.local; no ssh) or "failed" (a bad project name, a down shop Mac or a failed copy).
    Prints and logs nothing."""
    if not PROJECT_RE.fullmatch(project):
        return "failed"
    try:
        data = (Path(repo) / ".env.local").read_bytes()
    except FileNotFoundError:
        return "none"
    except OSError:
        return "failed"
    if not probe(alias)["up"]:
        return "failed"
    return "copied" if run(ENV_COPY.format(p=project), STEP_TIMEOUT, input=data, alias=alias).returncode == 0 \
        else "failed"


def _render_auth(text: str) -> str | None:
    """project.md's `- Render auth:` path read from a job worktree ($WT, as lanes/review.md does) as a repo-relative
    path, or None: no line, or a path outside the repo, under .claude/ or with a character off [A-Za-z0-9._/-]."""
    m = RENDER_AUTH_RE.search(text)
    if not m:
        return None
    rel = posixpath.normpath(".claude/worktrees/scrum-x/" + m.group(1).strip())
    if rel.startswith("..") or posixpath.isabs(rel) or (rel + "/").startswith(".claude/") \
            or not re.fullmatch(r"[A-Za-z0-9._/-]+", rel):
        return None
    return rel


def profile_copy(project: str, repo: str, alias: str = ALIAS) -> str:
    """Write the shop's ~/scrum-work/<project>/scrum/project.md from this Mac's <repo>/scrum/project.md (stdin only,
    tmp file + mv -f), so a cloud-job session there keeps its E2E, Test sign-in and Render auth lines (cloud.md Setup).
    The repo path (as given and its realpath) becomes the shop clone and any other path under this Mac's home moves
    to the shop's $HOME; every other byte is unchanged. The same call adds setup's `scrum/` and `.claude/worktrees/`
    lines to the clone's .git/info/exclude. Then the file the Render auth line names, when _render_auth() accepts it
    and it exists here, goes to the same repo-relative path there (mode 600, bytes on stdin only). "copied"; "none"
    with no ssh when there is no project.md here; "failed" with no ssh for a name off PROJECT_RE, or for a down shop
    Mac, no clone there or a failed or timed-out copy. Prints nothing."""
    if not PROJECT_RE.fullmatch(project):
        return "failed"
    try:
        text = (Path(repo) / "scrum" / "project.md").read_bytes().decode("utf-8", "surrogateescape")
    except FileNotFoundError:
        return "none"
    except OSError:
        return "failed"
    rel = _render_auth(text)
    try:
        auth = (Path(repo) / rel).read_bytes() if rel else None
    except OSError:
        auth = None
    paths = sorted({str(repo), os.path.realpath(repo)}, key=len, reverse=True)
    text = re.sub("(?:" + "|".join(map(re.escape, paths)) + r")(?![A-Za-z0-9._-])",
                  lambda _: f"{HOME_TOKEN}/scrum-work/{project}", text)
    text = text.replace(str(Path.home()) + "/", HOME_TOKEN + "/")
    if not probe(alias)["up"] or run(PROFILE_COPY.format(p=project, t=HOME_TOKEN), STEP_TIMEOUT,
                                     input=text.encode("utf-8", "surrogateescape"), alias=alias).returncode:
        return "failed"
    if auth is not None and run(AUTH_COPY.format(p=project, d=shlex.quote(posixpath.dirname(rel)),
                                                 f=shlex.quote(rel)), STEP_TIMEOUT, input=auth, alias=alias).returncode:
        return "failed"
    return "copied"


def clone(project: str, url: str, alias: str = ALIAS) -> bool:
    """Clone `url` into the shop's ~/scrum-work/<project>, or fetch and fast-forward that clone to origin's HEAD when
    its origin is `url`. False with no ssh for a name off PROJECT_RE or a URL off REPO_URL_RE (https GitHub only), and
    False for another origin, a merge that is not a fast-forward or a failed call. Never resets or deletes."""
    if not PROJECT_RE.fullmatch(project) or not REPO_URL_RE.fullmatch(url):
        return False
    return run(CLONE.format(p=project, u=shlex.quote(url)), INSTALL_TIMEOUT, alias=alias).returncode == 0


def start(project: str, job_id: str, prompt: str, account: str, model: str | None = None,
          alias: str = ALIAS) -> int | None:
    """Start a headless `claude -p` cloud-job session in the shop's ~/scrum-work/<project> on SHOP_ACCOUNTS `account`,
    in the background with its output in .git/scrum-shop/<job_id>.log: its pid, or None (a non-zero exit, output that
    is not a pid). `prompt` goes only on stdin, into a umask 077 prompt file. None with no ssh for a project off
    PROJECT_RE, a job id off JOB_RE or an unknown account."""
    if not PROJECT_RE.fullmatch(project) or not JOB_RE.fullmatch(job_id) or account not in SHOP_ACCOUNTS:
        return None
    r = run(START.format(p=project, d=SHOP_LOGS, j=job_id, env=account_env(account),
                         model=f" --model {shlex.quote(model)}" if model else ""), STEP_TIMEOUT, input=prompt,
            alias=alias)
    lines = r.stdout.split()  # the pid is the last word: a shell startup line may come first
    return int(lines[-1]) if r.returncode == 0 and lines and re.fullmatch(r"[0-9]{1,10}", lines[-1]) else None


def ended(project: str, job_id: str, pid: int, alias: str = ALIAS) -> str | None:
    """The last 8192 bytes of a finished shop session's log ("" with no log), or None while `ps -p <pid>` still shows
    claude, the shop Mac is down, a name is off PROJECT_RE or JOB_RE, or the call fails. Prints nothing."""
    if not PROJECT_RE.fullmatch(project) or not JOB_RE.fullmatch(job_id) or not probe(alias)["up"]:
        return None
    r = run(ENDED.format(pid=int(pid), p=project, d=SHOP_LOGS, j=job_id), STEP_TIMEOUT, alias=alias)
    return r.stdout if r.returncode == 0 else None


def memory_key(path: str) -> str:
    """Claude Code's ~/.claude/projects/ dir name for `path`: every character outside [A-Za-z0-9] becomes `-`."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _registry() -> Path:
    """projects.json's path: SCRUM_REGISTRY, else ~/.claude/trevskills-scrum/projects.json (read_registry's rule)."""
    return Path(os.environ.get("SCRUM_REGISTRY") or Path.home() / ".claude" / "trevskills-scrum" / "projects.json")


def workers() -> list[Worker]:
    """One Worker(alias, max, accounts) per valid line of workers.txt beside projects.json, in file order. A line is
    `<alias> <max jobs> <account>[,<account>...]`; `#` starts a comment. A line without 3 fields, an alias off
    PROJECT_RE (never an ssh option) or already listed, a max off MAX_RE, or an empty, repeated or unknown
    (SHOP_ACCOUNTS) account is skipped. No file: today's one shop Mac; an unreadable file or no valid line: []."""
    try:
        text = (_registry().parent / "workers.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        return [Worker(ALIAS, 2, ("owa", "main"))]
    except (OSError, ValueError):
        return []
    out = []
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) != 3:
            continue
        alias, most, names = fields[0], fields[1], fields[2].split(",")
        if PROJECT_RE.fullmatch(alias) and MAX_RE.fullmatch(most) and len(set(names)) == len(names) \
                and all(n in SHOP_ACCOUNTS for n in names) and alias not in (w.alias for w in out):
            out.append(Worker(alias, int(most), tuple(names)))
    return out


def _projects() -> dict[str, Path]:
    """{folder name: repo} for each projects.json entry (SCRUM_REGISTRY moves it) with a scrum/ dir whose folder name
    matches PROJECT_RE and whose memory_key() no other such entry shares (app.one and app-one would share one shop
    memory dir). Read here as board.read_registry does, since board.py and serve.py will import shop."""
    try:
        paths = json.loads(_registry().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(paths, list):
        return {}
    repos = [Path(p) for p in paths
             if isinstance(p, str) and PROJECT_RE.fullmatch(Path(p).name) and (Path(p) / "scrum").is_dir()]
    keys = [memory_key(r.name) for r in repos]
    return {r.name: r for r in repos if keys.count(memory_key(r.name)) == 1}


def _md_tar() -> bytes:
    """The copy step's stdin: CLAUDE.md (this Mac's bytes, a newline when they lack one, then NOTES_IMPORT),
    memory/<name>/ for each _projects() entry that has a memory dir here, and skills/<name>/ for each plain folder in
    ~/.claude/skills (not a link, not `synced`, a PROJECT_RE name; jobs read files there, e.g. trevskills-email's
    ai-tells.md), its links copied as files and a broken one skipped. Raises OSError (no CLAUDE.md, a bad read)."""
    claude = Path.home() / ".claude"
    text = (claude / "CLAUDE.md").read_bytes()
    text += (b"" if text.endswith(b"\n") else b"\n") + NOTES_IMPORT.encode() + b"\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", dereference=True) as tar:
        info = tar.gettarinfo(claude / "CLAUDE.md", "CLAUDE.md")
        info.size = len(text)
        tar.addfile(info, io.BytesIO(text))
        for name, repo in _projects().items():
            mem = claude / "projects" / memory_key(str(repo)) / "memory"
            if mem.is_dir():
                tar.add(mem, f"memory/{name}")
        skills = claude / "skills"
        for d in sorted(skills.iterdir()) if skills.is_dir() else ():
            if d.is_symlink() or not d.is_dir() or d.name == "synced" or not PROJECT_RE.fullmatch(d.name):
                continue
            for top, _, files in os.walk(d):
                for f in sorted(files):
                    p = Path(top, f)
                    if p.is_file():  # follows a link; a broken one is skipped (tar.add would raise)
                        tar.add(p, f"skills/{d.name}/{p.relative_to(d).as_posix()}")
    return buf.getvalue()


def md_sync(alias: str = ALIAS) -> bool:
    """Make this Mac the single writer of what shop sessions read: pull the shop's skill clones (MD_PULL), run the
    one-time cleanup (MD_CLEANUP) and replace its CLAUDE.md, memory dirs and the skill folders this Mac has as plain
    folders (MD_COPY), each one run() of STEP_TIMEOUT.
    True when all three exit 0; False at the first failure, with no later call. This Mac's files are read before any
    ssh, so a missing CLAUDE.md costs no call, and a down shop Mac costs only the probe. Prints nothing."""
    try:
        stream = _md_tar()
    except OSError:
        return False
    if not probe(alias)["up"]:
        return False
    return all(run(cmd, STEP_TIMEOUT, input=data, alias=alias).returncode == 0
               for cmd, data in ((MD_PULL, None), (MD_CLEANUP, None), (MD_COPY, stream)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shop.py", description="Talk to a worker Mac over ssh <alias>.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("probe", "print the probe as one JSON line"),
                       ("setup", "prepare the worker Mac for a scrum job; one line per step"),
                       ("md-sync", "pull the worker's skill clones and copy CLAUDE.md, memory and skill folders there; one line")):
        sub.add_parser(name, help=text).add_argument("alias", nargs="?", help="default: the first workers.txt alias")
    args = parser.parse_args(argv)
    command, alias = args.command, args.alias or next((w.alias for w in workers()), ALIAS)
    if command == "setup":
        return 1 if "failed" in setup(alias).values() else 0
    if command == "md-sync":
        if not probe(alias)["up"]:
            print("shop: down")
            return 1
        ok = md_sync(alias)
        print(f"md-sync: {'ok' if ok else 'failed'}")
        return 0 if ok else 1
    print(json.dumps(probe(alias)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
