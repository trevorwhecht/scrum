"""Job 1112 repro: on 2026-11-18 cloud_tick aborted shop jobs 1051, 1055 and 1063 with SHOP_ENDED although their PRs
(#741, #745, #762) had merged minutes earlier. Each PR below is the real one's title and head, read from the GitHub
REST API; the sync never matched them, so the merged PR lost to the dead session."""
import unittest
from unittest import mock

import test_serve_shop as base  # its import pins the hermetic env; only its fixtures are borrowed, not its tests

MERGED = [  # (why, job id, PR number, PR title, PR head ref)
    ("#741: short head, short title tag", "1051-apply-digest-065-p5-067-p4-and-070-p2-to", 741,
     "[scrum 1051] Check gate: claimed backlog lines count as on backlog", "scrum/1051"),
    ("#745: full head, no title tag", "1055-apply-digest-025-p1-to", 745,
     "Apply digest 025 p1 to lanes/newjob.md", "scrum/1055-apply-digest-025-p1-to"),
    ("#762: full head, short title tag", "1063-apply-digest-114-p2-and-p3-to", 762,
     "[scrum 1063] Close digest 114 p2 and p3 gaps in the stop rules", "scrum/1063-apply-digest-114-p2-and-p3-to"),
]


class MergedShopPrSpellingTest(unittest.TestCase):
    setUp, week, project, job, cloud = (base.ShopTickTest.setUp, base.ShopTickTest.week, base.ShopTickTest.project,
                                        base.ShopTickTest.job, base.ShopTickTest.cloud)

    def test_merged_pr_beats_shop_ended_whatever_its_spelling(self):
        for why, job_id, number, title, head in MERGED:
            with self.subTest(why):
                self.serve.CLOUD_LAST.clear()
                root = self.project("mm", [{"id": job_id, "stage": "cloud", "shop": "3697", "account": "owa"}])
                url = f"https://github.com/trevorwhecht/mm/pull/{number}"
                pr = {"number": number, "html_url": url, "title": title, "state": "closed",
                      "merged_at": "2026-11-18T11:39:39Z", "labels": [], "user": {"login": "trevorwhecht"},
                      "body": "Scrum lane: fast\n", "head": {"ref": head, "repo": {"full_name": "trevorwhecht/mm"}},
                      "base": {"ref": "main", "repo": {"full_name": "trevorwhecht/mm"}}}
                self.sh.ended.side_effect = lambda *a, **kw: "Merged the PR\n"  # the session ended after its merge
                with mock.patch.object(self.board, "gh_api", side_effect=lambda repo, ep, *f: {} if f else [pr]), \
                        mock.patch.object(self.board, "merge_refusal", return_value=None), \
                        mock.patch.object(self.board, "artifacts_pushed", return_value=False):
                    self.cloud()
                job = self.job(root, job_id)
                self.assertEqual((job["stage"], job["pr"], job["reason"]), ("done", url, None),
                                 f"{why}: merged PR {url} lost to the ended shop session")
                self.assertEqual((root / "backlog.md").read_text(), "# Backlog\n", "a merged job is never requeued")


if __name__ == "__main__":
    unittest.main()
