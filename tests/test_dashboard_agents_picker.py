import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

# Fake DOM: #agSkills keeps its innerHTML string; post() never settles, so the add stays pending.
HARNESS = """
const els = {agDetail: {dataset: {agent: "scrum-builder"}}, agFilter: {value: ""}, agSkills: {innerHTML: ""}, agError: {textContent: ""}};
const $ = id => els[id], enc = encodeURIComponent, esc = s => String(s);
let posts = 0;
const post = () => { posts++; return new Promise(() => {}); };
"""
FIXTURE = 'agents = [{name: "scrum-builder", skills: []}]; skills = [{name: "alpha"}, {name: "beta"}];\n'
SCENARIO = """
renderSkills();
addSkill("alpha", {disabled: false, textContent: "alpha"});  // the button the user clicked
els.agFilter.value = "a"; renderSkills();                     // typing in "Filter skills" rebuilds the list
const html = els.agSkills.innerHTML;
addSkill("alpha", {disabled: html.includes("disabled"), textContent: "alpha"});  // click the rebuilt button / Enter
console.log(JSON.stringify({html, posts}));
"""


class AgentsPickerPendingTest(unittest.TestCase):
    def test_pending_add_survives_filter_rerender(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index("function renderSkills()")
        src = text[start:text.index('\n$("agentsBtn")', start)]
        state = text[text.index("let agents = "):text.index("const modelLabel")]  # module-level picker state
        out = subprocess.run([node, "-e", HARNESS + state + FIXTURE + src + SCENARIO], capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        buttons = re.findall(r"<button([^>]*)>([^<]*)</button>", got["html"])
        self.assertEqual([(re.search(r'data-skill="([^"]*)"', a).group(1), " disabled" in a, label) for a, label in buttons],
                         [("alpha", True, "Adding…"), ("beta", True, "beta")])
        self.assertEqual(got["posts"], 1)


if __name__ == "__main__":
    unittest.main()
