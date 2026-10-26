import unittest

from test_dashboard_roadmap_card import run


class JobFileUrl(unittest.TestCase):
    """A board job carries the git ref it branched from as `base` (board.py FIELDS). The job modal must still fetch the
    job's own files from p/<project>/jobs/<id>/, not treat that ref as a URL prefix (which 404s on /origin/mainspec.md)."""

    def test_job_spec_md_served_for_existing_job(self):
        job = '{key: "trevskills-scrum/231-x", project: "trevskills-scrum", id: "231-x", base: "origin/main", files: ["spec.md"]}'
        got, = run(f'await show({job}, "spec.md"); console.log(JSON.stringify(fetched));', {}, projects=("trevskills-scrum",))
        self.assertEqual(got, ["p/trevskills-scrum/jobs/231-x/spec.md"])

    def test_job_file_served_for_parent_slash_name_project(self):
        job = '{key: "repos/app/7-y", project: "repos/app", id: "7-y", base: "origin/main", files: ["spec.md"]}'
        got, = run(f'await show({job}, "spec.md"); console.log(JSON.stringify(fetched));', {}, projects=("repos/app",))
        self.assertEqual(got, ["p/repos%2Fapp/jobs/7-y/spec.md"])


if __name__ == "__main__":
    unittest.main()
