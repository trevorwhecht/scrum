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
from urllib.parse import unquote, urlparse

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
            m = re.fullmatch(r"/api/p/(.+?)(/backlog(?:/run)?|/jobs/[^/]+/(?:approve|rework|abort))", urlparse(self.path).path)
            root = m and scrum_dir(unquote(m.group(1)))
            code, obj = self.route(unquote(m.group(1)), root, m.group(2), body if isinstance(body, dict) else {}) \
                if root else (404, {"error": "no such project or endpoint"})
        except ValueError:
            code, obj = 400, {"error": "body must be JSON"}
        except SystemExit as e:
            code, obj = 400, {"error": str(e)}
        self.send_json(code, obj)

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
