import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum"


class TerminalOpensInBackground(unittest.TestCase):
    """Scrum's Terminal windows never take focus from what Trevor is typing in (2026-11-10)."""

    def test_no_focus_steal(self):
        serve = (SKILL / "serve.py").read_text()
        new_window = re.search(r'NEW_WINDOW_SCRIPT = """(.*?)"""', serve, re.S).group(1)
        script = (SKILL / "job-window.applescript").read_text()
        # raise-only code: the raiseWin handler and the doRaise-gated activate
        keep = re.sub(r"(?s)on raiseWin\(w\).*?end raiseWin", "", script)
        keep = keep.replace("if doRaise then activate", "")
        for name, text in (("job-window.applescript", keep), ("NEW_WINDOW_SCRIPT", new_window)):
            self.assertNotRegex(text, r"(?m)^\s*activate\b", name)
            self.assertNotIn("set index of", text, name)
        self.assertIn("my raiseWin", script)
        self.assertEqual(script.count("my raiseWin"), script.count("if doRaise then my raiseWin"))

if __name__ == "__main__":
    unittest.main()
