import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def run(scenario):
    """Run dashboard.html's getJson block (lastGood .. single) in node with a stubbed fetch, then `scenario`; return its JSON.
    `sent` holds each fetch's [url, If-None-Match or null]; each reply is called with the fetch's opts."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    start = text.index("const lastGood = {}, etags = {};")
    block = text[start:text.index("\n", text.index("const single = "))]
    script = f"let replies = [], sent = [];\nconst fetch = (url, opts) => (sent.push([url, opts?.headers?.['If-None-Match'] ?? null]), replies.shift()(opts));\n{block}\n(async () => {{ {scenario} }})();"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


OK = 'v => () => Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(v)})'


class LastGood(unittest.TestCase):
    """Job 424: a dropped request on a busy serve.py repeats the last good body, so columns never blank to 0."""

    def test_failure_repeats_last_good_body(self):
        got = run(f"""
const ok = {OK};
replies = [ok({{jobs: [1, 2]}}), () => Promise.reject(new TypeError("reset")),
           () => Promise.resolve({{ok: false, status: 503}})];
const a = await getJson("b", {{jobs: []}});
const b = await getJson("b", {{jobs: []}});
const c = await getJson("b", {{jobs: []}});
console.log(JSON.stringify([a, b, c, missed]));""")
        self.assertEqual(got, [{"jobs": [1, 2]}, {"jobs": [1, 2]}, {"jobs": [1, 2]}, 2])

    def test_failure_with_no_history_gives_fallback(self):
        got = run("""replies = [() => Promise.reject(new TypeError("reset"))];
console.log(JSON.stringify([await getJson("r", null), missed]));""")
        self.assertEqual(got, [None, 1])

    def test_404_still_means_missing_and_forgets(self):
        got = run(f"""
const ok = {OK}, nf = () => Promise.resolve({{ok: false, status: 404}});
replies = [ok([1]), nf, () => Promise.reject(new TypeError("reset"))];
const a = await getJson("x", [], "STALE");
const b = await getJson("x", [], "STALE");
const c = await getJson("x", [], "STALE");
console.log(JSON.stringify([a, b, c, missed]));""")
        self.assertEqual(got, [[1], "STALE", [], 1])

    # Job 463: a 200 with an ETag is revalidated next time; a 304 repeats the stored body and is not a miss.
    TAGGED = ('(v, tag) => () => Promise.resolve({ok: true, status: 200, headers: {get: h => h === "ETag" ? tag : null}, '
              'json: () => Promise.resolve(v)})')
    NOT_MODIFIED = '() => Promise.resolve({ok: false, status: 304, headers: {get: () => null}, json: () => Promise.reject()})'

    def test_304_returns_last_good_body(self):
        got = run(f"""
const tagged = {self.TAGGED}, nm = {self.NOT_MODIFIED};
replies = [tagged({{jobs: [7]}}, '"abc"'), nm];
const a = await getJson("b", {{jobs: []}});
const b = await getJson("b", {{jobs: []}});
console.log(JSON.stringify([a, b, missed, sent]));""")
        self.assertEqual(got, [{"jobs": [7]}, {"jobs": [7]}, 0, [["b", None], ["b", '"abc"']]])

    def test_no_conditional_header_without_body(self):
        got = run(f"""
const tagged = {self.TAGGED}, ok = {OK};
replies = [() => Promise.reject(new TypeError("reset")), ok([1]), ok([2]), tagged([3], '"t3"'),
           () => Promise.resolve({{ok: false, status: 503}}), tagged([4], '"t4"')];
for (let i = 0; i < 6; i++) await getJson("u", []);
console.log(JSON.stringify(sent.map(s => s[1])));""")
        self.assertEqual(got, [None, None, None, None, '"t3"', '"t3"'])

    def test_hung_request_times_out_to_last_good(self):
        # Job 501: a request that never settles is aborted by its timeout signal and counts as a miss.
        got = run(f"""
