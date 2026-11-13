"""A card names the Claude account its session ran on (board `account`, set by board.spawn) in a lane chip right after
the lane chip; a job started before accounts existed shows no extra chip."""
import json, re, unittest

from test_dashboard_play_queued import run

JOB = {"key": "p/300-a", "project": "p", "id": "300-a", "title": "Acct", "stage": "build", "updatedAt": "2026-11-13T10:00:00Z"}


class AccountChip(unittest.TestCase):
    def test_card_shows_account_chip_only_when_set(self):
        html, bad, none = run(f"out(card({json.dumps({**JOB, 'account': 'owa'})}));"
                              f"out(card({json.dumps({**JOB, 'account': '<b>x</b>'})}));"
                              f"out(card({json.dumps(JOB)}));")
        chips = re.findall(r'<span class="lanechip">([^<]*)</span>', html)
        self.assertEqual(chips[:2], ["standard", "owa"])  # right after the lane chip
        self.assertIn('<span class="lanechip">&lt;b&gt;x&lt;/b&gt;</span>', bad)
        self.assertEqual(re.findall(r'<span class="lanechip">([^<]*)</span>', none), ["standard"])


if __name__ == "__main__":
    unittest.main()
