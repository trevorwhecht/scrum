"""Job 1347: a rework or resume spawn of a scrum agent that fails once with `Agent type '<name>' not found` is retried
once before the AGENT_MISSING ask runs (the link can be briefly absent while install.sh or git rewrites it)."""
import unittest
from pathlib import Path

ROUTING = Path(__file__).resolve().parents[2] / "skills" / "trevskills-scrum" / "lanes" / "routing.md"


class MissingAgentRetryRepro(unittest.TestCase):
    def test_first_not_found_is_retried_once_before_the_ask(self):
        text = ROUTING.read_text()
        para = text[text.index("**Missing agent.**"):]
        para = para[:para.index("\n\n")] if "\n\n" in para else para
        retry = para.find("retry the spawn once")
        ask = para.find("Run `B ask $ID 'agent missing")
        self.assertNotEqual(retry, -1, "Missing agent paragraph has no 'retry the spawn once' wording")
        self.assertLess(retry, ask, "the retry must come before the AGENT_MISSING ask")
        self.assertIn("fails again", para)
        self.assertIn("spawn no `general-purpose` or other agent in its place", para)


if __name__ == "__main__":
    unittest.main()
