#!/usr/bin/env python3
"""Dashboard server for /trevskills-scrum: serves the project's scrum/ folder plus a small JSON API, so the
dashboard's buttons can edit the backlog and start Claude runs (approve, rework, run now).

  cd <project main checkout> && python3 ~/.claude/skills/trevskills-scrum/serve.py      → http://localhost:8765

Binds 127.0.0.1 only. Every request must carry a localhost Host header (blocks DNS rebinding), and every write
must be a JSON POST from no origin or a localhost origin; a cross-site page can't send that without a CORS
preflight, which this server never approves.
"""
import argparse, json, os, re, signal, subprocess, sys, threading, time
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board  # noqa: E402

CLAUDE = os.environ.get("SCRUM_CLAUDE", "claude")  # tests point this at a stub
LOCAL = {"localhost", "127.0.0.1"}
RUNS, RUNS_LOCK = {}, threading.Lock()  # job id -> {"action", "started", "proc", "log"}
ESTIMATE_PROMPT = """You are estimating one backlog item for the repository in the current directory.
Look only at what you need (CLAUDE.md, the files the item would touch). Do not change anything.
Reply with ONLY one JSON object: {{"points": <one of 1, 2, 3, 5, 8, 13>, "why": "<one short sentence>"}}
Scale: 1 trivial tweak · 2 one small file · 3 a few files · 5 several layers (API + UI) · 8 large or risky · 13 too big, should be split.
Item: {text}"""


def running(job_id):
    with RUNS_LOCK:
        run = RUNS.get(job_id)
        return bool(run and run["proc"].poll() is None)


def stop(job_id):
    """Terminate a dashboard-started run and everything it spawned (it runs in its own process group)."""
    with RUNS_LOCK:
        run = RUNS.get(job_id)
    if run and run["proc"].poll() is None:
        try:
            os.killpg(run["proc"].pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def spawn(root, job_id, action, prompt):
    """Start `claude -p <prompt>` in the repo, detached, logging to scrum/runs/. The dashboard shows it as running."""
    logs = root / "runs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{datetime.now():%Y%m%d-%H%M%S}-{action}-{job_id}.log"
    with open(log, "w") as fh:
        proc = subprocess.Popen([CLAUDE, "-p", prompt, "--permission-mode", "acceptEdits"], cwd=root.parent,
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    with RUNS_LOCK:
        RUNS[job_id] = {"action": action, "started": time.time(), "proc": proc, "log": f"runs/{log.name}"}


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


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, root, **kwargs):
        self.root = root
        super().__init__(*args, directory=str(root), **kwargs)

    def log_message(self, *args):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def local_host(self):
        return urlparse("//" + (self.headers.get("Host") or "")).hostname in LOCAL

    def do_GET(self):
        if not self.local_host():
            return self.send_json(403, {"error": "forbidden host"})
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/dashboard.html")
            return self.end_headers()
        if self.path == "/api/backlog":
            return self.send_json(200, board.backlog_items(self.root))
        if self.path == "/api/runs":
            with RUNS_LOCK:
                return self.send_json(200, [{"id": k, "action": r["action"], "started": r["started"], "log": r["log"],
                                             "alive": r["proc"].poll() is None, "exit": r["proc"].poll()}
                                            for k, r in RUNS.items()])
        return super().do_GET()

    def do_POST(self):
        origin = self.headers.get("Origin")
        if (not self.local_host() or "application/json" not in (self.headers.get("Content-Type") or "")
                or (origin and urlparse(origin).hostname not in LOCAL)):
            return self.send_json(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            code, obj = self.route(body if isinstance(body, dict) else {})
        except ValueError:
            code, obj = 400, {"error": "body must be JSON"}
        except SystemExit as e:
            code, obj = 400, {"error": str(e)}
        self.send_json(code, obj)

    def route(self, body):
        root = self.root
        if self.path == "/api/backlog":
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
        if self.path == "/api/backlog/run":
            out = board.cmd_next(root, body.get("index"))
            (root / "jobs" / out["id"] / "feature.md").write_text(out["feature"] + "\n")
            spawn(root, out["id"], "start", f"/trevskills-scrum start {out['id']}")
            return 202, out
        if m := re.fullmatch(r"/api/jobs/([^/]+)/abort", self.path):
            job_id = board.check_id(m.group(1))
            stop(job_id)
            board.cmd_abort(root, job_id, bool(body.get("requeue")))
            return 200, {"id": job_id, "stage": "aborted"}
        if m := re.fullmatch(r"/api/jobs/([^/]+)/(approve|rework)", self.path):
            job_id, action = board.check_id(m.group(1)), m.group(2)
            jobs = json.loads((root / "board.json").read_text())["jobs"] if (root / "board.json").exists() else []
            job = next((j for j in jobs if j["id"] == job_id), None)
            if not job or job["stage"] != "needs-human" or running(job_id):
                return 409, {"error": "job isn't waiting on you, or is already running"}
            if action == "approve":
                note = " — Trevor confirms /trevskills-migrate has already been run for this job." if body.get("migrated") else ""
                spawn(root, job_id, action, f"/trevskills-scrum approve {job_id}{note}")
            else:
                feedback = board.clean(body.get("feedback") or "")
                if not feedback:
                    raise SystemExit("feedback is empty")
                spawn(root, job_id, action, f"/trevskills-scrum rework {job_id} {json.dumps(feedback)}")
            return 202, {"id": job_id, "action": action}
        return 404, {"error": "no such endpoint"}


def make_server(root, port):
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=Path(root).resolve()))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=Path("scrum"))
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    if not (a.dir / "board.json").exists() and not (a.dir / "backlog.md").exists():
        sys.exit(f"{a.dir.resolve()} has no board.json or backlog.md; run /trevskills-scrum in this repo first")
    server = make_server(a.dir, a.port)
    print(f"Scrum dashboard: http://localhost:{a.port}/dashboard.html  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
