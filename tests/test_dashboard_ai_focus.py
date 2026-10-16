import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

# Fake DOM. Setting innerHTML parses its <button> tags into child buttons and disconnects the old ones; removing the
# focused node drops focus to body, as a browser does. frame() is a rendering update: it blurs a focused node that is
# hidden or disabled (focus fixup). getJson()/post() return promises the scenario settles by hand.
HARNESS = r"""
const doc = {activeElement: null};
const unent = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const parseSel = sel => {
  sel = sel.replace(/^#\w+\s+/, "");
  const tag = (sel.match(/^[a-z]+/) || [""])[0], attrs = [];
  for (const m of sel.matchAll(/\[([\w-]+)(?:=(?:"((?:\\.|[^"\\])*)"|([^\]]*)))?\]/g))
    attrs.push([m[1], m[2] !== undefined ? m[2].replace(/\\(.)/g, "$1") : m[3] !== undefined ? m[3].replace(/\\(.)/g, "$1") : null]);
  return {tag, attrs};
};
function el(tag, attrs = {}) {
  const e = {tag, attrs, children: [], isConnected: true, listeners: {}, _hidden: "hidden" in attrs, _disabled: "disabled" in attrs, value: "",
    _html: "", dataset: {}, id: attrs.id || "", textContent: "",
    addEventListener(t, f) { (this.listeners[t] ||= []).push(f); },
    focus() { if (this.isConnected) { doc.activeElement = this; focusLog.push(this.dataset.id || this.dataset.row || this.dataset.research || this.id || this.tag); } },
    matches(sel) { const {tag, attrs} = parseSel(sel); return (!tag || tag === this.tag) && attrs.every(([k, v]) => k in this.attrs && (v === null || this.attrs[k] === v)); },
    closest(sel) { return this.matches(sel) ? this : null; },
    querySelectorAll(sel) { return this.children.filter(c => c.matches(sel)); },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
    get hidden() { return this._hidden; }, set hidden(v) { this._hidden = !!v; },
    get disabled() { return this._disabled; }, set disabled(v) { this._disabled = !!v; },
    get innerHTML() { return this._html; },
    set innerHTML(h) {
      for (const c of this.children) { c.isConnected = false; if (doc.activeElement === c) doc.activeElement = body; }
      this._html = h;
      this.children = [...h.matchAll(/<button([^>]*)>/g)].map(m => {
        const a = {};
        for (const x of m[1].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) a[x[1]] = x[2] === undefined ? "" : unent(x[2]);
        const b = el("button", a);
        for (const k in a) if (k.startsWith("data-")) b.dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = a[k];
        return b;
      });
    },
  };
  for (const k in attrs) if (k.startsWith("data-")) e.dataset[k.slice(5)] = attrs[k];
  return e;
}
const body = el("body"), els = {};
const $ = id => els[id] ||= Object.assign(el(id === "aiBack" ? "button" : id === "aiCats" ? "div" : "x", {id}), {showModal() {}, open: true});
$("aiBack").hidden = true; $("aiScope").value = "global";
doc.activeElement = body;
const document = doc; doc.body = body;
const CSS = {escape: s => String(s).replace(/[^\w-]/g, c => "\\" + c)};
const enc = encodeURIComponent, STALE = "stale", runs = {};
const focusLog = [];
const pending = [];
const deferred = () => { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); pending.push({res, rej}); return p; };
const urls = [];  // every getJson url, in order
const getJson = url => { urls.push(url); return deferred(); }, post = () => deferred();
const tick = () => new Promise(r => setTimeout(r, 0));
const frame = () => { const a = doc.activeElement; if (a && a !== body && (a.hidden || a.disabled)) doc.activeElement = body; };
const click = async (target) => { doc.activeElement = target; for (const f of $("aiList").listeners.click || []) f({target}); };
const back = () => { doc.activeElement = $("aiBack"); for (const f of $("aiBack").listeners.click) f({target: $("aiBack")}); };
const listBtn = sel => $("aiList").querySelector(sel);
const active = () => { const a = doc.activeElement; return a === body ? "body" : a === $("aiBack") ? "aiBack" : a === $("aiScope") ? "aiScope"
  : (a.isConnected ? "" : "DISCONNECTED:") + (a.attrs["data-toggle"] ? `${a.attrs["data-toggle"]}:${a.dataset.row}` : a.dataset.research ? `research:${a.dataset.research}`
  : a.dataset.cat ? `cat:${a.dataset.cat}` : `id:${a.dataset.id}`); };
const ID = 'user:skills/a b"c';  // contains /, :, a space and a quote
const ITEMS = [{id: ID, name: "alpha", scope: "user", path: "~/.claude/skills/a", status: ""}, {id: "user:skills/beta", name: "beta", scope: "user", path: "~/b", status: ""}];
const auditRows = () => [
  {id: ID, name: "alpha", scope: "user", category: "skills", lifetime: 1, recent: 0, tokens: 10, flags: [], verdict: "Retire", reason: "r", disable: true, editable: true},
  {id: "user:skills/beta", name: "beta", scope: "user", category: "skills", lifetime: 1, recent: 0, tokens: 10, flags: [], verdict: "Keep", reason: "r", disable: true, editable: true},
];
const ITEM = {id: ID, name: "alpha", scope: "user", path: "~/a", content: "x", editable: false};
"""

def run(scenario):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))] + "\n"
    src = text[text.index("const AI_GROUPS"):text.index("// Save and Undo both answer")]
    script = HARNESS + esc + src + "\n(async () => {\n" + scenario + "\n})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


CATEGORY = 'aiData = {categories: [{key: "skills", label: "Skills", count: 2, items: ITEMS}]}; aiCat = "skills"; renderAi();\n'
AUDIT = CATEGORY + 'aiCat = "audit"; aiAudit = {rows: auditRows()}; renderAi();\n'


