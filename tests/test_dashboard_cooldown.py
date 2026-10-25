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
        self.assertRegex(header, r'<span id="machine"[^>]*></span>\s*<button class="btn" id="cooldown" type="button"',
                         "right after #machine")
        btn = re.search(r'<button class="btn" id="cooldown"[^>]*>', header).group(0)
        self.assertIn("data-agent-hint=", btn, "the explanation is in the hint, not on screen")
        self.assertIn("refuses every automatic start", btn)
        self.assertIn('<span id="cooldownState"', header)
        click = text[text.index('$("cooldown").addEventListener("click"'):]
        click = click[:click.index("\n});\n")]
        self.assertIn('post("api/cooldown", {on: !btn.dataset.on})', click, "the opposite of the shown state")
        self.assertIn("renderCooldown({cooldown: out.cooldown", click, "re-renders from the response")
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
                  "  {cooldown: true, sessions: 0}].map(m => { renderCooldown(m);\n"
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
                               True])


if __name__ == "__main__":
    unittest.main()
