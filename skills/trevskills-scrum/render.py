#!/usr/bin/env python3
"""The shared review render (lanes/review.md step 2): load each changed page once in headless Chrome and save what
scrum-review-ui and scrum-review-ux read instead of loading it themselves.

  python3 render.py <url> <out_dir> [--cookies <file>] <path>...
  python3 render.py --reap

For each path: <slug>-390.png and <slug>-1440.png (viewport-sized, 900 px tall), console errors and warnings appended
to out_dir/console.log as `<path> <width> <level>: <text>`, and out_dir/manifest.json
{"url", "cookies", "pages": [{"path", "final_url", "http_status", "status", "shots", "console_errors"}]}.
--cookies loads a Playwright storageState file's cookies first; no cookie name or value is ever written out.
Exit 0 when every page is ok, redirected or http_error; 1 on a timeout or when Chrome cannot run (manifest "error");
2 on a usage error. Every render first reaps (reap()) each scrum-render Chrome whose render.py is gone (ppid 1) and
its temp dir; --reap does only that, prints {"reaped": [<pids>]} and exits 0.
Images from https://res.cloudinary.com/ are kept on disk (cache_dir(): SCRUM_CLOUDINARY_CACHE, else
~/.claude/trevskills-scrum/cloudinary-cache), keyed by the sha1 of the URL like the app's e2e/helpers/cloudinaryCache.ts, so a
sweep downloads each mockup once; only a 200 is stored, never expired (a re-upload has a new /v<n>/ URL).
Stdlib only: Chrome DevTools Protocol over a small websocket client."""
import base64, glob, hashlib, json, os, re, select, shutil, signal, socket, struct, subprocess, sys, tempfile, time
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import buildlock  # a sibling: machine_hold and board_module for main()'s hold before Chrome starts (job 1227)

USAGE = "usage: render.py <url> <out_dir> [--cookies <file>] <path>...\n       render.py --reap"
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTHS = ((390, True), (1440, False))
HEIGHT = 900
LOAD_CAP = 60  # seconds per page load
BUDGET = 240  # seconds for the whole run, counted after main()'s hold (HOLD_CAP): both fit the 600 s Bash timeout
#              of lanes/review.md's and lanes/uisweep.md's render steps
HOLD_CAP = 300  # seconds main() waits at most while buildlock.machine_hold gives a reason, then renders anyway
HOLD_POLL = 5  # seconds between machine_hold reads while holding
QUIET = 0.5  # seconds with no request in flight, started or finished, before a loaded page is shot
SETTLE_CAP = 10  # seconds after the load event at most, so a request that never ends cannot stall the run
OUR_FILES = ("manifest.json", "console.log")
CLOUDINARY = "https://res.cloudinary.com/"
COOKIE_KEYS = ("name", "value", "url", "domain", "path", "secure", "httpOnly", "sameSite", "expires")


def find_chrome() -> str | None:
    """SCRUM_CHROME when set (None when it is not an executable), else Chrome.app, else the first Playwright chromium."""
    if (env := os.environ.get("SCRUM_CHROME")) is not None:
        return env if os.access(env, os.X_OK) else None
    if os.access(MAC_CHROME, os.X_OK):
        return MAC_CHROME
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "/opt/pw-browsers"
    return next(iter(sorted(glob.glob(f"{root}/chromium-*/chrome-linux/chrome"))), None)


def slug(path: str) -> str:
    """`root` for /, else the path with / turned into - and the leading - dropped."""
    return "root" if path == "/" else path.replace("/", "-").removeprefix("-")


# --- websocket client (RFC 6455): masked client frames, enough for one CDP connection.
def encode_frame(data: bytes, opcode: int = 1, mask: bool = True) -> bytes:
    n = len(data)
    head = bytes([0x80 | opcode])
    bit = 0x80 if mask else 0
    head += bytes([bit | n]) if n < 126 else bytes([bit | 126]) + struct.pack(">H", n) if n < 65536 else \
        bytes([bit | 127]) + struct.pack(">Q", n)
    if not mask:
        return head + data
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(data))


