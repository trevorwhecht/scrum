import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def node_eval(fn, args):
    """Run dashboard.html's esc and `fn` in node over each argument; return the list of results."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    start = text.index("const esc = ")
    esc = text[start:text.index("\n", start)]
    start = text.index(f"function {fn}(")
    body = text[start:text.index("\n}\n", start) + 2]
    script = f"{esc}\n{body}\nconsole.log(JSON.stringify({json.dumps(args)}.map(a => {fn}(a))));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class RouteTags(unittest.TestCase):
    def test_one_tag_per_line_in_file_order(self):
        log = ('{"ts": "t", "role": "scrum-builder", "runner": "local", "model": "qwen2.5-coder:7b", "duration_s": 12.5, "outcome": "invalid-artifact"}\n'
               '{"ts": "t", "role": "scrum-builder", "runner": "cloud", "model": null, "duration_s": 300.0, "outcome": "fallback"}\n'
               '{"role": "codex-review", "runner": "skip"}\n')
        self.assertEqual(node_eval("routeTags", [log]), [
            '<span class="row">'
            '<span class="chip rt local" title="qwen2.5-coder:7b · 12.5s · invalid-artifact">builder local</span>'
            '<span class="chip rt cloud" title="— · 300s · fallback">builder cloud</span>'
            '<span class="chip rt" title="— · —s · —">codex-review skip</span>'
            '</span>'])

    def test_empty_or_malformed_log_renders_nothing(self):
        self.assertEqual(node_eval("routeTags", ["", "not json\n", "\n\n", "null\n42\n[]\n", '{"role": "x"}\n{"runner": "local"}\n']),
                         ["", "", "", "", ""])

    def test_skips_bad_lines_between_good_ones(self):
        log = 'garbage\n\n{"role": "estimator", "runner": "cloud", "model": "sonnet", "duration_s": 4.2, "outcome": "ok"}\n{"runner": "local"}\n'
        self.assertEqual(node_eval("routeTags", [log]),
                         ['<span class="row"><span class="chip rt cloud" title="sonnet · 4.2s · ok">estimator cloud</span></span>'])

    def test_values_are_escaped(self):
        log = json.dumps({"role": "<script>alert(1)</script>", "runner": '"><img src=x>', "model": "a&b", "duration_s": 1,
                          "outcome": "<b>"}) + "\n"
        self.assertEqual(node_eval("routeTags", [log]), [
            '<span class="row"><span class="chip rt" title="a&amp;b · 1s · &lt;b&gt;">'
            '&lt;script&gt;alert(1)&lt;/script&gt; &quot;&gt;&lt;img src=x&gt;</span></span>'])


class RoutingText(unittest.TestCase):
    def test_readout(self):
        self.assertEqual(node_eval("routingText", [
            {"codex": {"5h": 42, "weekly": 61.4}, "ollama": "up"},
            {"codex": {"5h": None, "weekly": None}, "ollama": "down"},
            {"ollama": "up"}]), [
            "Codex 5h 42% · wk 61% · Ollama up",
            "Codex 5h — · wk — · Ollama down",
            "Codex 5h — · wk — · Ollama up"])


if __name__ == "__main__":
    unittest.main()
