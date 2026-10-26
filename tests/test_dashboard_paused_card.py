"""A job Trevor paused (board `paused` true) stays in its stage column: red outline, a `paused` badge, no stale text,
and Play instead of Pause in its panel."""
import re, unittest

from test_dashboard_job_modal import DASHBOARD, run


def section(start, end):
    text = DASHBOARD.read_text()
    return text[text.index(start):text.index(end)]


class PausedCard(unittest.TestCase):
    def test_card_css_uses_the_theme_red(self):
        css = section("<style>", "</style>")
        rule = re.search(r"\.card\.paused\{([^}]*)\}", css)
        self.assertIsNotNone(rule, ".card.paused rule missing")
        self.assertIn("border:2px solid var(--human)", rule.group(1))
        self.assertNotRegex(rule.group(1), r"#[0-9a-fA-F]{3,6}|rgb", "no raw colour")

    def test_card_markup(self):
        card = section("function card(job)", "function render(")
        self.assertIn('${hold ? " paused" : ""}', card)
        self.assertIn('${hold ? \'<span class="badge">paused</span>\' : ""}', card)
        self.assertIn("!hold && !held", card)  # a paused card is never stale
        self.assertIn('const colOf = job => job.stage === "aborted" ? "done" : playQueued(job) ? "waiting" : job.stage;', DASHBOARD.read_text())

    def test_play_branch_in_panel(self):
        self.assertTrue(run('heldByTrevor({stage: "build", paused: true})'))
        self.assertFalse(run('heldByTrevor({stage: "build", waiting: "question: x"})'))
        self.assertEqual(run('pauseForm({stage: "build", paused: true})'), "")
        self.assertEqual(run('playForm({stage: "build", paused: true, reason: "stalled in build: paused by Trevor. Fix: click Play."})'),
                         '<form data-act="resume"><button class="btn primary tall" type="submit">Play</button></form>')
        self.assertEqual(run('playForm({stage: "build", reason: "stalled in build: paused by Trevor. Fix: click Play."})'), "")
        body = section("function renderActions(job)", '$("actions").addEventListener("submit"')
        self.assertIn("playForm(job) + reopenForm(job)", body)

    def test_paused_child_waits_on_trevor(self):
        self.assertTrue(run('needsYou({stage: "build", paused: true})'))


if __name__ == "__main__":
    unittest.main()