def decode_frame(buf: bytes):
    """(opcode, payload, bytes used) for the first whole frame in buf, else None."""
    if len(buf) < 2:
        return None
    opcode, n, pos = buf[0] & 0x0F, buf[1] & 0x7F, 2
    if n == 126:
        if len(buf) < 4:
            return None
        n, pos = struct.unpack(">H", buf[2:4])[0], 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n, pos = struct.unpack(">Q", buf[2:10])[0], 10
    key = None
    if buf[1] & 0x80:
        if len(buf) < pos + 4:
            return None
        key, pos = buf[pos:pos + 4], pos + 4
    if len(buf) < pos + n:
        return None
    data = buf[pos:pos + n]
    if key:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return opcode, data, pos + n


class WebSocket:
    def __init__(self, url: str):
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path or '/'} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            if not (chunk := self.sock.recv(4096)):
                raise OSError("websocket handshake closed")
            self.buf += chunk
        head, self.buf = self.buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("websocket handshake refused")

    def send(self, text: str):
        self.sock.sendall(encode_frame(text.encode()))

    def recv(self, timeout: float) -> str | None:
        """The next text message, or None when none arrives within timeout."""
        deadline, parts = time.monotonic() + timeout, []
        while True:
            if (f := decode_frame(self.buf)) is None:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([self.sock], [], [], left)[0]:
                    return None
                if not (chunk := self.sock.recv(1 << 16)):
                    raise OSError("websocket closed")
                self.buf += chunk
                continue
            opcode, data, used = f
            fin = self.buf[0] & 0x80
            self.buf = self.buf[used:]
            if opcode == 9:
                self.sock.sendall(encode_frame(data, 10))
            elif opcode == 8:
                raise OSError("websocket closed")
            elif opcode in (0, 1):
                parts.append(data)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def cache_dir() -> Path:
    return Path(os.environ.get("SCRUM_CLOUDINARY_CACHE") or Path.home() / ".claude" / "trevskills-scrum" / "cloudinary-cache")


def _write_atomic(file: Path, data: bytes):
    tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, file)


def cached_image(url: str, fetch=None) -> tuple[bytes, str] | None:
    """(body, content-type) for a res.cloudinary.com url from the disk cache, downloading and storing it on a miss.
    None when the download fails or is not a 200 (nothing stored; the browser then fetches it itself)."""
    base = cache_dir() / hashlib.sha1(url.encode()).hexdigest()
    try:
        return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".json").read_text())["contentType"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        if fetch:
            body, ctype = fetch(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "scrum-render"})
            with urllib.request.urlopen(req, timeout=20) as r:
                body, ctype = (r.read(), r.headers.get("content-type", "")) if r.status == 200 else (None, "")
    except (OSError, ValueError):
        return None
    if body is None:
        return None
    try:  # body first, meta last: a reader that sees the meta sees a whole body
        base.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(base.with_suffix(".body"), body)
        _write_atomic(base.with_suffix(".json"), json.dumps({"url": url, "status": 200, "contentType": ctype}).encode())
    except OSError:
        pass  # a full disk costs a re-download, never a failed render
    return body, ctype


class CDP:
    """One page target: call() waits for its reply and queues the events that arrive meanwhile."""

    def __init__(self, ws: WebSocket):
        self.ws, self.n, self.events = ws, 0, deque()

    def _paused(self, msg: dict) -> bool:
        """Answer a Fetch.requestPaused for a Cloudinary image from the disk cache; True when msg was one."""
        if msg.get("method") != "Fetch.requestPaused":
            return False
        p = msg.get("params", {})
        got = cached_image(p.get("request", {}).get("url", "")) if p.get("request", {}).get("method") == "GET" else None
        self.n += 1  # fire and forget: the reply has an id no call() waits for
        if got:
            body, ctype = got
            cmd = ("Fetch.fulfillRequest", {"requestId": p["requestId"], "responseCode": 200,
                                            "responseHeaders": [{"name": "Content-Type", "value": ctype}],
                                            "body": base64.b64encode(body).decode()})
        else:
            cmd = ("Fetch.continueRequest", {"requestId": p["requestId"]})
        self.ws.send(json.dumps({"id": self.n, "method": cmd[0], "params": cmd[1]}))
        return True

    def call(self, method: str, params: dict | None = None, timeout: float = 30):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            if (raw := self.ws.recv(left)) is None:
                break
            msg = json.loads(raw)
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method} failed")  # never the message: it can echo params (cookies)
                return msg.get("result", {})
            if "method" in msg and not self._paused(msg):
                self.events.append(msg)
        raise TimeoutError(f"{method} timed out")

    def event(self, timeout: float):
        if self.events:
            return self.events.popleft()
        raw = self.ws.recv(max(timeout, 0))
        msg = json.loads(raw) if raw else None
        return None if msg and self._paused(msg) else msg


