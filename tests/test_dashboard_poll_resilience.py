import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def run(scenario):
    """Run dashboard.html's getJson block (lastGood .. single) in node with a stubbed fetch, then `scenario`; return its JSON."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    start = text.index("const lastGood = {};")
    block = text[start:text.index("\n", text.index("const single = "))]
    script = f"let replies = [];\nconst fetch = () => replies.shift()();\n{block}\n(async () => {{ {scenario} }})();"
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
