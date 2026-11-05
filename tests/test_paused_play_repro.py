"""Job 644: a paused job keeps its Play button while the machine guard would only queue the click (low free RAM, swap,
low disk, the session ceiling, a CPU-load-only hold). Only a click serve.py would refuse outright hides Play."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

import test_serve  # module import only: unittest must not collect ServeTest a second time from here
from test_dashboard_stop_buttons import js

ServeBase = type("ServeBase", (unittest.TestCase,),
                 {k: v for k, v in vars(test_serve.ServeTest).items() if not k.startswith("test_")})

PLAY = '<form data-act="resume"><button class="btn primary tall" type="submit">Play</button></form>'
CALM = {"SCRUM_FREE_RAM": "90", "SCRUM_SWAP_PCT": "0", "SCRUM_FREE_DISK_GB": "500", "SCRUM_CPU_BUSY_PCT": "5",
        "SCRUM_CPU_LOAD_PCT": "10"}


class PausedPlayRepro(ServeBase):
    def test_paused_job_shows_play_under_machine_refusal(self):
        b = self.serve.board
        job_id = b.cmd_new(self.root, "Paused under load")
        self.addCleanup(self.edit_job, job_id, stage="aborted", paused=None, play_queued=None)
        self.edit_job(job_id, stage="build", paused=True, reason="stalled in build: paused by Trevor. Fix: click Play.")
        tmp = Path(tempfile.mkdtemp())
        idle, full = tmp / "ps-idle.txt", tmp / "ps-full.txt"
        idle.write_text("")
        full.write_text("".join(f"claude -p /trevskills-scrum build {i}\n" for i in range(20)))
        cases = {"low free RAM": {"SCRUM_FREE_RAM": "10"},
                 "swap": {"SCRUM_FREE_RAM": "30", "SCRUM_SWAP_PCT": "40"},
                 "low disk": {"SCRUM_FREE_DISK_GB": "2"},
                 "session ceiling": {"SCRUM_PS": str(full)},
                 "CPU load only": {"SCRUM_CPU_LOAD_PCT": "900", "SCRUM_CPU_BUSY_PCT": "99"}}
        for name, env in cases.items():
            with self.subTest(name), mock.patch.dict(os.environ, {**CALM, "SCRUM_PS": str(idle),
                                                                  "SCRUM_SWAP_LOG": str(tmp / "swap.json"), **env}):
                job = self.board_jobs()[job_id]
                html, = js(f"renderActions({json.dumps({**job, 'key': f'repo/{job_id}', 'project': 'repo'})});"
                           " out(els.actions.innerHTML);")
                self.assertIn(PLAY, html, f"{name}: resumeRefusal={job.get('resumeRefusal')!r}")


if __name__ == "__main__":
    unittest.main()
