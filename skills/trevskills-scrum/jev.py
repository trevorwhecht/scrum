"""TypeSafe Jev client: one POST per call, noul / score / choice questions. Stdlib only.

Every failure raises JevError, so a caller can catch one thing and carry on.
Key: $TYPESAFE_API_KEY, else the macOS Keychain item TypeSafe/typesafe.
"""
import http.client, json, os, subprocess, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT = 90  # seconds per call, retries included


class JevError(Exception):
    pass


def api_key():
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        try:
            key = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "TypeSafe", "-a", "typesafe", "-w"],
                                 capture_output=True, text=True).stdout.strip()
        except OSError:  # no `security` binary, as on a cloud box
            key = ""
    if not key:
        raise JevError("no TYPESAFE_API_KEY and no Keychain item TypeSafe/typesafe")
    return key


def ask(state, questions, timeout=TIMEOUT, key=None):
    """Send one request; return the response's `answers` dict."""
    key = key or api_key()
    fail = lambda msg: JevError(msg.replace(key, "***"))
    deadline = time.monotonic() + timeout
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=max(deadline - time.monotonic(), 0.001)) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            try:
                detail = e.read()[:300].decode(errors="replace")
            except Exception:
                detail = ""
            finally:
                e.close()
            msg = f"HTTP {e.code} {e.reason} {detail}".strip()
            if e.code not in (429, 529) or attempt == 3:
                raise fail(msg) from None
            if time.monotonic() + 2 ** attempt >= deadline:
                raise fail(f"{msg} (no time left in the {timeout}s budget to retry)") from None
            time.sleep(2 ** attempt)
        except TimeoutError:  # socket.timeout is an alias
            raise JevError(f"timed out after {timeout}s") from None
        except urllib.error.URLError as e:
            raise fail(f"network error: {e.reason}") from None
        except (http.client.HTTPException, OSError) as e:  # a failed r.read(); not retried
            raise fail(f"read failed: {type(e).__name__}: {e}") from None
    try:
        answers = json.loads(raw)["answers"]
    except (ValueError, KeyError, TypeError):
        raise fail(f"response has no answers: {raw[:300].decode(errors='replace')}") from None
    if not isinstance(answers, dict):
        raise JevError("response answers is not an object")
    return answers


def _number(answer, field, high):
    v = answer.get(field) if isinstance(answer, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= high:
        raise JevError(f"{field} answer is not a number in [0, {high}]")
    return float(v)


def parse_noul(answer):
    return _number(answer, "noul", 1)


def _one(state, question, timeout):
    answer = ask(state, {"q": question}, timeout).get("q")
    if not isinstance(answer, dict):
        raise JevError("no answer for question q")
    return answer


def noul(state, instructions, timeout=TIMEOUT):
    answer = _one(state, {"type": "noul", "instructions": instructions}, timeout)
    return parse_noul(answer), answer


def score(state, instructions, levels, timeout=TIMEOUT):
    if len(levels) < 2:
        raise JevError("score needs at least 2 levels")
    answer = _one(state, {"type": "score", "instructions": instructions, "criteria": levels}, timeout)
    return _number(answer, "score", len(levels) - 1), answer


def choice(state, instructions, options, timeout=TIMEOUT):
    if len(options) < 2:
        raise JevError("choice needs at least 2 options")
    answer = _one(state, {"type": "choice", "instructions": instructions, "criteria": options}, timeout)
    picked = answer.get("choice")
    if not isinstance(picked, str) or picked not in options:
        raise JevError("choice answer is not one of the options")
    return picked, answer


def rank(query, items, instruction, key=None, batch=20, max_chars=1500):
    """Score each item with one noul question (`instruction.format(i=i)`), `batch` items per request, 4 requests at
    a time. Returns scores in input order; raises JevError on any failure."""
    if not items:
        return []
    key = key or api_key()

    def one(chunk):
        answers = ask({"query": query, "items": {str(i): t[:max_chars] for i, t in enumerate(chunk)}},
                      {f"q{i}": {"type": "noul", "instructions": instruction.format(i=i)} for i in range(len(chunk))},
                      key=key)
        return [parse_noul(answers.get(f"q{i}")) for i in range(len(chunk))]
    with ThreadPoolExecutor(4) as pool:
        return [s for b in pool.map(one, [items[i:i + batch] for i in range(0, len(items), batch)]) for s in b]
