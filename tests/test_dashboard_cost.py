"""Job 975: a card whose job has `costUsd` (serve.py board_with_activity) shows one meta line `$<usd, 2 decimals> ·
<tokens, compact> tokens`; a card without it shows no cost line."""
import json, unittest

from test_dashboard_play_queued import run

JOB = {"key": "p/975-a", "project": "p", "id": "975-a", "title": "Cost job", "stage": "done",
       "updatedAt": "2026-11-18T10:00:00Z"}


def card(**kw):
    return f"out(card({json.dumps({**JOB, **kw})}));"


class CardCost(unittest.TestCase):
    def test_cost_line(self):
        done, running, small, zero = run(card(costUsd=1.2374, costTokens=3_215_000)
                                          + card(stage="build", costUsd=12.5, costTokens=48_700)
                                          + card(costUsd=0.004, costTokens=850)
                                          + card(costUsd=0, costTokens=1_000_000))
        self.assertIn('<span class="meta">$1.24 · 3.2M tokens</span>', done)
        self.assertIn('<span class="meta">$12.50 · 48.7K tokens</span>', running)
        self.assertIn('<span class="meta">$0.00 · 850 tokens</span>', small)
        self.assertIn('<span class="meta">$0.00 · 1M tokens</span>', zero)

    def test_no_cost_line_without_cost(self):
        for html in run(card() + card(costTokens=500) + card(stage="build")):
            self.assertNotIn("tokens", html)
            self.assertNotIn(" tokens</span>", html)


if __name__ == "__main__":
    unittest.main()
