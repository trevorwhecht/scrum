"""Job 1362: an edit job's card (board `kind`, set by `B set $ID lane=edit kind=<kind>`) shows the kind in the coloured
project tag; the tag keeps `data-project` and the project's colour. A card with no kind, and the viewer's tagButton,
still show the project name."""
import json, re, unittest

from test_dashboard_play_queued import run

JOB = {"key": "edit/001-reef", "project": "edit", "id": "001-reef", "title": "Reef ad", "stage": "build",
       "lane": "edit", "updatedAt": "2026-11-22T10:00:00Z"}
TAG = re.compile(r'<span class="tag" data-project="([^"]*)" style="([^"]*)">([^<]*)</span>')


class EditKindTag(unittest.TestCase):
    def test_card_tag_shows_kind(self):
        kinded, plain = run(f"out(card({json.dumps({**JOB, 'kind': 'edit-animation'})}));"
                            f"out(card({json.dumps(JOB)}));")
        tags = TAG.findall(kinded)
        self.assertEqual(len(tags), 1, kinded)
        project, style, text = tags[0]
        self.assertEqual((project, text), ("edit", "edit-animation"))
        self.assertEqual(style, TAG.findall(plain)[0][1], "the kind tag keeps the project's colour")

    def test_card_tag_without_kind_unchanged(self):
        plain, other, button = run(f"out(card({json.dumps(JOB)}));"
                                   f"out(card({json.dumps({**JOB, 'key': 'p/300-a', 'project': 'p', 'lane': None})}));"
                                   "out(tagButton('edit'));")
        self.assertEqual([(p, t) for p, _, t in TAG.findall(plain)], [("edit", "edit")])
        self.assertEqual([(p, t) for p, _, t in TAG.findall(other)], [("p", "p")])
        self.assertRegex(button, r'^<button type="button" class="tag" data-project="edit" [^>]*>edit</button>$')


if __name__ == "__main__":
    unittest.main()
