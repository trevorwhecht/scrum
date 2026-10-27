"""The checkout alert line lists every project's board.checkoutAlert, one per line, and hides when all are null."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD


def render(boards):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    fn = text[text.index("function renderCheckoutAlert("):text.index("async function poll()")]
    script = (f"const el = {{innerHTML: '', hidden: true}};\nconst $ = id => id === 'checkoutAlert' ? el : null;\n{esc}\n{fn}\n"
              f"renderCheckoutAlert({json.dumps(boards)});\nconsole.log(JSON.stringify(el));")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class CheckoutAlert(unittest.TestCase):
    def test_two_alerts_two_lines(self):
        el = render([{"jobs": [], "checkoutAlert": "a <b> main checkout has 1 commit(s)"}, {"jobs": [], "checkoutAlert": None},
                     {"jobs": [], "checkoutAlert": "9-x merged, not live: fast-forward failed."}])
        self.assertEqual(el, {"innerHTML": "a &lt;b&gt; main checkout has 1 commit(s)<br>9-x merged, not live: fast-forward failed.",
                              "hidden": False})

    def test_all_null_hidden(self):
        self.assertEqual(render([{"jobs": [], "checkoutAlert": None}, {"jobs": []}]), {"innerHTML": "", "hidden": True})

    def test_element_sits_between_header_and_board(self):
        self.assertIn('</header>\n<p class="error" id="checkoutAlert" role="alert" hidden></p>\n<main id="board">',
                      DASHBOARD.read_text())


if __name__ == "__main__":
    unittest.main()
