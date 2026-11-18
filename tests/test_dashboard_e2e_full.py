"""The header #checksBtn ("Checks · N") counts the projects with a board.e2eFull or board.uiSweep record, turns red when
any row is bad, hides when none has one, and its #checks dialog lists one row per project (job 977)."""
import json, re, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD


def render(boards, names=("a", "b"), now=10_000_000, missing=False):
    """{"btn": {text, hidden, danger}, "rows": innerHTML of #checksList} after renderE2eFull. missing: no elements."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    ago = text[text.index("const ago = "):text.index("// Also re-runs statusLine")]
    fn = text[text.index("const E2E_FULL_STALE"):text.index("async function poll()")]
    script = (
        "const cls = new Set();\n"
        "const btn = {textContent: '', hidden: true, classList: {toggle: (c, on) => on ? cls.add(c) : cls.delete(c)}};\n"
        "const list = {innerHTML: ''};\n"
        f"const $ = id => {'null' if missing else '({checksBtn: btn, checksList: list})[id] || null'};\n"
        f"Date.now = () => {now * 1000};\n{esc}\n{ago}\n{fn}\n"
        f"renderE2eFull({json.dumps(boards)}, {json.dumps(list(names))});\n"
        "console.log(JSON.stringify({btn: {text: btn.textContent, hidden: btn.hidden, danger: cls.has('danger')},"
        " rows: list.innerHTML}));")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


NOW = 10_000_000
PASS = {"at": NOW - 60, "head": "ffffffff", "result": "pass"}


class ChecksButton(unittest.TestCase):
    def test_all_null_hidden(self):
        self.assertEqual(render([{"e2eFull": None}, {}]),
                         {"btn": {"text": "", "hidden": True, "danger": False}, "rows": ""})

    def test_label_counts_projects_with_a_record(self):
        one = render([{"e2eFull": PASS}, {"e2eFull": None}])
        self.assertEqual(one["btn"], {"text": "Checks · 1", "hidden": False, "danger": False})
        two = render([{"e2eFull": PASS, "uiSweep": PASS}, {"uiSweep": PASS}])
        self.assertEqual(two["btn"]["text"], "Checks · 2")

    def test_missing_elements_tolerated(self):
        self.assertEqual(render([{"e2eFull": PASS}], missing=True)["rows"], "")


class ChecksRows(unittest.TestCase):
    def test_pass_fail_running_rows(self):
        one = render([{"e2eFull": {"at": NOW - 3 * 3600, "head": "1a2b3c4d5e", "result": "pass"}}])
        self.assertEqual(one["rows"], "<li><span>E2E main pass 1a2b3c4 3h ago</span></li>")
        two = render([{"e2eFull": {"at": NOW - 60, "head": "ffffffff", "result": "fail"}},
                      {"e2eFull": {"at": NOW - 60, "head": "1234567890", "result": "running"}}])
        self.assertEqual(two["rows"], '<li><span class="danger">a E2E main fail fffffff 1m ago</span></li>'
                         "<li><span>b E2E main running 1234567</span></li>")

    def test_escapes_and_missing_fields(self):
        el = render([{"e2eFull": {"result": "pass"}}, {"e2eFull": {"at": NOW, "head": "<b>", "result": "error"}}],
                    names=["<i>", "b"])
        self.assertEqual(el["rows"], "<li><span>&lt;i&gt; E2E main pass — —</span></li>"
                         '<li><span class="danger">b E2E main error &lt;b&gt; 0s ago</span></li>')

    def test_ui_sweep_pass_next_to_e2e(self):
        el = render([{"e2eFull": {"at": NOW - 3 * 3600, "head": "1a2b3c4d5e", "result": "pass"},
                      "uiSweep": {"at": NOW - 60, "head": "9f8e7d6c5b", "result": "pass", "findings": 0}}])
        self.assertEqual(el["rows"], "<li><span>E2E main pass 1a2b3c4 3h ago</span>"
                                     " · <span>UI sweep pass 9f8e7d6 1m ago · 0 findings</span></li>")

    def test_ui_sweep_without_e2e_record(self):
        el = render([{"e2eFull": PASS},
                     {"e2eFull": None, "uiSweep": {"at": NOW - 7200, "head": "abcdefgh", "result": "running"}}])
        self.assertEqual(el["rows"], "<li><span>a E2E main pass fffffff 1m ago</span></li>"
                         '<li><span class="danger">b UI sweep stale abcdefg 2h ago</span></li>')
        self.assertEqual(render([{"uiSweep": {"at": NOW - 60, "head": "abcdefgh", "result": "running"}}])["rows"],
                         "<li><span>UI sweep running abcdefg</span></li>")


class ChecksRed(unittest.TestCase):
    def danger(self, rec, key="e2eFull"):
        return render([{key: rec}, {"e2eFull": PASS}])["btn"]["danger"]

    def test_bad_results_are_red(self):
        for result in ("fail", "failed", "error"):
            for key in ("e2eFull", "uiSweep"):
                self.assertTrue(self.danger({"at": NOW - 60, "head": "x", "result": result}, key), (result, key))

    def test_good_results_are_not_red(self):
        for result in ("pass", "running", None):
            self.assertFalse(self.danger({"at": NOW - 60, "head": "x", "result": result}), result)

    def test_stale_running_is_red(self):
        self.assertTrue(self.danger({"at": NOW - 7200, "head": "x", "result": "running"}))
        self.assertFalse(self.danger({"at": NOW - 7199, "head": "x", "result": "running"}))
        el = render([{"e2eFull": {"at": NOW - 7200, "head": "abcdefgh", "result": "running"}}])
        self.assertEqual(el["rows"], '<li><span class="danger">E2E main stale abcdefg 2h ago</span></li>')

    def test_sweep_fail_with_no_open_items_is_not_red(self):
        sweep = {"at": NOW - 120, "head": "abcdefgh", "result": "fail", "findings": 3, "open": 0}
        el = render([{"e2eFull": PASS, "uiSweep": sweep}])
        self.assertFalse(el["btn"]["danger"])
        self.assertEqual(el["rows"], "<li><span>E2E main pass fffffff 1m ago</span>"
                         " · <span>UI sweep fail abcdefg 2m ago · 3 findings</span></li>")

    def test_sweep_fail_with_open_items_or_no_count_stays_red(self):
        for extra in ({"open": 1}, {"open": 2}, {}):
            sweep = {"at": NOW - 120, "head": "abcdefgh", "result": "fail", "findings": 3, **extra}
            el = render([{"e2eFull": PASS, "uiSweep": sweep}, {"e2eFull": None, "uiSweep": None}])
            self.assertTrue(el["btn"]["danger"], extra)
            self.assertEqual(el["rows"], "<li><span>E2E main pass fffffff 1m ago</span>"
                             ' · <span class="danger">UI sweep fail abcdefg 2m ago · 3 findings</span></li>', extra)

    def test_e2e_fail_still_red_next_to_retired_sweep(self):
        sweep = {"at": NOW - 120, "head": "abcdefgh", "result": "fail", "findings": 3, "open": 0}
        self.assertTrue(render([{"e2eFull": {**PASS, "result": "fail"}, "uiSweep": sweep}])["btn"]["danger"])


class ChecksMarkup(unittest.TestCase):
    def test_strip_gone_button_and_dialog_present(self):
        text = DASHBOARD.read_text()
        self.assertNotIn('id="e2eFull"', text)
        self.assertNotIn("#e2eFull", text)
        btn = re.search(r'<button class="btn" id="checksBtn" type="button" hidden data-agent-hint="[^"]+">Checks</button>',
                        text)
        self.assertIsNotNone(btn)
        self.assertLess(text.index('id="aiBtn"'), btn.start(), "Checks sits last in the header")
        self.assertLess(btn.start(), text.index("</header>"))
        dialog = text[text.index('<dialog id="checks" aria-label="Checks">'):]
        dialog = dialog[:dialog.index("</dialog>")]
        self.assertIn('<button class="close" type="button" aria-label="Close">✕</button>', dialog)
        self.assertIn('id="checksList"', dialog)
        self.assertIn('$("checksBtn").addEventListener("click"', text)

    def test_checks_tap_targets_and_mobile_dialog(self):
        text = DASHBOARD.read_text()
        self.assertIn("#checks .close,#checksBtn{min-height:44px;min-width:44px}", text)
        mobile = text[text.index("@media (max-width:640px){#colour"):]
        self.assertIn("#checks,#usage,#rank{width:100%", mobile[:mobile.index("}")])

    def test_desktop_header_one_row(self):
        """At 1400 px and wider the header never wraps: buttons keep their size, and #machine and #routing wrap their
        text inside their own box instead (job 977 rework: no readout text is cut off)."""
        text = DASHBOARD.read_text()
        start = text.index("@media (min-width:1400px){header{flex-wrap:nowrap")
        rule = text[start:text.index("\n", start)]
        self.assertIn("header>*{flex-shrink:0}", rule)
        self.assertIn("#machine,#routing{flex-shrink:1;white-space:normal}", rule)
        self.assertIn("#status:empty{flex-basis:0}", rule, "an empty status takes no room; a status keeps its 26ch")
        self.assertIn("#cooldownState:empty,#autoOff:empty{min-width:0}", rule, "an empty state text takes no room")
        self.assertLess(text.index("header{flex-wrap:wrap}"), start, "the desktop rule overrides the wrapping one")

    def test_machine_and_routing_never_cut_off(self):
        """No rule anywhere ellipsizes or clips the machine readout or the Claude usage button."""
        text = DASHBOARD.read_text()
        rules = re.findall(r"[^{}]*#(?:machine|routing)\b[^{}]*\{[^}]*\}", text[:text.index("</style>")])
        self.assertTrue(rules)
        for r in rules:
            sel = r[:r.index("{")]
            if re.search(r"#(?:machine|routing)\s*(?:,|$)", sel.strip() + ","):  # the element itself, not a descendant
                self.assertNotIn("ellipsis", r)
                self.assertNotIn("overflow:hidden", r)
                self.assertNotIn("min-width:0", r)

if __name__ == "__main__":
    unittest.main()
