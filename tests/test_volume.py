import json, os, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

SKILL = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
import board  # noqa: E402
import serve  # noqa: E402

DASHBOARD = SKILL / "dashboard.html"
DETACHED = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def fn_body(text, name):
    start = text.index(f"function {name}(")
    return text[start:text.index("\n}\n", start) + 2]


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "volume"
        env = mock.patch.dict(os.environ, {"SCRUM_VOLUME": str(self.path), "SCRUM_MUTE": ""})
        env.start()
        self.addCleanup(env.stop)


class PlayVolume(Tmp):
    """Job 397: board.play reads the dashboard's volume file on every call."""

    def argv(self, content):
        if content is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(content)
        with mock.patch.object(board.subprocess, "Popen") as popen:
            board.play("/x.aiff")
        return [c.args[0] for c in popen.call_args_list]

    def test_volume_path(self):
        self.assertEqual(board.volume_path(), self.path)
        with mock.patch.dict(os.environ, {"SCRUM_VOLUME": ""}):
            self.assertEqual(board.volume_path(), Path.home() / ".claude" / "trevskills-scrum" / "volume")

    def test_levels(self):
        self.assertEqual(self.argv('{"level": 40, "muted": false}'), [["afplay", "-v", "0.4", "/x.aiff"]])
        self.assertEqual(self.argv('{"level": 40, "muted": true}'), [])
        self.assertEqual(self.argv('{"level": 0, "muted": false}'), [])
        self.assertEqual(self.argv('{"level": 100, "muted": false}'), [["afplay", "-v", "1.0", "/x.aiff"]])

    def test_fallbacks_play_full(self):
        self.assertEqual(self.argv(None), [["afplay", "-v", "1.0", "/x.aiff"]], "missing file")
        for bad in ("not json{", "[1]", '{"level": 150, "muted": false}', '{"level": "40", "muted": false}',
                    '{"level": true, "muted": false}', '{"level": 40.5, "muted": false}'):
            self.assertEqual(self.argv(bad), [["afplay", "-v", "1.0", "/x.aiff"]], bad)

    def test_detached_and_scrum_mute_first(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"level": 40, "muted": false}')
        with mock.patch.object(board.subprocess, "Popen") as popen:
            with mock.patch.dict(os.environ, {"SCRUM_MUTE": "1"}):
                board.play("/x.aiff")
            popen.assert_not_called()
            board.play("/x.aiff")
        popen.assert_called_once_with(["afplay", "-v", "0.4", "/x.aiff"], **DETACHED)


class SetVolume(Tmp):
    def test_writes_file(self):
        self.assertEqual(serve.set_volume(30, True), (200, {"level": 30, "muted": True}))
        self.assertEqual(json.loads(self.path.read_text()), {"level": 30, "muted": True})
        self.assertEqual(serve.set_volume(0, False), (200, {"level": 0, "muted": False}))
        self.assertEqual(json.loads(self.path.read_text()), {"level": 0, "muted": False})
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["volume"], "no tmp file left behind")

    def test_bad_values_leave_file(self):
        level_err = (400, {"error": "level must be a whole number from 0 to 100"})
        for level in (True, 40.0, "40", -1, 101, None):
            self.assertEqual(serve.set_volume(level, False), level_err, repr(level))
        for muted in ("true", 1, None):
            self.assertEqual(serve.set_volume(40, muted), (400, {"error": "muted must be true or false"}), repr(muted))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_write_failure_is_generic_500(self):
        self.path.parent.mkdir(parents=True)
        self.path.mkdir()  # a directory where the file goes: os.replace fails
        with mock.patch("sys.stderr"):
            self.assertEqual(serve.set_volume(40, False), (500, {"error": "could not save the volume"}))
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["volume"], "tmp file removed")

    def test_routed_in_do_post(self):
        src = (SKILL / "serve.py").read_text()
        self.assertIn('elif path == "/api/volume":\n                code, obj = set_volume(body.get("level"), body.get("muted"))', src)