const ok = {OK}, seen = [];
const hang = opts => new Promise((_, rej) => {{
  const fail = () => rej(new DOMException("signal timed out", "TimeoutError"));
  if (opts?.signal?.aborted) fail(); else opts?.signal?.addEventListener("abort", fail);
}});
AbortSignal.timeout = ms => (seen.push(ms), AbortSignal.abort());
replies = [ok({{jobs: [5]}}), hang];
const a = await getJson("h", {{jobs: []}});
const b = await getJson("h", {{jobs: []}});
console.log(JSON.stringify([a, b, missed, seen]));""")
        self.assertEqual(got, [{"jobs": [5]}, {"jobs": [5]}, 1, [15000, 15000]])

    def test_poll_fetches_are_timed(self):
        text = DASHBOARD.read_text()
        start = text.index("async function poll()")
        body = text[start:text.index("\n}\n", start)]
        self.assertNotRegex(body, r"(?<![\w.])fetch\(")
        self.assertIn('timed("api/projects"', body)

    def test_404_forgets_etag(self):
        got = run(f"""
const tagged = {self.TAGGED}, nf = () => Promise.resolve({{ok: false, status: 404}});
replies = [tagged([1], '"one"'), nf, tagged([2], '"two"')];
const a = await getJson("x", [], "STALE");
const b = await getJson("x", [], "STALE");
const c = await getJson("x", [], "STALE");
console.log(JSON.stringify([a, b, c, sent.map(s => s[1])]));""")
        self.assertEqual(got, [[1], "STALE", [2], [None, '"one"', None]])


class RouteText(unittest.TestCase):
    """Job 534: a failed routing.log fetch forgets its ETag so the next poll refetches instead of getting a 304."""
    T = ('(b, tag) => () => Promise.resolve({ok: true, status: 200, headers: {get: h => h === "ETag" ? tag : null}, '
         'text: () => Promise.resolve(b)})')
    NM = '() => Promise.resolve({ok: false, status: 304, headers: {get: () => null}})'

    def test_304_keeps_previous_text(self):
        got = run(f"""
const t = {self.T}, nm = {self.NM};
replies = [t("log1", '"a"'), nm];
const a = await getText("u", undefined);
const b = await getText("u", a);
console.log(JSON.stringify([a, b, sent]));""")
        self.assertEqual(got, ["log1", "log1", [["u", None], ["u", '"a"']]])

    def test_failure_forgets_etag(self):
        got = run(f"""
const t = {self.T};
replies = [t("old", '"tag"'), () => Promise.reject(new TypeError("reset")), t("new", '"t2"')];
const a = await getText("u", undefined);
const b = await getText("u", a);
const c = await getText("u", b);
console.log(JSON.stringify([a, b, c, sent.map(s => s[1])]));""")
        self.assertEqual(got, ["old", "", "new", [None, '"tag"', None]])

    def test_404_forgets_etag(self):
        got = run(f"""
const t = {self.T};
replies = [t("old", '"tag"'), () => Promise.resolve({{ok: false, status: 404}}), t("new", '"t2"')];
const a = await getText("u", undefined);
const b = await getText("u", a);
const c = await getText("u", b);
console.log(JSON.stringify([a, b, c, sent.map(s => s[1])]));""")
        self.assertEqual(got, ["old", "", "new", [None, '"tag"', None]])


class SingleFlight(unittest.TestCase):
    def test_overlapping_ticks_share_one_run(self):
        got = run("""
let calls = 0, release;
const tick = single(() => { calls++; return new Promise(r => { release = r; }); });
tick(); tick(); tick();
release(); await new Promise(r => setTimeout(r, 0));
tick(); release(); await new Promise(r => setTimeout(r, 0));
console.log(JSON.stringify(calls));""")
        self.assertEqual(got, 2)

    def test_timers_are_single_flight(self):
        text = DASHBOARD.read_text()
        self.assertIn("setInterval(single(poll), 2000)", text)
        self.assertIn("setInterval(single(loadRouting), 60000)", text)


if __name__ == "__main__":
    unittest.main()
