#!/usr/bin/env python3
"""The one Trevskills Scrum dashboard, for every project: serves the dashboard, each registered project's scrum/
files, and a small JSON API so the buttons can edit backlogs and start Claude runs (approve, rework, run now, abort).

  python3 ~/.claude/skills/trevskills-scrum/serve.py      → http://localhost:8765   (or click the app icon)

Projects come from the registry that /trevskills-scrum fills in (board.py register). Binds 127.0.0.1 only. Every
request must carry a localhost Host header (blocks DNS rebinding), and every write must be a JSON POST from no
origin or a localhost origin; a cross-site page can't send that without a CORS preflight, which is never approved.
"""
import argparse, json, os, re, shutil, signal, subprocess, sys, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board  # noqa: E402

# Started from the app icon, PATH can be bare, so look in the usual install spots too. Tests set SCRUM_CLAUDE.
CLAUDE = os.environ.get("SCRUM_CLAUDE") or shutil.which("claude") or next(
    (str(p) for p in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"), Path.home() / ".claude/local/claude")
     if p.exists()), "claude")
LOCAL = {"localhost", "127.0.0.1"}
TYPES = {".json": "application/json", ".md": "text/markdown; charset=utf-8", ".log": "text/plain; charset=utf-8",
         ".html": "text/html; charset=utf-8"}
RUNS, RUNS_LOCK = {}, threading.Lock()  # "project/job id" -> {"action", "started", "proc", "log"}
ESTIMATE_PROMPT = """You are estimating one backlog item for the repository in the current directory.
Look only at what you need (CLAUDE.md, the files the item would touch). Do not change anything.
Reply with ONLY one JSON object: {{"points": <one of 1, 2, 3, 5, 8, 13>, "why": "<one short sentence>"}}
Scale: 1 trivial tweak · 2 one small file · 3 a few files · 5 several layers (API + UI) · 8 large or risky · 13 too big, should be split.
Item: {text}"""


def running(project, job_id):
    with RUNS_LOCK:
        run = RUNS.get(f"{project}/{job_id}")
        return bool(run and run["proc"].poll() is None)