class VolumeMarkup(unittest.TestCase):
    def setUp(self):
        self.text = DASHBOARD.read_text()

    def test_header_markup(self):
        header = self.text[self.text.index("<header>"):self.text.index("</header>")]
        self.assertRegex(header, r'<span class="volwrap"><button class="btn" id="volume" type="button"[^>]*>\s*<svg[^>]*>.*</svg>'
                         r'</button><span class="volpop"><input type="range" id="volumeLevel" min="0" max="100" step="1" aria-label="Sound volume"></span></span>'
                         r'\s*<button class="btn" id="backlogBtn"')

    def test_css(self):
        css = " ".join(re.findall(r"(?:#volume|\.vol)[^{]*\{[^}]*\}", self.text))
        self.assertIn("#volume{min-height:44px;min-width:44px", css)
        self.assertIn(".volwrap:focus-within .volpop", css)
        self.assertIn(".volwrap:hover .volpop", css)
        self.assertIn('#volume[aria-pressed="true"] .waves{display:none}', css, "muted hides the waves")
        self.assertIn('#volume[aria-pressed="false"] .cross{display:none}', css, "unmuted hides the cross")
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b|\bwhite\b")

    def test_handlers(self):
        text = self.text
        inp = text[text.index('$("volumeLevel").addEventListener("input"'):]
        inp = inp[:inp.index("\n});\n")]
        self.assertIn('store.set("scrum.volume"', inp)
        self.assertIn('store.set("scrum.muted", "")', inp, "moving the slider clears mute")
        chg = text[text.index('$("volumeLevel").addEventListener("change"'):]
        chg = chg[:chg.index("\n});\n")]
        self.assertIn("sendVolume()", chg)
        click = text[text.index('$("volume").addEventListener("click"'):]
        click = click[:click.index("\n});\n")]
        self.assertIn("muted = !muted", click)
        self.assertIn('store.set("scrum.muted", muted ? "1" : "")', click)
        self.assertIn("renderVolume()", click)
        self.assertIn("sendVolume()", click)
        self.assertIn("readVolume()", text)
        self.assertIn('if (store.get("scrum.volume") || store.get("scrum.muted")) sendVolume();', text)
        send = fn_body(text, "sendVolume")
        self.assertIn('post("api/volume", {level, muted})', send)
        self.assertIn(".catch(() => {})", send, "an older serve.py's 404 shows no error")

    def node(self, script):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout)

    def test_read_volume(self):
        got = self.node(
            "const saved = {}; const store = {get: k => saved[k] || \"\"};\nlet level, muted;\n"
            f"{fn_body(self.text, 'readVolume')}\n"
            "const out = [\"\", \"abc\", \"150\", \"30\", \"-5\", \"2.5\"].map(v => { saved[\"scrum.volume\"] = v; readVolume(); return level; });\n"
            "saved[\"scrum.muted\"] = \"1\"; readVolume(); out.push(muted); saved[\"scrum.muted\"] = \"\"; readVolume(); out.push(muted);\n"
            "console.log(JSON.stringify(out));")
        self.assertEqual(got, [100, 100, 100, 30, 100, 100, True, False])

    def test_render_volume(self):
        got = self.node(
            "const attrs = () => { const a = {}; return {attrs: a, setAttribute: (k, v) => { a[k] = v; }}; };\n"
            "const els = {volume: attrs(), volumeLevel: {}};\nconst $ = id => els[id];\nlet level, muted;\n"
            f"{fn_body(self.text, 'renderVolume')}\n"
            "const out = [[50, false], [50, true], [0, false]].map(([l, m]) => { level = l; muted = m; renderVolume();\n"
            "  return [els.volume.attrs['aria-pressed'], els.volume.attrs['aria-label'], els.volumeLevel.value]; });\n"
            "delete els.volume; delete els.volumeLevel; renderVolume();\n"
            "console.log(JSON.stringify(out));")
        self.assertEqual(got, [["false", "Mute sounds", "50"], ["true", "Unmute sounds", "50"], ["true", "Unmute sounds", "0"]])


if __name__ == "__main__":
    unittest.main()
