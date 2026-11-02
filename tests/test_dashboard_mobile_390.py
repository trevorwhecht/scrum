import re, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def css():
    text = DASHBOARD.read_text()
    return text[text.index("<style>") + 7:text.index("</style>")]


def split(sheet):
    """(rules outside any @media, [body of each @media (max-width:640px) block]), as flat strings."""
    outside, phone, i = [], [], 0
    while (m := re.compile(r"@media[^{]*\{").search(sheet, i)):
        outside.append(sheet[i:m.start()])
        depth, j = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(sheet[j], 0)
            j += 1
        if "max-width:640px" in m.group(0).replace(" ", ""):
            phone.append(sheet[m.end():j - 1])
        i = j
    outside.append(sheet[i:])
    return "".join(outside), phone


def decls(block, selector):
    """Every declaration of the rules whose selector list contains selector exactly."""
    out = ""
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
        if selector in [s.strip() for s in sel.split(",")]:
            out += body.replace(" ", "") + ";"
    return out


class DashboardMobile390Css(unittest.TestCase):
    def test_css_rules_present(self):
        outside, phone = split(css())
        self.assertIn("min-height:44px", decls(outside, "#viewer .btn"))
        phone = "".join(phone)
        self.assertIn("padding-right:0", decls(phone, "#tabs"))
        close = decls(phone, "#tabs .close")
        self.assertIn("min-height:44px", close)
        self.assertIn("min-width:44px", close)
        self.assertIn("margin-left:0", decls(phone, "#filter"))
        self.assertIn("display:none", decls(phone, ".col:not(.pick)"))
        self.assertIn("font-size:16px", decls(phone, "#colPick"))
        self.assertIn("min-height:44px", decls(phone, "#colPick"))
        self.assertIn("display:none", decls(outside, "#colPick"))

    def test_header_desktop_unchanged(self):
        outside, phone = split(css())
        base = decls(outside, "header")
        self.assertIn("display:flex;align-items:baseline;gap:12px;padding:16px", base)
        self.assertNotIn("padding:6px", base)
        self.assertIn("padding:6px12px", decls("".join(phone), "header"))

    def test_backlog_row_buttons_44px(self):
        row = decls(split(css())[0], "#blList .btn")
        self.assertIn("min-height:44px", row)
        self.assertIn("min-width:44px", row)


if __name__ == "__main__":
    unittest.main()
