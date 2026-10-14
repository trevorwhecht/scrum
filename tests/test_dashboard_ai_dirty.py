import json, shutil, subprocess, unittest

from test_dashboard_ai_focus import DASHBOARD, HARNESS, CATEGORY

# On top of the focus HARNESS: rendering #aiList swaps in fresh editor nodes (#aiEdit, #aiText, ...) and disconnects the old
# ones, as a browser does; the AI-Settings dialog gets close(), and the shared dialog click handler is fed this one dialog.
EXTRA = r"""
const FORM = ["aiEdit", "aiText", "aiSave", "aiUndo", "aiStatus", "aiDiff"];
const list = $("aiList"), listHtml = Object.getOwnPropertyDescriptor(list, "innerHTML");
Object.defineProperty(list, "innerHTML", {get: listHtml.get, set(h) {
  listHtml.set.call(this, h);
  const m = h.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/);
  for (const id of FORM) {
    if (els[id]) els[id].isConnected = false;
    els[id] = Object.assign(el(id, {id}), {isConnected: !!m, classList: {add() {}, remove() {}}, scrollIntoView() {}});
  }
  if (m) { els.aiText.value = unent(m[1]).replace(/\r\n?/g, "\n"); els.aiUndo.hidden = true; els.aiSave.disabled = true; }
}});
const dlg = $("aiSettings");
dlg.close = () => { dlg.open = false; };
doc.querySelectorAll = sel => sel === "dialog" ? [dlg] : [];
const type = t => { $("aiText").value = t; for (const f of list.listeners.input) f({target: $("aiText")}); };
const submit = () => { for (const f of list.listeners.submit) f({preventDefault() {}}); };
const xBtn = {closest: s => s === ".close" ? xBtn : null};
const dclick = target => { for (const f of dlg.listeners.click) f({target}); };
const escape = () => { let kept = false; for (const f of dlg.listeners.cancel || []) f({preventDefault() { kept = true; }}); if (!kept) dlg.close(); };
const leave = how => how === "back" ? back() : how === "x" ? dclick(xBtn) : how === "backdrop" ? dclick(dlg) : escape();
const EXITS = ["back", "x", "backdrop", "escape"];
// left: the attempt took effect (back to the list, or the dialog closed)
const state = () => ({open: dlg.open, editing: !!$("aiEdit").isConnected, error: $("aiError").textContent, text: $("aiText").value});
const EDIT = {id: ID, name: "alpha", scope: "user", path: "~/a", content: "x", editable: true, version: 1, category: "skills"};
const JSONITEM = {...EDIT, content: '{"a": 1}', category: "settings"};
const openItem = async it => { dlg.open = true; renderAi(); click(listBtn("button[data-id]")); pending.shift().res({...it}); await tick(); frame(); };
"""

WARN = "Unsaved changes. Press again to discard."


