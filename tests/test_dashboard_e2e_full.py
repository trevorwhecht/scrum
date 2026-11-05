"""The #e2eFull header line shows each project's board.e2eFull and hides when none has one."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD


def render(boards, names=("a", "b"), now=10_000_000):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    ago = text[text.index("const ago = "):text.index("// Also re-runs statusLine")]
    fn = text[text.index("const E2E_FULL_STALE"):text.index("async function poll()")]
    script = (f"const el = {{innerHTML: '', hidden: true}};\nconst $ = id => id === 'e2eFull' ? el : null;\n"
              f"Date.now = () => {now * 1000};\n{esc}\n{ago}\n{fn}\n"
              f"renderE2eFull({json.dumps(boards)}, {json.dumps(list(names))});\nconsole.log(JSON.stringify(el));")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


NOW = 10_000_000


class E2eFull(unittest.TestCase):
    def test_all_null_hidden(self):
        self.assertEqual(render([{"e2eFull": None}, {}]), {"innerHTML": "", "hidden": True})

    def test_pass_fail_running_lines(self):
        one = render([{"e2eFull": {"at": NOW - 3 * 3600, "head": "1a2b3c4d5e", "result": "pass"}}])
        self.assertEqual(one, {"innerHTML": "<span>E2E main pass 1a2b3c4 3h ago</span>", "hidden": False})
        two = render([{"e2eFull": {"at": NOW - 60, "head": "ffffffff", "result": "fail"}},
                      {"e2eFull": {"at": NOW - 60, "head": "1234567890", "result": "running"}}])
        self.assertEqual(two["innerHTML"], '<span class="danger">a E2E main fail fffffff 1m ago</span>'
                         ' · <span>b E2E main running 1234567</span>')

    def test_escapes_and_missing_fields(self):
        el = render([{"e2eFull": {"result": "pass"}}, {"e2eFull": {"at": NOW, "head": "<b>", "result": "error"}}],
                    names=["<i>", "b"])
        self.assertEqual(el["innerHTML"], '<span>&lt;i&gt; E2E main pass — —</span>'
                         ' · <span class="danger">b E2E main error &lt;b&gt; 0s ago</span>')

    def test_stale_running(self):
        el = render([{"e2eFull": {"at": NOW - 7200, "head": "abcdefgh", "result": "running"}}])
        self.assertEqual(el["innerHTML"], "<span>E2E main stale abcdefg 2h ago</span>")


if __name__ == "__main__":
    unittest.main()
