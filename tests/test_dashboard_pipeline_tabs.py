import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

# Fake DOM: tab buttons record setAttribute; listeners on #pipeTabs are kept so the test can fire them.
HARNESS = """
const node = extra => ({style: {}, dataset: {}, hidden: false, innerHTML: "", textContent: "", querySelector: () => null,
  on: {}, addEventListener(t, f) { this.on[t] = f; }, ...extra});
const tabs = ["all", "fast", "standard", "debug", "bigboy", "maintenance"].map(k => ({dataset: {tab: k}, attrs: {},
  setAttribute(n, v) { this.attrs[n] = String(v); }, focus() {}, closest() { return this; }}));
const els = {flow: node(), agZoom: node(), agZoomOut: node(), agZoomIn: node(),
  pipeTabs: node({querySelectorAll: () => tabs, querySelector: s => tabs.find(b => s.includes(`"${b.dataset.tab}"`))})};
const on = els.pipeTabs.on, $ = id => els[id], esc = s => String(s), store = {get: () => null, set: () => {}}, window = {addEventListener: () => {}};
"""
SCENARIO = """
const seen = [];
const snap = () => seen.push({tab: pipelineTab, tabindex: Object.fromEntries(tabs.map(b => [b.dataset.tab, b.attrs.tabindex]))});
renderFlow(); snap();                                                   // first load
on.click({target: tabs[2]}); snap();                                    // click Standard
on.keydown({key: "ArrowRight"}); snap();                                // -> Debug
on.keydown({key: "ArrowLeft"}); on.keydown({key: "ArrowLeft"}); snap(); // -> Fast
setTab("standard", true); snap();                                       // dashed "-> Standard" link in the chart
setTab("bigboy", true); snap();                                         // "Children" link
console.log(JSON.stringify(seen));
"""


class PipelineTabsTest(unittest.TestCase):
    def test_pipeline_tabs_roving_tabindex(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        src = text[text.index("const ORCH = "):text.index("function showAgents(")]
        out = subprocess.run([node, "-e", HARNESS + src + SCENARIO], capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        self.assertEqual([g["tab"] for g in got], ["all", "standard", "debug", "fast", "standard", "bigboy"])
        for g in got:
            want = {k: "0" if k == g["tab"] else "-1" for k in ("all", "fast", "standard", "debug", "bigboy", "maintenance")}
            self.assertEqual(g["tabindex"], want, g["tab"])


if __name__ == "__main__":
    unittest.main()