def _free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            if (port := s.getsockname()[1]) != 9222:
                return port


def _start_chrome(chrome: str, tmp: str):
    """(process, page websocket URL); raises OSError when Chrome does not come up within 20 s."""
    port = _free_port()
    proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}",
                             f"--user-data-dir={tmp}/profile", "--no-first-run", "--no-default-browser-check",
                             "--disable-gpu", "--hide-scrollbars", "--disable-extensions", "--mute-audio",
                             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return proc, None
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                pages = [t for t in json.load(r) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return proc, pages[0]["webSocketDebuggerUrl"]
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    return proc, None


def _kill(proc):
    """Stop Chrome's whole process group: SIGTERM, up to 5 s on the leader, then always SIGKILL, so a helper that
    ignores SIGTERM or outlives the leader never lives on (job 1451)."""
    if proc is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass


def _signal(pid: int, pgid: int, sig: int):
    """Send sig to pid's group when pid leads it, else to pid alone; a process already gone is ignored."""
    try:
        if pgid == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _gone(pid: int, within: float) -> bool:
    deadline = time.monotonic() + within
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def reap(tmp: str | None = None, ps_out: str | None = None) -> list[int]:
    """Stop every scrum-render Chrome whose render.py is gone (ppid 1, its --user-data-dir under tmp) and remove that
    render's temp dir; return the pids reaped. A Chrome with a live parent, and its helpers, are never signalled."""
    tmp = tempfile.gettempdir() if tmp is None else tmp
    if ps_out is None:
        try:
            ps_out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,command="], capture_output=True, text=True,
                                    timeout=5, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    flag = re.compile(r"(?:^|\s)--user-data-dir=" + re.escape(tmp.rstrip("/"))
                      + r"/(scrum-render-[^/\s]+)/profile(?:\s|$)")
    found = []
    for line in ps_out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4 or not all(p.isdigit() for p in parts[:3]):
            continue
        pid, ppid, pgid = map(int, parts[:3])
        if ppid == 1 and pid > 1 and (m := flag.search(parts[3])):
            found.append((pid, pgid, os.path.join(tmp, m.group(1))))
    for pid, pgid, _ in found:
        _signal(pid, pgid, signal.SIGTERM)
    for pid, pgid, run_dir in found:
        _gone(pid, 5)
        _signal(pid, pgid, signal.SIGKILL)
        shutil.rmtree(run_dir, ignore_errors=True)
    return [pid for pid, _, _ in found]


def _load_cookies(cdp: CDP, file: Path) -> str:
    """Set the storageState file's cookies; return the manifest note (never a cookie name or value)."""
    try:
        cookies = json.loads(file.read_text(encoding="utf-8"))["cookies"]
        cookies = [{k: c[k] for k in COOKIE_KEYS if k in c and not (k == "expires" and c[k] == -1)} for c in cookies]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return f"missing: {file}"
    try:
        cdp.call("Network.setCookies", {"cookies": cookies})
    except (RuntimeError, TimeoutError):
        return f"rejected: {file}"
    return f"loaded {len(cookies)}"


def _text(params: dict) -> str:
    out = []
    for a in params.get("args", []):
        v = a.get("value", a.get("description", a.get("type", "")))
        out.append(v if isinstance(v, str) else json.dumps(v))
    return " ".join(out)


BUSY_JS = """[...document.querySelectorAll('[class*=skeleton i],.animate-pulse')].some(e => e.getClientRects().length > 0)
|| !!document.querySelector('[aria-busy=true]') || [...document.querySelectorAll('[role=status]')].some(
  e => /^(loading(\\.\\.\\.)?)?$/i.test(e.textContent.trim()) && e.getClientRects().length > 0
) || [...document.querySelectorAll('body *')].some(
  e => /^loading(\\.\\.\\.)?$/i.test([...e.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join('').trim())
       && e.getClientRects().length > 0)"""


def _busy(cdp: CDP) -> bool:
    """True while the page shows a loading indicator; False when it cannot be read."""
    try:
        r = cdp.call("Runtime.evaluate", {"expression": BUSY_JS, "returnByValue": True}, timeout=5)
    except (RuntimeError, TimeoutError):
        return False
    return r.get("result", {}).get("value") is True


def _load(cdp: CDP, url: str, path: str, width: int, mobile: bool, deadline: float, log) -> dict:
    """Load url at width; {"status", "http_status", "final_url", "errors"}. Console lines go to log."""
    cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": HEIGHT, "deviceScaleFactor": 1,
                                                   "mobile": mobile})
    cdp.events.clear()
    nav = cdp.call("Page.navigate", {"url": url})
    frame, res = nav.get("frameId"), {"status": "ok", "http_status": None, "final_url": None, "errors": 0}
    end, loaded = min(time.monotonic() + LOAD_CAP, deadline), None
    inflight, last = set(), time.monotonic()  # requestIds in flight; time of the last network change

    def handle(ev):
        nonlocal loaded, last
        m, p = ev.get("method"), ev.get("params", {})
        line = None
        if m == "Page.loadEventFired" and loaded is None:
            loaded = last = time.monotonic()
        elif m == "Network.requestWillBeSent":
            inflight.add(p.get("requestId"))
            last = time.monotonic()
        elif m in ("Network.loadingFinished", "Network.loadingFailed"):
            inflight.discard(p.get("requestId"))
            last = time.monotonic()
        elif m == "Network.responseReceived" and p.get("type") == "Document" and p.get("frameId") == frame:
            res["http_status"] = p.get("response", {}).get("status")
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning"):
            line = (p["type"], _text(p))
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            line = ("error", d.get("exception", {}).get("description") or d.get("text", ""))
        elif m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            line = ("error", p["entry"].get("text", ""))
        if line:
            res["errors"] += line[0] == "error"
            log.write(f"{path} {width} {line[0]}: {' '.join(line[1].split())}\n")

    while True:
        now = time.monotonic()
        stop = end if loaded is None else min(loaded + SETTLE_CAP, deadline,
                                              loaded + SETTLE_CAP if inflight else last + QUIET)
        if now >= stop:
            # ponytail: an indicator at LOAD_CAP is shot anyway (status ok)
            if loaded is None or now >= end or not _busy(cdp):
                break
            stop = min(now + 0.25, end)  # poll again in about 250 ms
        if (ev := cdp.event(stop - now)) is not None:
            handle(ev)
    while cdp.events:  # events queued during the last _busy call, e.g. the console line logged as it cleared
        handle(cdp.events.popleft())
    if loaded is None:
        res["status"] = "timeout"
        return res
    res["final_url"] = cdp.call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True},
                                timeout=10).get("result", {}).get("value")
    if res["http_status"] is not None and res["http_status"] >= 400:
        res["status"] = "http_error"
    elif _route(res["final_url"] or "") != _route(path):
        res["status"] = "redirected"
    return res