def stop(project, job_id):
    """Terminate a dashboard-started run and everything it spawned (it runs in its own process group)."""
    with RUNS_LOCK:
        run = RUNS.get(f"{project}/{job_id}")
    if run and run["proc"].poll() is None:
        try:
            os.killpg(run["proc"].pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def spawn(project, root, job_id, action, prompt):
    """Start `claude -p <prompt>` in the repo, detached, logging to scrum/runs/. The dashboard shows it as running."""
    logs = root / "runs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{datetime.now():%Y%m%d-%H%M%S}-{action}-{job_id}.log"
    with open(log, "w") as fh:
        proc = subprocess.Popen([CLAUDE, "-p", prompt, "--permission-mode", "acceptEdits"], cwd=root.parent,
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    with RUNS_LOCK:
        RUNS[f"{project}/{job_id}"] = {"action": action, "started": time.time(), "proc": proc, "log": f"runs/{log.name}"}


def estimate(root, text):
    """Ask Sonnet for Fibonacci points in the background; on any failure the item just stays unestimated."""
    try:
        out = subprocess.run([CLAUDE, "-p", "--model", "sonnet", "--allowedTools", "Read,Grep,Glob",
                              ESTIMATE_PROMPT.format(text=text)], cwd=root.parent, capture_output=True, text=True,
                             timeout=180, stdin=subprocess.DEVNULL).stdout
        for blob in reversed(re.findall(r"\{[^{}]*\}", out)):
            data = json.loads(blob)
            if "points" in data:
                board.backlog_set_estimate(root, text, data["points"], data.get("why"))
                return
    except (subprocess.SubprocessError, OSError, ValueError, SystemExit):
        pass


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
ITEM = re.compile(r"(\s*)-\s+(.+)")
AGENT_LOCK = threading.Lock()


def agents_dir():
    """The checkout serve.py runs from (the main one, when installed); tests point SCRUM_AGENTS_DIR elsewhere."""
    return Path(os.environ.get("SCRUM_AGENTS_DIR") or HERE.parent.parent / "agents")


def read_agent(path):
    """Frontmatter fields, the `skills:` list (block or `a, b` form) and the markdown body of one agent file."""
    text = path.read_text()
    m = FRONTMATTER.match(text)
    meta, skills, key = {}, [], None
    for line in (m.group(1) if m else "").splitlines():
        if (item := ITEM.fullmatch(line)) and key == "skills":
            skills.append(item.group(2).strip())
        elif ":" in line and not line[:1].isspace():
            key, _, val = (x.strip() for x in line.partition(":"))
            meta[key] = val
            if key == "skills":
                skills += [s.strip() for s in val.strip("[]").split(",") if s.strip()]
    return {"name": path.stem, "model": meta.get("model", ""), "tools": meta.get("tools", ""),
            "description": meta.get("description", ""), "skills": skills, "body": text[m.end():] if m else text}


def add_skill(path, skill):
    """Append `  - skill` under `skills:` (creating the key after the last frontmatter line); other bytes stay put."""
    with AGENT_LOCK:
        text = path.read_text()
        m = FRONTMATTER.match(text)
        if not m:
            raise SystemExit("agent file has no frontmatter")
        have = read_agent(path)["skills"]
        if skill in have:
            return
        lines = m.group(1).split("\n")
        at = next((i for i, l in enumerate(lines) if re.match(r"skills\s*:", l)), None)
        if at is None:
            lines += ["skills:", f"  - {skill}"]
        elif lines[at].split(":", 1)[1].strip():  # one-line `skills: a, b` becomes a block list
            lines[at:at + 1] = ["skills:"] + [f"  - {s}" for s in have + [skill]]
        else:
            items, i = [], at + 1  # skip blank and `#` comment lines; stop at anything else
            while i < len(lines) and (ITEM.fullmatch(lines[i]) or lines[i].lstrip()[:1] in ("", "#")):
                if ITEM.fullmatch(lines[i]):
                    items.append(i)
                i += 1
            indent = ITEM.fullmatch(lines[items[0]]).group(1) if items else "  "
            lines.insert(items[-1] + 1 if items else at + 1, f"{indent}- {skill}")
        path.write_text(text[:m.start(1)] + "\n".join(lines) + text[m.end(1):])


def claude_home():
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def skill_files():
    """{name: (source, SKILL.md path)} for user skills and user-scope plugin skills, named <plugin>:<skill>."""
    home = claude_home()
    found = {p.parent.name: ("user", p) for p in home.glob("skills/*/SKILL.md")}
    try:
        plugins, extra = json.loads((home / "plugins" / "installed_plugins.json").read_text())["plugins"], {}
        for key, installs in plugins.items():
            plugin = key.split("@")[0]
            for inst in installs:
                if inst.get("scope") == "user":
                    extra.update({f"{plugin}:{p.parent.name}": (plugin, p) for p in Path(inst["installPath"]).glob("skills/*/SKILL.md")})
        found.update(extra)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass  # a missing or malformed plugins file just adds nothing
    return found


def installed_skills():
    """User skills (~/.claude/skills/*/SKILL.md) and user-scope plugin skills, named <plugin>:<skill>."""
    found = skill_files()
    return [{"name": n, "source": found[n][0]} for n in sorted(found)]


# --- AI-Settings: a read-only view of every Claude Code config source -----------------------------------------------
# Paths and precedence adapted from mcpware/cross-code-organizer (MIT)
#   managed  /Library/Application Support/ClaudeCode/{managed-settings.json, managed-mcp.json}   (CLAUDE_MANAGED_DIR)
#   user     CLAUDE_HOME: skills/*/SKILL.md (+ plugin skills), commands/ agents/ rules/ *.md, CLAUDE.md,
#            projects/*/memory/*.md, settings.json (+ hooks), plugins/installed_plugins.json; ~/.claude.json mcpServers
#   project  <root>: CLAUDE.md, .claude/{skills/*/SKILL.md, commands, agents, rules}, .claude/settings.json (+ hooks), .mcp.json
#   local    <root>: CLAUDE.local.md, .claude/settings.local.json (+ hooks), ~/.claude.json projects[<root>].mcpServers
CATEGORIES = [("skills", "Skills"), ("mcp", "MCP Servers"), ("commands", "Commands"), ("agents", "Agents"), ("rules", "Rules"),
              ("config", "Config"), ("hooks", "Hooks"), ("plugins", "Plugins"), ("settings", "Settings")]
RANK = {"managed": 0, "local": 1, "project": 2, "user": 3}  # lower wins
NAMED = {"skills", "mcp", "commands", "agents"}  # the rest are additive: everything loads, nothing is overridden
WALK_DEPTH, WALK_SKIP = 6, {"node_modules", "Library"}  # fixed on purpose; dot-dirs are skipped too
SECRET_KEY = re.compile(r"token|secret|password|api[_-]?key|authorization", re.I)


def user_home():
    """Tests point CLAUDE_HOME at <fake home>/.claude, so ~ is its parent; otherwise the real home."""
    return Path(os.environ["CLAUDE_HOME"]).parent if os.environ.get("CLAUDE_HOME") else Path.home()


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def as_dict(v):
    return v if isinstance(v, dict) else {}


def redact(v, key=""):
    """Every value under env/headers, and every string under a secret-looking key, becomes "[redacted]"."""
    if key.lower() in ("env", "headers"):
        return {k: "[redacted]" for k in v} if isinstance(v, dict) else "[redacted]"
    if isinstance(v, dict):
        return {k: redact(x, str(k)) for k, x in v.items()}
    if isinstance(v, list):
        return [redact(x, key) for x in v]
    return "[redacted]" if isinstance(v, str) and SECRET_KEY.search(key) else v


def walk_claude_dirs(d, depth, found):
    """Add every folder under d that holds a .claude dir; never descends into dot-dirs, node_modules or Library."""
    try:
        entries = list(os.scandir(d))
    except OSError:
        return
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if e.name == ".claude":
            found.add(os.path.realpath(d))
        elif depth + 1 < WALK_DEPTH and not e.name.startswith(".") and e.name not in WALK_SKIP:
            walk_claude_dirs(e.path, depth + 1, found)


def ai_scopes(with_mac=True):
    """{scope id: (group, label, root or None)}. The home walk runs on each call (~0.2 s on Trevor's Mac), no cache."""
    home = os.path.realpath(user_home())
    scopes = {"global": ("global", "Global", None)}
    registered = board.projects()
    scopes.update({f"r:{n}": ("registered", n, Path(p)) for n, p in registered.items()})
    if with_mac:
        found = {os.path.realpath(k) for k in as_dict(as_dict(load_json(Path(home) / ".claude.json")).get("projects"))
                 if os.path.isdir(k)}
        walk_claude_dirs(home, 0, found)
        found -= {home} | {os.path.realpath(p) for p in registered.values()}
        for root in sorted(found):
            label = os.path.relpath(root, home) if root.startswith(home + os.sep) else root
            scopes[f"m:{label}"] = ("mac", label, Path(root))
    return scopes


def ai_inventory(scope_id):
    """{category: [item]} for one scope, or None for an unknown scope. Items keep their entry/path for the detail view."""
    scopes = ai_scopes(with_mac=scope_id.startswith("m:"))
    if scope_id not in scopes:
        return None
    root, home, user = scopes[scope_id][2], user_home(), claude_home()
    managed = Path(os.environ.get("CLAUDE_MANAGED_DIR") or "/Library/Application Support/ClaudeCode")
    claude_json = home / ".claude.json"
    cj = as_dict(load_json(claude_json))
    raw = []  # (category, scope, name, path, is_json, entry)

    def md(cat, scope, paths, name=lambda p: p.stem):
        raw.extend((cat, scope, name(p), p, False, None) for p in sorted(paths) if p.is_file())

    def settings(scope, path):
        data = load_json(path)
        if not isinstance(data, dict):
            return
        raw.append(("settings", scope, path.name, path, True, data))
        for event, entries in as_dict(data.get("hooks")).items():
            for e in entries if isinstance(entries, list) else []:
                if isinstance(e, dict):
                    raw.append(("hooks", scope, f"{event} · {e.get('matcher') or '*'}", path, True, e))

    def mcp(scope, path, servers):
        raw.extend(("mcp", scope, n, path, True, e) for n, e in as_dict(servers).items())

    def claude_dir(scope, d):
        md("skills", scope, d.glob("skills/*/SKILL.md"), lambda p: p.parent.name)
        for cat in ("commands", "agents", "rules"):
            md(cat, scope, d.glob(f"{cat}/*.md"))

    settings("managed", managed / "managed-settings.json")
    mcp("managed", managed / "managed-mcp.json", as_dict(load_json(managed / "managed-mcp.json")).get("mcpServers"))
    claude_dir("user", user)
    raw.extend(("skills", "user", n, p, False, None) for n, (src, p) in sorted(skill_files().items()) if src != "user")
    md("config", "user", [user / "CLAUDE.md"], lambda p: p.name)
    md("config", "user", user.glob("projects/*/memory/*.md"), lambda p: str(p.relative_to(user)))
    settings("user", user / "settings.json")
    plugins = user / "plugins" / "installed_plugins.json"
    raw.extend(("plugins", "user", k, plugins, True, v) for k, v in as_dict(as_dict(load_json(plugins)).get("plugins")).items())
    mcp("user", claude_json, cj.get("mcpServers"))
    if root:
        md("config", "project", [root / "CLAUDE.md"], lambda p: p.name)
        claude_dir("project", root / ".claude")
        settings("project", root / ".claude" / "settings.json")
        mcp("project", root / ".mcp.json", as_dict(load_json(root / ".mcp.json")).get("mcpServers"))
        md("config", "local", [root / "CLAUDE.local.md"], lambda p: p.name)
        settings("local", root / ".claude" / "settings.local.json")
        real = os.path.realpath(root)
        mcp("local", claude_json, next((as_dict(v).get("mcpServers") for k, v in as_dict(cj.get("projects")).items()
                                        if os.path.realpath(k) == real), None))

    out, seen = {cat: [] for cat, _ in CATEGORIES}, set()
    for cat, scope, name, path, is_json, entry in raw:
        item_id = f"{scope_id}|{cat}|{scope}|{path}|{name}"
        n = 1
        while item_id + (f"#{n}" if n > 1 else "") in seen:
            n += 1
        item_id += f"#{n}" if n > 1 else ""
        seen.add(item_id)
        out[cat].append({"id": item_id, "name": str(name), "scope": scope, "path": str(path), "status": "",
                         "_json": is_json, "_entry": entry})
    for cat, items in out.items():
        if cat in NAMED:
            by_name = {}
            for it in items:
                by_name.setdefault(it["name"], []).append(it)
            for same in by_name.values():
                if len({it["scope"] for it in same}) > 1:
                    top = min(RANK[it["scope"]] for it in same)
                    for it in same:
                        it["status"] = "wins" if RANK[it["scope"]] == top else "overridden"
        items.sort(key=(lambda it: RANK[it["scope"]]) if cat == "settings" else (lambda it: (it["name"].lower(), RANK[it["scope"]])))
    return out


def ai_settings_scope(scope_id):
    inv = ai_inventory(scope_id)
    if inv is None:
        return None
    return {"scope": scope_id, "categories": [
        {"key": cat, "label": label, "count": len(inv[cat]),
         "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in inv[cat]]} for cat, label in CATEGORIES]}


def ai_settings_item(item_id):
    """One item's path and content. Only ids from a freshly built inventory resolve, so no client path is ever read."""
    inv = ai_inventory(item_id.split("|", 1)[0]) if "|" in item_id else None
    it = next((x for items in (inv or {}).values() for x in items if x["id"] == item_id), None)
    if not it:
        return None
    if it["_json"]:
        content = json.dumps(redact(it["_entry"]), indent=2)
    else:
        try:
            content = Path(it["path"]).read_text(errors="replace")
        except OSError:
            return None
    return {k: v for k, v in it.items() if not k.startswith("_")} | {"content": content}


def scrum_dir(project):
    repo = board.projects().get(project)
    return repo / "scrum" if repo else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        self.send(code, json.dumps(obj).encode(), "application/json")

    def local_host(self):
        return urlparse("//" + (self.headers.get("Host") or "")).hostname in LOCAL

    def do_GET(self):
        path = urlparse(self.path).path
        if not self.local_host():
            return self.send_json(403, {"error": "forbidden host"})
        if path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/dashboard.html")
            return self.end_headers()
        if path == "/dashboard.html":
            return self.send(200, (HERE / "dashboard.html").read_bytes(), TYPES[".html"])
        if path == "/api/agents":
            return self.send_json(200, [read_agent(p) for p in sorted(agents_dir().glob("*.md"))])
        if path == "/api/skills":
            return self.send_json(200, installed_skills())
        if path == "/api/ai-settings":
            scope = parse_qs(urlparse(self.path).query).get("scope", [None])[0]
            if scope is None:
                groups = {"global": [], "registered": [], "mac": []}
                for sid, (group, label, _) in ai_scopes().items():
                    groups[group].append({"id": sid, "label": label})
                return self.send_json(200, groups)
            data = ai_settings_scope(scope)
            return self.send_json(200, data) if data else self.send_json(404, {"error": "no such scope"})
        if path == "/api/ai-settings/item":
            data = ai_settings_item(parse_qs(urlparse(self.path).query).get("id", [""])[0])
            return self.send_json(200, data) if data else self.send_json(404, {"error": "no such item"})
        if path == "/api/projects":
            return self.send_json(200, [{"name": name} for name in board.projects()])
        if path == "/api/runs":
            with RUNS_LOCK:
                return self.send_json(200, [{"project": k.rsplit("/", 1)[0], "id": k.rsplit("/", 1)[1], "action": r["action"],
                                             "started": r["started"], "log": r["log"], "alive": r["proc"].poll() is None,
                                             "exit": r["proc"].poll()} for k, r in RUNS.items()])
        if m := re.fullmatch(r"/api/p/(.+)/backlog", path):
            root = scrum_dir(unquote(m.group(1)))
            return self.send_json(200, board.backlog_items(root)) if root else self.send_json(404, {"error": "no such project"})
        if m := re.fullmatch(r"/p/([^/]+(?:%2F[^/]+)?)/(.+)", path):
            return self.send_project_file(unquote(m.group(1)), unquote(m.group(2)))
        self.send_json(404, {"error": "not found"})

    def send_project_file(self, project, rel):
        """Only .json/.md/.log files that really sit inside that project's scrum/ folder."""
        root = scrum_dir(project)
        if root:
            target = os.path.realpath(root / rel)
            if target.startswith(os.path.realpath(root) + os.sep) and Path(target).suffix in (".json", ".md", ".log") \
                    and os.path.isfile(target):
                return self.send(200, Path(target).read_bytes(), TYPES[Path(target).suffix])
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (not self.local_host() or "application/json" not in (self.headers.get("Content-Type") or "")
                or (origin and urlparse(origin).hostname not in LOCAL)):
            return self.send_json(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            body, path = body if isinstance(body, dict) else {}, urlparse(self.path).path
            if a := re.fullmatch(r"/api/agents/([^/]+)/skills", path):
                code, obj = self.route_skill(unquote(a.group(1)), body.get("skill"))
            else:
                m = re.fullmatch(r"/api/p/(.+?)(/backlog(?:/run)?|/jobs/[^/]+/(?:approve|rework|abort))", path)
                root = m and scrum_dir(unquote(m.group(1)))
                code, obj = self.route(unquote(m.group(1)), root, m.group(2), body) \
                    if root else (404, {"error": "no such project or endpoint"})
        except ValueError:
            code, obj = 400, {"error": "body must be JSON"}
        except SystemExit as e:
            code, obj = 400, {"error": str(e)}
        self.send_json(code, obj)

    def route_skill(self, name, skill):
        target = agents_dir() / f"{name}.md"
        if not re.fullmatch(r"[\w-]+", name) or not target.is_file():
            return 404, {"error": "no such agent"}
        if not isinstance(skill, str) or skill not in {s["name"] for s in installed_skills()}:
            return 400, {"error": "not an installed skill"}
        add_skill(target, skill)
        return 200, read_agent(target)

    def route(self, project, root, rest, body):
        if rest == "/backlog":
            op = body.get("op")
            if op == "add":
                items = board.backlog_op(root, "add", text=body.get("text"))
                threading.Thread(target=estimate, args=(root, items[-1]["text"]), daemon=True).start()
                return 200, items
            kwargs = {"index": body.get("index")}
            if op == "edit":
                kwargs.update(text=body.get("text"), **({"points": body["points"]} if "points" in body else {}))
            if op == "move":
                kwargs["delta"] = body.get("delta")
            return 200, board.backlog_op(root, op, **kwargs)
        if rest == "/backlog/run":
            out = board.cmd_next(root, body.get("index"))
            (root / "jobs" / out["id"] / "feature.md").write_text(out["feature"] + "\n")
            spawn(project, root, out["id"], "start", f"/trevskills-scrum start {out['id']}")
            return 202, out
        job_id, action = board.check_id(rest.split("/")[2]), rest.split("/")[3]
        if action == "abort":
            stop(project, job_id)
            board.cmd_abort(root, job_id, bool(body.get("requeue")))
            return 200, {"id": job_id, "stage": "aborted"}
        jobs = json.loads((root / "board.json").read_text())["jobs"] if (root / "board.json").exists() else []
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job or job["stage"] != "needs-human" or running(project, job_id):
            return 409, {"error": "job isn't waiting on you, or is already running"}
        if action == "approve":
            note = " — Trevor confirms /trevskills-migrate has already been run for this job." if body.get("migrated") else ""
            spawn(project, root, job_id, action, f"/trevskills-scrum approve {job_id}{note}")
        else:
            feedback = board.clean(body.get("feedback") or "")
            if not feedback:
                raise SystemExit("feedback is empty")
            spawn(project, root, job_id, action, f"/trevskills-scrum rework {job_id} {json.dumps(feedback)}")
        return 202, {"id": job_id, "action": action}


def make_server(port):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    server = make_server(a.port)
    names = ", ".join(board.projects()) or "none yet (run /trevskills-scrum in a repo)"
    print(f"Trevskills Scrum: http://localhost:{a.port}  projects: {names}  claude: {CLAUDE}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
