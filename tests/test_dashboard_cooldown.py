import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def fn_body(text, name):
    start = text.index(f"function {name}(")
    return text[start:text.index("\n}\n", start) + 2]


class CooldownButton(unittest.TestCase):
    """Job 305: a header button that turns cool-down on and off, and a state text that says when the Mac is idle."""

    def test_markup_and_posts(self):
        text = DASHBOARD.read_text()
        header = text[text.index("<header>"):text.index("</header>")]
        self.assertRegex(header, r'<span id="machine"[^>]*></span>\s*<div id="controls">\s*<button class="btn" id="cooldown" type="button"',
                         "right after #machine, first of the header's buttons")
        btn = re.search(r'<button class="btn" id="cooldown"[^>]*>', header).group(0)
        self.assertIn("data-agent-hint=", btn, "the explanation is in the hint, not on screen")
        self.assertIn("holds only new work", btn)
        self.assertIn("The shop Mac is not held by cool-down", btn)
        self.assertIn('<span id="cooldownState"', header)
        click = text[text.index('$("cooldown").addEventListener("click"'):]
        click = click[:click.index("\n});\n")]
        self.assertIn('post("api/cooldown", {on: !btn.dataset.on})', click, "the opposite of the shown state")
        self.assertIn("renderCooldown({cooldown: out.cooldown", click, "re-renders from the response")
        self.assertIn("restart_waiting: waiting", click, "the click re-render keeps the last poll's Safe to restart")
        self.assertIn("if (focused) btn.focus()", click, "disabling during the POST drops focus; it comes back")
        self.assertIn('act === "resume" ? {manual: true}', text, "the Play/Resume form marks the click manual")
        self.assertIn("renderCooldown(m)", fn_body(text, "poll"))
        css = " ".join(re.findall(r"#cooldown[^{]*\{[^}]*\}", text))
        self.assertIn("min-height:44px;min-width:44px", css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b|\bwhite\b")

    def test_render_states(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        script = (f"const els = {{cooldown: {{dataset: {{}}}}, cooldownState: {{}}}};\nconst $ = id => els[id];\n{esc}\n"
                  f"{fn_body(text, 'renderCooldown')}\n"
                  "const out = [{cooldown: false, sessions: 3}, {cooldown: true, sessions: 3}, {cooldown: true, sessions: 1},\n"
                  "  {cooldown: true, sessions: 0}, {cooldown: true, sessions: 0, restart_waiting: []},\n"
                  "  {cooldown: true, sessions: 2, restart_waiting: ['p/618']},\n"
                  "  {cooldown: true, sessions: 0, restart_waiting: ['p/<b>', 'q/7']},\n"
                  "  {cooldown: false, sessions: 0, restart_waiting: ['p/618']}].map(m => { renderCooldown(m);\n"
                  "  return [els.cooldown.hidden, els.cooldown.textContent, els.cooldownState.innerHTML]; });\n"
                  "renderCooldown(null);\n"
                  "out.push(els.cooldown.hidden);\n"
                  "delete els.cooldownState; renderCooldown({cooldown: true, sessions: 0});\n"
                  "console.log(JSON.stringify(out));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, [[False, "Cool down", ""],
                               [False, "Resume work", "Cooling down · 3 sessions finishing"],
                               [False, "Resume work", "Cooling down · 1 session finishing"],
                               [False, "Resume work", "Idle, safe to restart <code>sudo shutdown -r now</code>"],
                               [False, "Resume work", "Safe to restart: yes <code>sudo shutdown -r now</code>"],
                               [False, "Resume work",
                                "Cooling down · 2 sessions finishing · Safe to restart: no — waiting on p/618"],
                               [False, "Resume work", "Safe to restart: no — waiting on p/&lt;b&gt;, q/7"],
                               [False, "Cool down", ""],
                               True])


def button(worker, on=False, disabled=False):
    """A shop Mac's own Cool down / Resume work button, as renderMachine draws it."""
    return (f'<button class="btn" type="button" data-worker="{worker}"{' data-on="1"' if on else ""}'
            f'{" disabled" if disabled else ""} aria-label="{"Resume work on" if on else "Cool down"} {worker}">'
            f'{"Resume work" if on else "Cool down"}</button>')


class ShopCooldownButtons(unittest.TestCase):
    """Job 1185: each shop Mac gets its own Cool down / Resume work button beside its rings in the meter, with
    #cooldown's click pattern: an explicit on/off POST naming the worker, disabled while it is in flight."""

    def test_markup_hints_and_css(self):
        text = DASHBOARD.read_text()
        header = text[text.index("<header>"):text.index("</header>")]
        btn = re.search(r'<button class="btn" id="cooldown"[^>]*>', header).group(0)
        self.assertIn("each shop Mac has its own Cool down button", btn)
        meter = re.search(r'<span id="machine"[^>]*>', header).group(0)
        self.assertIn("ends with its own Cool down button", meter)
        self.assertIn("cooldown-&lt;alias&gt;", meter)
        self.assertIn("#machine .btn{min-height:44px;min-width:44px", text, "a 44x44 tap target, as #cooldown")

    def run_node(self, body):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        line = lambda s: text[text.index(s):text.index("\n", text.index(s))]
        ago = text[text.index("const ago = "):text.index("\n};\n", text.index("const ago = ")) + 3]
        click = text[text.index('$("machine").addEventListener("click"'):]
        click = click[:click.index("\n});\n") + 5]
        script = ("Date.now = () => 1763460000000;\nconst document = {activeElement: null};\n"
                  "const els = {machine: {hidden: false, innerHTML: '', querySelectorAll: () => [],"
                  " addEventListener(type, f) { this.on = f; }}, cooldownState: {textContent: ''}};\n"
                  "const $ = id => els[id];\n"
                  "const posts = [], post = (url, body) => new Promise((ok, fail) => posts.push({url, body, ok, fail}));\n"
                  + "\n".join(line(s) for s in ("const esc = ", "const shopCoolPending = ", "let machineLast = "))
                  + f"\n{ago}\n" + "".join(fn_body(text, f) + "\n" for f in ("machineLevel", "heldUntilText", "usagePart", "renderMachine"))
                  + click + "\n"
                  "const M = {min_free_ram_pct: 20, max_swap_pct: 25, min_free_disk_gb: 10, max_cpu_load_pct: 150, cpu_cores: 8,\n"
                  "  free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null};\n"
                  "const shop = (name, cooldown) => ({name, free_ram_pct: 50, cpu_load_pct: 10, cpu_cores: 4, at: 1763459960, cooldown});\n"
                  "const btns = () => [...els.machine.innerHTML.matchAll(/<button [^>]*>[^<]*<\\/button>/g)].map(m => m[0]);\n"
                  "const errs = () => [...els.machine.innerHTML.matchAll(/<button [^>]*>[^<]*<\\/button> <span class=\"error\"[^>]*>[^<]*<\\/span>/g)].map(m => m[0]);\n"
                  "const fake = (worker, on) => ({dataset: on ? {worker, on: '1'} : {worker}, closest() { return this; }});\n"
                  "const settle = () => new Promise(r => setTimeout(r));\n"
                  f"(async () => {{ {body} }})();")
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_one_button_per_worker(self):
        out = self.run_node(
            "renderMachine({...M, shop: [shop('shopmac', false), shop('mac2', true), shop('mac3')]});\n"
            "const groups = els.machine.innerHTML.split('<span class=\"grp\">').slice(1);\n"
            "renderMachine({...M, shop: [shop('<b>', false)]}); const odd = btns();\n"
            "renderMachine({...M, shop: []}); const none = btns();\n"
            "console.log(JSON.stringify([groups.map(g => [...g.matchAll(/<button [^>]*>[^<]*<\\/button>/g)].map(m => m[0])),"
            " groups.map(g => g.includes('<span>cooling down</span>')), odd, none]));")
        self.assertEqual(out, [[[], [button("shopmac")], [button("mac2", on=True)], [button("mac3")]],
                               [False, False, True, False],
                               [button("&lt;b&gt;")], []])

    def test_click_posts_worker_and_keeps_pending_through_poll(self):
        """A second click while the POST is in flight sends nothing; a poll re-render keeps it disabled; two workers'
        answers arriving out of order each land on their own button; a failed POST leaves the label and shows the error
        beside that button until the next click on it."""
        out = self.run_node(
            "const poll = () => renderMachine({...M, shop: [shop('a', false), shop('b', true)]});\n"
            "poll(); const out = {};\n"
            "els.machine.on({target: fake('a', false)}); els.machine.on({target: fake('a', false)});\n"
            "poll(); out.pending = btns();\n"
            "els.machine.on({target: fake('b', true)});\n"
            "out.posts = posts.map(p => [p.url, p.body]);\n"
            "posts[1].ok({cooldown: false, worker: 'b'}); await settle(); out.bFirst = btns();\n"
            "posts[0].ok({cooldown: true, worker: 'a'}); await settle(); out.both = btns();\n"
            "els.machine.on({target: fake('a', true)}); posts[2].fail(new Error('Server error 500')); await settle();\n"
            "out.failed = [btns(), errs(), els.cooldownState.textContent, posts[2].body];\n"
            "poll(); out.polled = errs();\n"
            "els.machine.on({target: fake('a', false)}); out.retry = errs(); posts[3].ok({cooldown: true, worker: 'a'}); await settle();\n"
            "out.retried = [btns(), errs()];\n"
            "els.machine.on({target: {closest: () => null}}); out.count = posts.length;\n"
            "console.log(JSON.stringify(out));")
        self.assertEqual(out["pending"], [button("a", disabled=True), button("b", on=True)])
        self.assertEqual(out["posts"], [["api/cooldown", {"worker": "a", "on": True}],
                                        ["api/cooldown", {"worker": "b", "on": False}]])
        self.assertEqual(out["bFirst"], [button("a", disabled=True), button("b")], "b's answer first: a still waits")
        self.assertEqual(out["both"], [button("a", on=True), button("b")])
        alert = '<span class="error" role="alert">Server error 500</span>'
        self.assertEqual(out["failed"], [[button("a", on=True), button("b")], [button("a", on=True) + " " + alert], "",
                                         {"worker": "a", "on": False}], "the error sits beside a's own button, not #cooldownState")
        self.assertEqual(out["polled"], [button("a") + ' <span class="error">Server error 500</span>'],
                         "a poll keeps the error, and does not announce it again")
        self.assertEqual(out["retry"], [], "the next click on that worker clears its error")
        self.assertEqual(out["retried"], [[button("a", on=True), button("b", on=True)], []])
        self.assertEqual(out["count"], 4, "a click outside a button posts nothing")

    def test_poll_refocus_never_scrolls(self):
        """The 2 s poll redraw gives focus back to the focused shop button without scrolling the page to the header."""
        out = self.run_node(
            "const calls = [];\n"
            "document.activeElement = {matches: s => s === '#machine [data-worker]', dataset: {worker: 'a'}};\n"
            "els.machine.querySelectorAll = () => ['b', 'a'].map(w => ({dataset: {worker: w}, focus(o) { calls.push([w, o]); }}));\n"
            "renderMachine({...M, shop: [shop('a', false), shop('b', false)]});\n"
            "console.log(JSON.stringify(calls));")
        self.assertEqual(out, [["a", {"preventScroll": True}]])


if __name__ == "__main__":
    unittest.main()