def _route(url: str) -> tuple[str, str]:
    """(path without a trailing /, query) of url; the fragment is ignored."""
    u = urlparse(url)
    return u.path.rstrip("/") or "/", u.query


RANK = {"ok": 0, "redirected": 1, "http_error": 2, "timeout": 3}


def render(url: str, out_dir: Path, paths: list[str], cookies: Path | None = None) -> dict:
    """Render every path at 390 and 1440 px into out_dir (deleted and re-created first); return the manifest."""
    start, url, out_dir = time.monotonic(), url.rstrip("/"), Path(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    manifest = {"url": url, "cookies": None, "pages": []}
    tmp, proc, ws = tempfile.mkdtemp(prefix="scrum-render-"), None, None
    try:
        if not (chrome := find_chrome()):
            where = os.environ.get("SCRUM_CHROME")
            manifest["error"] = f"no Chrome found at {where}" if where is not None else "no Chrome found"
            return manifest
        try:
            proc, ws_url = _start_chrome(chrome, tmp)
        except OSError as e:
            manifest["error"] = f"Chrome failed to start: {e.strerror or e}"
            return manifest
        if not ws_url:
            manifest["error"] = "Chrome failed to start: no DevTools page within 20 s"
            return manifest
        try:
            ws = WebSocket(ws_url)
            cdp = CDP(ws)
            for domain in ("Page", "Runtime", "Log", "Network"):
                cdp.call(f"{domain}.enable")
            cdp.call("Fetch.enable", {"patterns": [{"urlPattern": CLOUDINARY + "*", "requestStage": "Request"}]})
        except (OSError, RuntimeError, TimeoutError) as e:
            manifest["error"] = f"cannot connect to the CDP websocket: {e}"
            return manifest
        if cookies is not None:
            manifest["cookies"] = _load_cookies(cdp, Path(cookies))
        deadline = start + BUDGET
        with open(out_dir / "console.log", "a", encoding="utf-8") as log:
            for path in paths:
                page = {"path": path, "final_url": None, "http_status": None, "status": "ok", "shots": [],
                        "console_errors": 0}
                for width, mobile in WIDTHS:
                    if time.monotonic() >= deadline:
                        page["status"] = "timeout"
                        break
                    try:
                        res = _load(cdp, url + path, path, width, mobile, deadline, log)
                        if res["status"] != "timeout":
                            shot = cdp.call("Page.captureScreenshot", {"format": "png"})["data"]
                            name = f"{slug(path)}-{width}.png"
                            (out_dir / name).write_bytes(base64.b64decode(shot))
                            page["shots"].append(name)
                    except (TimeoutError, RuntimeError, KeyError, ValueError):
                        res = {"status": "timeout", "errors": 0, "http_status": None, "final_url": None}
                    log.flush()
                    page["console_errors"] += res["errors"]
                    page["final_url"] = res["final_url"] or page["final_url"]
                    page["http_status"] = res["http_status"] or page["http_status"]
                    page["status"] = max(page["status"], res["status"], key=RANK.get)
                manifest["pages"].append(page)
        return manifest
    except OSError as e:  # the websocket dropped mid-run
        manifest["error"] = f"cannot connect to the CDP websocket: {e}"
        return manifest
    finally:
        if ws:
            ws.close()
        _kill(proc)
        shutil.rmtree(tmp, ignore_errors=True)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str]) -> int:
    if list(argv) == ["--reap"]:
        print(json.dumps({"reaped": reap()}))
        return 0
    args, cookies = list(argv), None
    if "--cookies" in args:
        i = args.index("--cookies")
        if i + 1 >= len(args):
            print(USAGE, file=sys.stderr)
            return 2
        cookies = Path(args.pop(i + 1))
        args.pop(i)
    if len(args) < 3 or not all(p.startswith("/") for p in args[2:]) or args[0].startswith("-"):
        print(USAGE, file=sys.stderr)
        return 2
    url, out_dir, paths = args[0], Path(args[1]), args[2:]
    if out_dir.exists() and (not out_dir.is_dir() or any(
            not p.is_file() or not (p.name in OUR_FILES or p.suffix == ".png") for p in out_dir.iterdir())):
        print(f"render.py: {out_dir} holds files render.py did not write; refusing to delete it", file=sys.stderr)
        return 2
    reap()  # a Chrome a dead render.py left behind (job 1451)
    board = buildlock.board_module()  # a hot machine holds Chrome's start (job 1227); BUDGET counts after it
    why, cap = buildlock.machine_hold(board), time.monotonic() + HOLD_CAP
    if why:
        print(f"render.py: holding for the machine: {why}", file=sys.stderr, flush=True)
    while why and time.monotonic() < cap:
        time.sleep(HOLD_POLL)
        why = buildlock.machine_hold(board)
    olds = {sig: signal.signal(sig, lambda *_: sys.exit(1))  # run the finally that kills Chrome
            for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        manifest = render(url, out_dir, paths, cookies)
    finally:
        for sig, old in olds.items():
            signal.signal(sig, old)
    print(json.dumps({"pages": [{"path": p["path"], "status": p["status"]} for p in manifest["pages"]],
                      "error": manifest.get("error")}))
    return 0 if "error" not in manifest and all(p["status"] != "timeout" for p in manifest["pages"]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
