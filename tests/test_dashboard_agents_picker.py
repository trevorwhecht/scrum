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


# The three ways the detail view can be gone when renderSkills() runs late.
LEAVE = """
const leave = {
  noFilter: () => { delete els.agFilter; },              // no detail view rendered yet
  hidden: () => { els.agDetail.hidden = true; },        // Back
  noAgent: () => { agents = []; },                      // modal closed and reopened
};
"""
# Every state: renderSkills() must not throw and must leave #agSkills alone.
NOOP_SCENARIO = """
const out = {};
for (const k of Object.keys(leave)) {
  agents = [{name: "scrum-builder", skills: []}]; els.agFilter = {value: ""}; els.agDetail.hidden = false;
  els.agSkills.innerHTML = "SENTINEL"; leave[k]();
  try { renderSkills(); out[k] = els.agSkills.innerHTML; } catch (e) { out[k] = "threw: " + e.message; }
}
console.log(JSON.stringify(out));
"""
# Every state: leave while the POST is in flight, then let it reject.
FAILED_ADD_SCENARIO = """
(async () => {
  const out = {};
  for (const k of Object.keys(leave)) {
    agents = [{name: "scrum-builder", skills: []}]; els.agFilter = {value: ""}; els.agDetail.hidden = false; adding = null;
    let reject; post = () => new Promise((_, r) => { reject = r; });
    const p = addSkill("alpha");
    leave[k](); reject(new Error("boom " + k));
    let error = null;
    try { await p; } catch (e) { error = e.message; }
    out[k] = {error, adding, agError: els.agError.textContent};
  }
  console.log(JSON.stringify(out));
})();
"""


class AgentsPickerPendingTest(unittest.TestCase):
    def run_node(self, scenario, harness=HARNESS):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index("function renderSkills()")
        src = text[start:text.index('\n$("agentsBtn")', start)]
        state = text[text.index("let agents = "):text.index("const modelLabel")]  # module-level picker state
        out = subprocess.run([node, "-e", harness + state + FIXTURE + src + scenario], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_render_skills_noop_when_detail_gone(self):
        got = self.run_node(LEAVE + NOOP_SCENARIO)
        self.assertEqual(got, {"noFilter": "SENTINEL", "hidden": "SENTINEL", "noAgent": "SENTINEL"})

    def test_failed_add_after_leaving_detail_clears_lock(self):
        got = self.run_node(LEAVE + FAILED_ADD_SCENARIO, HARNESS.replace("const post", "let post"))
        for k in ("noFilter", "hidden", "noAgent"):
            self.assertEqual(got[k], {"error": None, "adding": None, "agError": f"boom {k}"}, k)

    def test_pending_add_survives_filter_rerender(self):
        got = self.run_node(SCENARIO)
        buttons = re.findall(r"<button([^>]*)>([^<]*)</button>", got["html"])
        self.assertEqual([(re.search(r'data-skill="([^"]*)"', a).group(1), " disabled" in a, label) for a, label in buttons],
                         [("alpha", True, "Adding…"), ("beta", True, "beta")])
        self.assertEqual(got["posts"], 1)


if __name__ == "__main__":
    unittest.main()