class AiSettingsFocusTest(unittest.TestCase):
    def test_open_item_focuses_back(self):
        got = run(CATEGORY + """
const out = {};
click(listBtn("button[data-id]")); out.beforeFetch = active();
frame(); pending.shift().res(null); await tick(); frame(); out.afterFail = active();
renderAi();
click(listBtn("button[data-id]")); pending.shift().res(ITEM); await tick(); frame(); out.afterLoad = active();
""" + 'aiCat = "audit"; aiAudit = {rows: auditRows()}; renderAi();\n' + """
click(listBtn("button[data-id]")); out.auditEdit = active();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"beforeFetch": "aiBack", "afterFail": "aiBack", "afterLoad": "aiBack", "auditEdit": "aiBack"})

    def test_back_focuses_opened_row(self):
        got = run(CATEGORY + """
const out = {};
click($("aiList").querySelectorAll("button[data-id]").find(b => b.dataset.id === ID)); pending.shift().res(ITEM); await tick(); frame();
back(); out.category = active();
""" + 'aiCat = "audit"; aiAudit = {rows: auditRows()}; renderAi();\n' + """
click($("aiList").querySelectorAll("button[data-id]").find(b => b.dataset.id === ID)); pending.shift().res(ITEM); await tick(); frame();
back(); out.audit = active();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"category": f'id:user:skills/a b"c', "audit": f'id:user:skills/a b"c'})

    def test_back_falls_back_to_category(self):
        got = run(CATEGORY + """
click(listBtn("button[data-id]")); pending.shift().res(ITEM); await tick(); frame();
aiData.categories[0].items = ITEMS.slice(1);  // the opened item has left the list
back();
console.log(JSON.stringify({active: active()}));
""")
        self.assertEqual(got, {"active": "cat:skills"})

    def test_toggle_focuses_new_button(self):
        got = run(AUDIT + """
const out = {}, rows = auditRows();
click(listBtn('button[data-toggle="disable"]')); frame();
pending.shift().res(rows[0]); await tick(); frame(); out.afterDisable = active();
click(listBtn('button[data-toggle="enable"]')); frame();
pending.shift().res(rows[0]); await tick(); frame(); out.afterUndo = active();
click(listBtn('button[data-toggle="disable"]')); frame();
pending.shift().res(rows[0]); await tick(); frame();
click(listBtn('button[data-toggle="enable"]')); frame();
pending.shift().res({...rows[0], disable: false}); await tick(); frame(); out.afterUndoNoDisable = active();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"afterDisable": f'enable:user:skills/a b"c', "afterUndo": f'disable:user:skills/a b"c',
                               "afterUndoNoDisable": f'research:user:skills/a b"c'})

    def test_toggle_failure_refocuses_button(self):
        got = run(AUDIT + """
const b = listBtn('button[data-toggle="disable"]');
click(b); frame();
pending.shift().rej(new Error("down")); await tick(); frame();
console.log(JSON.stringify({same: document.activeElement === b, disabled: b.disabled, error: $("aiError").textContent}));
""")
        self.assertEqual(got, {"same": True, "disabled": False, "error": "Couldn't change this setting. Is serve.py running?"})

    def test_no_focus_steal_when_user_moved(self):
        got = run(AUDIT + """
const out = {}, rows = auditRows();
click(listBtn('button[data-toggle="disable"]')); frame(); $("aiScope").focus();
pending.shift().res(rows[0]); await tick(); out.toggleMoved = active();
click(listBtn('button[data-toggle="disable"]')); frame(); $("aiScope").focus();
pending.shift().rej(new Error("down")); await tick(); out.failMoved = active();
click(listBtn('button[data-toggle="disable"]')); frame();
aiAudit = {rows: auditRows()}; document.activeElement = document.body;  // left the tab: the reply is dropped
pending.shift().res(rows[0]); await tick(); out.dropped = active();
""" + CATEGORY + """
click(listBtn("button[data-id]")); $("aiScope").focus();
pending.shift().res(ITEM); await tick(); out.openMoved = active();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"toggleMoved": "aiScope", "failMoved": "aiScope", "dropped": "body", "openMoved": "aiScope"})

    def test_research_resolve_keeps_open_editor(self):
        got = run(AUDIT + """
const out = {};
click(listBtn("button[data-research]"));
click(listBtn("button[data-id]")); pending[1].res({...ITEM, editable: true, content: "unsaved"}); await tick();
pending[0].res({key: "k", log: "runs/r.log", project: "reg"}); await tick();
out.editor = /<form id="aiEdit">\\s*<textarea id="aiText"[^>]*>unsaved<\\/textarea>/.test($("aiList").innerHTML);
out.backHidden = $("aiBack").hidden;
back();
out.researchDisabled = $("aiList").querySelectorAll("button[data-research]").find(b => b.dataset.research === ID).disabled;
out.researching = $("aiList").innerHTML.includes("Researching…");
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"editor": True, "backHidden": False, "researchDisabled": True, "researching": True})

    def test_research_resolve_rerenders_visible_audit(self):
        got = run(AUDIT + """
click(listBtn("button[data-research]"));
pending.shift().res({key: "k", log: "runs/r.log", project: "reg"}); await tick();
const html = $("aiList").innerHTML;
console.log(JSON.stringify({researching: html.includes('Researching…</span><a href="p/reg/runs/r.log"'),
  disabled: $("aiList").querySelectorAll("button[data-research]").find(b => b.dataset.research === ID).disabled,
  backHidden: $("aiBack").hidden}));
""")
        self.assertEqual(got, {"researching": True, "disabled": True, "backHidden": True})


if __name__ == "__main__":
    unittest.main()
