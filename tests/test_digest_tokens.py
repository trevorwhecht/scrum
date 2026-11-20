"""Job 1241: the digest's per-job cost audit, digests/<NNN>/tokens.md (board.write_tokens, called by cmd_digest_start),
and the helpers it shares with serve.py job_costs (board.cost_by_job, JOB_COST_DAYS, prompt_round, agent_pin,
transcript_tools)."""
import io, json, os, sys, tempfile, time, unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
import board  # noqa: E402

T0 = 1_700_000_000


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def reply(t, mid, cwd="/nowhere", model="claude-opus-4-5", tools=(), **counts):
    return {"type": "assistant", "timestamp": iso(t), "cwd": cwd,
            "message": {"id": mid, "model": model, "usage": counts, "content": list(tools)}}


def tool(tid, name, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
    return path


class CostByJobTest(unittest.TestCase):
    @staticmethod
    def row(project, job, model="claude-opus-4-5", **counts):
        return {"ts": 1, "model": model, "project": project, "job": job, "agent": "main", "skill": None,
                **{k: counts.get(k, 0) for k in board.TOKEN_KEYS}}

    def test_sums_tokens_and_usd_per_project_job(self):
        self.assertEqual(board.JOB_COST_DAYS, 7)
        rows = [self.row("p", "1-a", output_tokens=1_000_000), self.row("p", "1-a", input_tokens=2_000_000),
                self.row("p", "2-b", model="claude-sonnet-4-5", cache_read_input_tokens=1_000_000,
                         cache_creation_input_tokens=1_000_000),
                self.row("q", "1-a", model="claude-haiku-4-5", input_tokens=1_000_000),
                self.row(None, "1-a", output_tokens=7), self.row("p", None, output_tokens=9)]
        got = board.cost_by_job(rows)
        self.assertEqual(sorted(got), ["p", "q"])
        self.assertEqual(sorted(got["p"]), ["1-a", "2-b"])
        self.assertEqual(got["p"]["1-a"][0], 3_000_000)
        self.assertAlmostEqual(got["p"]["1-a"][1], 35.0)  # opus: 1M out $25 + 2M in $10
        self.assertEqual(got["p"]["2-b"][0], 2_000_000)
        self.assertAlmostEqual(got["p"]["2-b"][1], 4.05)  # sonnet: 1M cache read $0.30 + 1M cache write $3.75
        self.assertEqual(got["q"]["1-a"][0], 1_000_000)
        self.assertAlmostEqual(got["q"]["1-a"][1], 1.0)
        self.assertEqual(board.cost_by_job([]), {})

    def test_serve_job_costs_uses_board_helpers(self):
        src = (SKILL / "serve.py").read_text()
        body = src[src.index("def job_costs("):src.index("def board_with_activity(")]
        self.assertIn("board.cost_by_job(", body)
        self.assertIn("board.JOB_COST_DAYS", body)
        self.assertNotIn("JOB_COST_DAYS = ", src)


class PromptRoundTest(unittest.TestCase):
    def test_prompt_round(self):
        self.assertEqual(board.prompt_round("JOB_DIR=/x/jobs/1-a\nROUND=2\nWORKTREE=/w"), 2)
        self.assertEqual(board.prompt_round("ROUND=0"), 0)
        self.assertEqual(board.prompt_round("ROUND=3 then ROUND=4"), 3)
        self.assertIsNone(board.prompt_round("no round here"))
        self.assertIsNone(board.prompt_round("ROUND=x"))
        self.assertIsNone(board.prompt_round(""))

    def test_subagent_rounds_not_inherited(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "projects"
        write_lines(d / "p" / "s1.jsonl", [prompt("JOB_DIR=/r/scrum/jobs/5-e\nROUND=1"), reply(T0, "m", input_tokens=1)])
        sub = d / "p" / "s1" / "subagents"
        write_lines(sub / "agent-aa.jsonl", [prompt("JOB_DIR=/r/scrum/jobs/5-e\nROUND=2"), reply(T0 + 1, "a", input_tokens=2)])
        write_lines(sub / "agent-bb.jsonl", [prompt("no round"), reply(T0 + 2, "b", input_tokens=3)])
        write_lines(sub / "agent-cc.jsonl", [prompt("ROUND=x"), reply(T0 + 3, "c", input_tokens=4)])
        reg = Path(tmp.name) / "projects.json"
        reg.write_text("[]")
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)}):
            rows = board.transcript_tokens(T0 - 10, T0 + 10, d)
        self.assertEqual([(r["input_tokens"], r["round"]) for r in rows], [(1, 1), (2, 2), (3, None), (4, None)])
        self.assertEqual([r["transcript"] for r in rows],
                         [str(d / "p" / "s1.jsonl"), str(sub / "agent-aa.jsonl"), str(sub / "agent-bb.jsonl"),
                          str(sub / "agent-cc.jsonl")])


if __name__ == "__main__":
    unittest.main()