def run(scenario):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))] + "\n"
    # Through the shared dialog click handler, which holds the ✕ / backdrop exit.
    src = text[text.index("const AI_GROUPS"):text.index("\npoll();")]
    script = HARNESS + EXTRA + esc + src + "\n(async () => {\n" + CATEGORY + scenario \
        + "\n})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class AiSettingsDirtyTest(unittest.TestCase):
    def test_back_with_unsaved_changes_warns_then_leaves(self):
        got = run("""
const out = {};
await openItem(EDIT); type("x edited");
back(); out.first = state();
back(); out.second = {...state(), active: active()};
console.log(JSON.stringify(out));
""")
        self.assertEqual(got["first"], {"open": True, "editing": True, "error": WARN, "text": "x edited"})
        self.assertEqual(got["second"]["editing"], False)
        self.assertEqual(got["second"]["active"], 'id:user:skills/a b"c')

    def test_close_with_unsaved_changes_warns_then_closes(self):
        got = run("""
const out = {};
for (const a of ["x", "backdrop", "escape"]) for (const b of ["x", "backdrop", "escape"]) {
  await openItem(EDIT); type("dirty");
  leave(a); const first = state();
  leave(b); out[`${a}>${b}`] = [first.open, first.error, dlg.open];
}
console.log(JSON.stringify(out));
""")
        for k, v in got.items():
            self.assertEqual(v, [True, WARN, False], k)
        self.assertEqual(len(got), 9)

    def test_clean_editor_leaves_without_warning(self):
        got = run("""
const out = {};
for (const how of EXITS) {
  const r = out[how] = {};
  const check = name => { leave(how); r[name] = how === "back" ? !$("aiEdit").isConnected && $("aiError").textContent === "" : !dlg.open && $("aiError").textContent === ""; };
  // the list, Security and Audit views (with a stale editable aiItem left from a dirty editor that was discarded)
  await openItem(EDIT); type("dirty"); back(); back();
  dlg.open = true; renderAi(); $("aiError").textContent = ""; check("list");
  dlg.open = true; aiCat = "security"; aiFindings = []; renderAi(); check("security");
  dlg.open = true; aiCat = "audit"; aiAudit = {rows: auditRows()}; renderAi(); check("audit");
  aiCat = "skills";
  await openItem(ITEM); check("readOnly");
  await openItem(EDIT); check("untouched");
  await openItem(EDIT); type("xy"); type("x"); check("typedBack");
  await openItem(EDIT); type("saved"); submit(); pending.shift().res({...EDIT, content: "saved", version: 2}); await tick();
  $("aiError").textContent = ""; check("afterSave");
  await openItem(EDIT); type("saved"); submit(); pending.shift().res({...EDIT, content: "saved", version: 2}); await tick();
  click($("aiUndo")); pending.shift().res({...EDIT, version: 3}); await tick(); check("afterUndo");
}
console.log(JSON.stringify(out));
""")
        expected = {k: True for k in ["list", "security", "audit", "readOnly", "untouched", "typedBack", "afterSave", "afterUndo"]}
        for how in ["back", "x", "backdrop", "escape"]:
            self.assertEqual(got[how], expected, how)

    def test_typing_after_warning_rearms_guard(self):
        got = run("""
const out = {};
await openItem(EDIT); type("dirty");
back(); type("dirtier"); out.afterType = $("aiError").textContent;
back(); out.second = state();
await openItem(EDIT); type("dirty");
escape(); type("dirtier"); escape(); out.escape = state();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got["afterType"], "")
        self.assertEqual(got["second"], {"open": True, "editing": True, "error": WARN, "text": "dirtier"})
        self.assertEqual(got["escape"], {"open": True, "editing": True, "error": WARN, "text": "dirtier"})

    def test_json_save_resets_textarea_when_unchanged(self):
        got = run("""
await openItem(JSONITEM); type('{"a":2}');
submit(); pending.shift().res({...JSONITEM, content: '{\\n  "a": 2\\n}', version: 2}); await tick();
console.log(JSON.stringify({text: $("aiText").value, baseline: aiItem.baseline, save: $("aiSave").disabled, status: $("aiStatus").textContent}));
""")
        self.assertEqual(got, {"text": '{\n  "a": 2\n}', "baseline": '{\n  "a": 2\n}', "save": True, "status": "Saved"})

    def test_json_save_keeps_text_typed_during_request(self):
        got = run("""
const out = {};
await openItem(JSONITEM); type('{"a":2}');
submit(); type('{"a":3}');
pending.shift().res({...JSONITEM, content: '{\\r\\n  "a": 2\\r\\n}', version: 2}); await tick();
Object.assign(out, {text: $("aiText").value, baseline: aiItem.baseline, save: $("aiSave").disabled, undoHidden: $("aiUndo").hidden, status: $("aiStatus").textContent});
back(); out.leave = state();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"text": '{"a":3}', "baseline": '{\n  "a": 2\n}', "save": False, "undoHidden": False, "status": "Saved",
                               "leave": {"open": True, "editing": True, "error": WARN, "text": '{"a":3}'}})

    def test_failed_save_still_guards_leave(self):
        got = run("""
const out = {};
const fails = {"409": Object.assign(new Error("x"), {status: 409}), "400": Object.assign(new Error("bad"), {status: 400}), network: new Error("down")};
for (const [k, err] of Object.entries(fails)) {
  await openItem(EDIT); type("dirty");
  back();  // armed before the save: the failed save must not leave it armed
  submit(); pending.shift().rej(err); await tick();
  back(); out[k] = state();
}
console.log(JSON.stringify(out));
""")
        for k in ["409", "400", "network"]:
            self.assertEqual(got[k], {"open": True, "editing": True, "error": WARN, "text": "dirty"}, k)


if __name__ == "__main__":
    unittest.main()
