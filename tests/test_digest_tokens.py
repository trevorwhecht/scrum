"""Job 1241: the digest's per-job cost audit, digests/<NNN>/tokens.md (board.write_tokens, called by cmd_digest_start),
and the helpers it shares with serve.py job_costs (board.cost_by_job, JOB_COST_DAYS, prompt_round, agent_pin,
transcript_tools)."""
import io, json, shutil, os, sys, tempfile, time, unittest
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


class TranscriptToolsTest(unittest.TestCase):
    def test_counts_dedupes_and_bad_lines(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = write_lines(Path(tmp.name) / "t.jsonl", [
            prompt("hi"),
            reply(T0, "m1", tools=[tool("t1", "Read", file_path="/a/shot.PNG"), tool("t2", "Bash", command="ls")]),
            reply(T0, "m1", tools=[tool("t1", "Read", file_path="/a/shot.PNG"), tool("t2", "Bash", command="ls"),
                                   tool("t3", "Read", file_path="/a/b.py")]),  # the same message, written again
            "not json {\"tool_use\"",
            '["tool_use"]',
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t9"}]}},  # no name
            {"type": "assistant", "message": "tool_use"},
            reply(T0 + 1, "m2", tools=[tool("t4", "Read", file_path="/a/x.jpeg"), tool("t5", "Read", file_path="/a/y.jpg"),
                                       tool("t6", "Bash", command="pwd"), tool("t7", "Grep", pattern="png"),
                                       tool("t8", "Read", file_path="/a/png.txt")])])
        self.assertEqual(board.transcript_tools(p), ({"Read": 5, "Bash": 2, "Grep": 1}, 3))
        self.assertEqual(board.transcript_tools(Path(tmp.name) / "missing.jsonl"), ({}, 0))
        (Path(tmp.name) / "dir.jsonl").mkdir()
        self.assertEqual(board.transcript_tools(Path(tmp.name) / "dir.jsonl"), ({}, 0))


class AgentPinTest(unittest.TestCase):
    def test_agent_pin_reads_frontmatter(self):
        self.assertEqual(board.agent_pin("scrum-review-ui"), "sonnet")
        self.assertEqual(board.agent_pin("scrum-builder"), "opus")
        self.assertIsNone(board.agent_pin("main"))
        self.assertIsNone(board.agent_pin("no-such-agent"))
        self.assertIsNone(board.agent_pin("../skills/trevskills-scrum/SKILL"))


class WriteTokensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.repo = base / "app"
        self.root = self.repo / "scrum"
        (self.root / "digests" / "001").mkdir(parents=True)
        self.dir = base / "projects"
        self.dir.mkdir()
        reg = base / "machine" / "projects.json"
        reg.parent.mkdir()
        reg.write_text(json.dumps([str(self.repo)]))
        env = mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": str(self.dir), "SCRUM_REGISTRY": str(reg),
                                           "SCRUM_PULSE": str(reg.with_name("pulse.log"))})
        env.start()
        self.addCleanup(env.stop)
        fit = mock.patch.object(board, "_fit_diff", side_effect=self.fit)
        self.fit_calls = []
        self.added = {"1-a": 120}
        fit.start()
        self.addCleanup(fit.stop)
        self.t = time.time() - 3600
        self.n = 0

    def fit(self, root, job):
        self.fit_calls.append(job["id"])
        return (self.added[job["id"]], 3, 2, None) if job["id"] in self.added else (None, None, None, None)

    def board_jobs(self, *jobs):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": i, "title": i, "stage": "done", **({"lane": lane} if lane else {})} for i, lane in jobs]}))

    def jobs_txt(self, *ids, digest="001"):
        (self.root / "digests" / digest / "jobs.txt").write_text("".join(f"{i}\n" for i in ids))

    def replies(self, usd_list, model="claude-opus-4-5", tools=(), cwd=None, context=0):
        out = []
        for usd in usd_list:  # opus: $1 = 40,000 output tokens; sonnet: $1 = 66,667 rounded
            self.n += 1
            per = 40_000 if "opus" in model else 1_000_000 / 15
            out.append(reply(self.t + self.n, f"m{self.n}", cwd=cwd or str(self.repo), model=model,
                             tools=tools, output_tokens=round(usd * per), cache_read_input_tokens=context))
        return out

    def main(self, sid, job, lines, extra=""):
        return write_lines(self.dir / "p" / f"{sid}.jsonl", [prompt(f"JOB_DIR=/x/scrum/jobs/{job}{extra}")] + lines)

    def sub(self, sid, aid, agent, job, rnd, lines, meta=True):
        """job None writes a prompt with no JOB_DIR=; meta False writes no meta.json."""
        text = f"JOB_DIR=/x/scrum/jobs/{job}\nROUND={rnd}" if job else "do a thing"
        p = write_lines(self.dir / "p" / sid / "subagents" / f"agent-{aid}.jsonl", [prompt(text)] + lines)
        if meta:
            p.with_name(f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": agent}))
        return p

    def tokens(self, digest="001"):
        board.write_tokens(self.root, digest)
        return (self.root / "digests" / digest / "tokens.md").read_text()

    def fixture(self):
        self.board_jobs(("1-a", None), ("2-b", "standard"), ("3-c", None), ("4-d", None), ("5-e", None))
        self.jobs_txt("1-a", "2-b", "3-c", "4-d")
        self.main("s1", "1-a", self.replies([2]))
        self.r1 = self.sub("s1", "u1", "scrum-review-ui", "1-a", 1, self.replies([5], context=1000, tools=[
            tool("a1", "Read", file_path="/s/one.png"), tool("a2", "Bash", command="x")]))
        self.r2 = self.sub("s1", "u2", "scrum-review-ui", "1-a", 2, self.replies([2.5, 2], context=3000, tools=[
            tool("b1", "Bash", command="y")]))
        self.sub("s1", "b1", "scrum-builder", "1-a", 0, self.replies([1]))
        self.main("s2", "2-b", self.replies([1]))
        self.main("s3", "3-c", self.replies([2], model="claude-sonnet-4-5"))
        self.main("s4", "5-e", self.replies([50]))  # not in jobs.txt
        self.main("s5", "1-a", self.replies([70], cwd="/elsewhere"))  # another project's 1-a

    def test_jobs_split_by_agent_round_model(self):
        self.fixture()
        text = self.tokens()
        jobs = text[text.index("## Jobs\n"):text.index("## Flagged\n")]
        self.assertEqual(jobs, (
            "## Jobs\n"
            "- 1-a · lane standard · +120 lines · $12.50 · 507,000 tokens · 4,225 tokens per added line\n"
            "  - scrum-review-ui · round 1 · claude-opus-4-5 · $5.00 · 201,000 tokens\n"
            "  - scrum-review-ui · round 2 · claude-opus-4-5 · $4.50 · 186,000 tokens\n"
            "  - main · round - · claude-opus-4-5 · $2.00 · 80,000 tokens\n"
            "  - scrum-builder · round 0 · claude-opus-4-5 · $1.00 · 40,000 tokens\n"
            "- 3-c · lane standard · +? lines · $2.00 · 133,333 tokens · - tokens per added line\n"
            "  - main · round - · claude-sonnet-4-5 · $2.00 · 133,333 tokens\n"
            "- 2-b · lane standard · +? lines · $1.00 · 40,000 tokens · - tokens per added line\n"
            "  - main · round - · claude-opus-4-5 · $1.00 · 40,000 tokens\n"
            "- 4-d · no transcript rows\n"
            "\n"))
        self.assertNotIn("5-e", text)
        self.assertNotIn("4-d", self.fit_calls)  # a job without cost never reads its diff
        self.assertTrue(text.startswith("# Tokens: digest 001\n"))

    def test_flags_and_round_split(self):
        self.fixture()
        text = self.tokens()
        flagged = text[text.index("## Flagged\n"):]
        lines = [l for l in flagged.splitlines() if l.startswith("- ")]
        self.assertEqual(lines[0], (
            "- 1-a · $12.50 · scrum-review-ui ran on claude-opus-4-5, pinned sonnet; 6.3x lane median ($2.00); "
            "top 3 cost; scrum-review-ui 76% of job cost; scrum-review-ui round 2 $4.50 = 90% of round 1 $5.00"))
        self.assertEqual(lines[1:], ["- 3-c · $2.00 · top 3 cost", "- 2-b · $1.00 · top 3 cost"])
        self.assertIn("  - scrum-review-ui · round 1 · claude-opus-4-5 · $5.00", text)
        self.assertIn("  - scrum-review-ui · round 2 · claude-opus-4-5 · $4.50", text)

    def test_pin_rule_ignores_unknown_families_and_opus_pins(self):
        self.board_jobs(("1-a", None))
        self.jobs_txt("1-a")
        self.main("s1", "1-a", self.replies([1]))
        self.sub("s1", "c1", "scrum-review-code", "1-a", 1, self.replies([1], model="<synthetic>")
                 + self.replies([1], model="claude-sonnet-4-5"))
        self.sub("s1", "b1", "scrum-builder", "1-a", 0, self.replies([1], model="claude-fable-1"))
        self.sub("s1", "x1", "general-purpose", "1-a", 0, self.replies([1]))
        self.sub("s1", "d1", "scrum-digest-reader", "1-a", 0, self.replies([0.5], model="claude-haiku-4-5"))
        text = self.tokens()
        self.assertNotIn("pinned", text)

    def test_reviewer_round_rule_needs_round_one_cost(self):
        self.board_jobs(("1-a", None))
        self.jobs_txt("1-a")
        self.sub("s1", "e2", "scrum-review-e2e", "1-a", 2, self.replies([3], model="claude-sonnet-4-5"))
        self.sub("s1", "c1", "scrum-review-code", "1-a", 1, self.replies([1]))
        self.sub("s1", "c2", "scrum-review-code", "1-a", 2, self.replies([0.7]))
        self.sub("s1", "c3", "scrum-review-code", "1-a", 3, self.replies([0.8]))
        self.sub("s1", "s1", "scrum-review-security", "1-a", 1, self.replies([0], model="claude-opus-4-5"))
        self.sub("s1", "s2", "scrum-review-security", "1-a", 2, self.replies([1], model="claude-opus-4-5"))
        text = self.tokens()
        self.assertIn("scrum-review-code round 3 $0.80 = 80% of round 1 $1.00", text)
        self.assertNotIn("scrum-review-code round 2", text.split("## Flagged")[1])
        self.assertNotIn("scrum-review-e2e round", text.split("## Flagged")[1])
        self.assertNotIn("scrum-review-security round", text.split("## Flagged")[1])

    def test_costliest_agent_detail(self):
        self.fixture()
        text = self.tokens()
        flagged = text[text.index("## Flagged\n"):]
        block = flagged[flagged.index("- 1-a"):flagged.index("- 3-c")]
        self.assertEqual(block.splitlines()[1:], [
            "  - costliest: scrum-review-ui $9.50",
            "  - tools: Bash 2, Read 1",
            "  - image reads: 1",
            "  - peak context: 3,000 tokens",
            f"  - transcript: {self.r1}",
            f"  - transcript: {self.r2}"])
        self.assertLessEqual(len(block.splitlines()) - 1, 10)

    def test_transcript_lines_capped_at_six(self):
        self.board_jobs(("1-a", None))
        self.jobs_txt("1-a")
        paths = [self.sub("s1", f"r{i}", "scrum-review-ui", "1-a", i + 1, self.replies([1]))
                 for i in range(8)]
        text = self.tokens()
        flagged = text[text.index("## Flagged\n"):]
        tl = [l for l in flagged.splitlines() if l.startswith("  - transcript: ")]
        self.assertEqual(tl, [f"  - transcript: {p}" for p in paths[:5]] + ["  - transcript: +3 more"])
        self.assertIn("  - tools: none", flagged)

    def span(self, t0, t1, usd, tag):
        """Two replies stamped t0 and t1 seconds after self.t, together costing usd (opus)."""
        return [reply(self.t + t, f"{tag}{t}", cwd=str(self.repo), output_tokens=round(usd * 20_000))
                for t in (t0, t1)]

    def two_sessions(self, a, b, agent="scrum-builder"):
        self.board_jobs(("1-a", None))
        self.jobs_txt("1-a")
        for old in (self.dir / "p").glob("s*"):  # a second call in one test starts clean
            shutil.rmtree(old, ignore_errors=True)
        self.sub(a[0], "x1", agent, "1-a", 0, self.span(*a[1:], "p"))
        self.sub(b[0], "x2", agent, "1-a", 0, self.span(*b[1:], "q"))
        text = self.tokens()
        return [l for l in text[text.index("## Flagged\n"):].splitlines() if "two sessions" in l]

    def test_two_sessions_flag(self):
        hm = lambda t: datetime.fromtimestamp(self.t + t).strftime("%H:%M")
        got = self.two_sessions(("s1", 0, 600, 3), ("s2", 300, 1200, 1))  # overlap; the shorter (10 min) run cost $3
        self.assertEqual(len(got), 1)
        self.assertIn(f"two sessions: scrum-builder {hm(0)}-{hm(600)} and {hm(300)}-{hm(1200)}, wasted $3.00", got[0])

    def test_two_sessions_not_flagged_without_overlap_or_with_one_parent(self):
        self.assertEqual(self.two_sessions(("s1", 0, 600, 3), ("s2", 900, 1200, 1)), [])  # no overlap
        self.assertEqual(self.two_sessions(("s1", 0, 600, 3), ("s1", 300, 1200, 1)), [])  # one parent session
        self.assertEqual(len(self.two_sessions(("s1", 0, 600, 3), ("s2", 300, 1200, 1), agent="scrum-review-ui")), 1)

    def two_agents(self, runs, jobs=("1-a",)):
        """runs: (parent, agent, job, t0, t1, usd[, meta]) tuples; returns the `two agents` lines of ## Flagged."""
        self.board_jobs(*[(j, None) for j in jobs])
        self.jobs_txt(*jobs)
        for old in (self.dir / "p").glob("s*"):
            shutil.rmtree(old, ignore_errors=True)
        for i, (sid, agent, job, t0, t1, usd, *meta) in enumerate(runs):
            self.sub(sid, f"y{i}", agent, job, 0, self.span(t0, t1, usd, f"r{i}_"), meta=not meta)
        text = self.tokens()
        flagged = text[text.index("## Flagged\n"):] if "## Flagged\n" in text else ""
        return [l for l in flagged.splitlines() if "two agents" in l]

    def test_two_agents_flag(self):
        hm = lambda t: datetime.fromtimestamp(self.t + t).strftime("%H:%M")
        runs = [("s1", "scrum-builder", "1-a", 0, 600, 3), ("s1", "scrum-builder", "1-a", 300, 1200, 1)]
        got = self.two_agents(runs)
        self.assertEqual(len(got), 1)
        self.assertIn(f"two agents: scrum-builder {hm(0)}-{hm(600)} and {hm(300)}-{hm(1200)}, wasted $3.00", got[0])
        text = self.tokens()
        self.assertIn("1-a", text[text.index("## Flagged\n"):])
        got = self.two_agents([(a, "scrum-review-ui", *r) for a, _, *r in runs])
        self.assertEqual(len(got), 1)
        self.assertIn("two agents: scrum-review-ui ", got[0])

    def test_two_agents_not_flagged_without_overlap_other_parent_or_other_agent(self):
        b = "scrum-builder"
        self.assertEqual(self.two_agents([("s1", b, "1-a", 0, 600, 3), ("s1", b, "1-a", 900, 1200, 1)]), [])
        self.assertEqual(self.two_agents([("s1", b, "1-a", 0, 600, 3), ("s2", b, "1-a", 300, 1200, 1)]), [])
        self.assertEqual(self.two_agents([("s1", "scrum-review-code", "1-a", 0, 600, 3),
                                          ("s1", "scrum-review-ui", "1-a", 300, 1200, 1)]), [])

    def test_two_agents_keyed_on_prompt_job(self):
        w = "scrum-spec-writer"
        self.assertEqual(self.two_agents([("s1", w, "1-a", 0, 600, 3), ("s1", w, "2-b", 300, 1200, 1)],
                                         jobs=("1-a", "2-b")), [])
        self.assertEqual(self.two_agents([("s1", w, None, 0, 600, 3), ("s1", w, None, 300, 1200, 1)]), [])
        self.assertEqual(self.two_agents([("s1", w, "1-a", 0, 600, 3, "nometa"),
                                          ("s1", w, "1-a", 300, 1200, 1, "nometa")]), [])

    def test_empty_and_missing_inputs(self):
        self.board_jobs(("1-a", None))
        self.jobs_txt()
        self.assertEqual(self.tokens(), "No jobs in this digest\n")
        self.jobs_txt("1-a")
        self.assertEqual(self.tokens(), "No transcript rows for this digest's jobs\n")  # no rows at all
        self.main("s1", "9-z", self.replies([1]))
        self.assertEqual(self.tokens(), "No transcript rows for this digest's jobs\n")  # rows, none listed
        with mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": str(self.dir / "missing")}):
            self.assertEqual(self.tokens(), "No transcript rows for this digest's jobs\n")
        self.main("s2", "1-a", self.replies([1]))
        with mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": ""}), \
                mock.patch.object(board, "transcript_tokens") as tt:
            self.assertEqual(self.tokens(), "No transcript rows for this digest's jobs\n")  # unittest guard
        tt.assert_not_called()
        self.assertEqual(self.fit_calls, [])

    def test_rerun_overwrites(self):
        self.fixture()
        first = self.tokens()
        self.assertEqual(self.tokens(), first)
        self.assertEqual(first.count("## Jobs"), 1)

    def test_digest_start_writes_tokens_and_survives_failure(self):
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)
        (self.root / "digests" / "001").rmdir()
        job_id = board.cmd_new(self.root, "done 0")
        board.cmd_set(self.root, job_id, ["stage=done"], internal=True)
        self.stamp(job_id, "feature.md", self.t - 60)  # created before its rows
        self.main("s1", job_id, self.replies([1]))
        order = []
        real_waste, real_tokens = board.write_waste, board.write_tokens
        with mock.patch.object(board, "write_waste", side_effect=lambda *a: (order.append("waste"), real_waste(*a))), \
                mock.patch.object(board, "write_tokens", side_effect=lambda *a: (order.append("tokens"), real_tokens(*a))):
            out = board.cmd_digest_start(self.root)
        self.assertEqual(out["id"], "001")
        self.assertEqual(order, ["waste", "tokens"])
        text = (self.root / "digests" / "001" / "tokens.md").read_text()
        self.assertIn(f"- {job_id} · lane standard · +? lines · $1.00 · 40,000 tokens · - tokens per added line\n", text)
        board.cmd_new(self.root, "done 1")
        job2 = board.read_board(self.root)["jobs"][-1]["id"]
        board.cmd_set(self.root, job2, ["stage=done"], internal=True)
        err = io.StringIO()
        with mock.patch.object(board, "write_tokens", side_effect=ValueError("boom")), redirect_stderr(err):
            out = board.cmd_digest_start(self.root)
        self.assertEqual(out["id"], "002")
        self.assertIn("digest-start: tokens: boom\n", err.getvalue())
        self.assertTrue((self.root / "digests" / "002" / "waste.md").exists())
        self.assertFalse((self.root / "digests" / "002" / "tokens.md").exists())

    # Job 1251: tokens per added line, `,` separators, the window start, the 2+ agents share rule, TimeoutExpired.
    def done_job(self, title):
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)
        job_id = board.cmd_new(self.root, title)
        board.cmd_set(self.root, job_id, ["stage=done"], internal=True)
        self.stamp(job_id, "feature.md", self.t - 60)  # created before its rows
        return job_id

    def test_digest_start_writes_tokens_by_agent(self):
        (self.root / "digests" / "001").rmdir()
        job = self.done_job("job c")
        self.added = {job: 100}
        self.main("s1", job, [reply(self.t + 1, "c1", cwd=str(self.repo), input_tokens=400_000)])
        self.sub("s1", "u1", "scrum-review-ui", job, 1,
                 [reply(self.t + 2, "c2", cwd=str(self.repo), input_tokens=600_000)])
        self.assertEqual(board.cmd_digest_start(self.root)["id"], "001")
        text = (self.root / "digests" / "001" / "tokens.md").read_text()
        self.assertIn(
            f"- {job} · lane standard · +100 lines · $5.00 · 1,000,000 tokens · 10,000 tokens per added line\n"
            "  - scrum-review-ui · round 1 · claude-opus-4-5 · $3.00 · 600,000 tokens\n"
            "  - main · round - · claude-opus-4-5 · $2.00 · 400,000 tokens\n", text)
        self.assertIn(f"- {job} · $5.00 · scrum-review-ui ran on claude-opus-4-5, pinned sonnet; top 3 cost; "
                      "scrum-review-ui 60% of job cost\n", text)  # main's 40% is not over agent_share
        self.assertIn("  - peak context: 600,000 tokens\n", text)

    def test_agent_share_skips_jobs_under_min_usd(self):
        self.assertEqual(board.TOKENS_FLAG["agent_share_min_usd"], 1.00)
        m = "claude-opus-4-5"

        def groups(main, agent):
            return {("main", None, m): (1, main), ("scrum-spec-writer", None, m): (1, agent)}
        cheap = board._token_reasons("1-a", 0.51, groups(0.27, 0.24), None, set())  # job 1302: $0.51, 47% agent
        self.assertEqual([r for r in cheap if "of job cost" in r], [])
        dear = board._token_reasons("1-a", 1.00, groups(0.40, 0.60), None, set())  # at the floor: still flagged
        self.assertEqual([r for r in dear if "of job cost" in r], ["scrum-spec-writer 60% of job cost"])

    def test_top_cost_skips_jobs_under_min_usd(self):
        self.assertEqual(board.TOKENS_FLAG["top_cost_min_usd"], 1.00)
        g = {("main", None, "claude-opus-4-5"): (1, 0.33)}
        cheap = board._token_reasons("1-a", 0.33, g, None, {"1-a"})  # job 1327: $0.33, one shop session
        self.assertNotIn("top 3 cost", cheap)
        floor = board._token_reasons("1-a", 1.00, {("main", None, "claude-opus-4-5"): (1, 1.00)}, None, {"1-a"})
        self.assertIn("top 3 cost", floor)  # at the floor: still flagged
        dear = board._token_reasons("1-a", 4.20, {("main", None, "claude-opus-4-5"): (1, 4.20)}, None, {"1-a"})
        self.assertIn("top 3 cost", dear)

    def test_tokens_no_rows_and_no_added(self):
        self.board_jobs(("1-a", None), ("2-b", None), ("3-c", None), ("4-d", None), ("5-e", None))
        self.jobs_txt("4-d", "5-e", "1-a", "3-c", "2-b")
        self.added = {"1-a": 0, "5-e": 3}
        self.main("s1", "1-a", self.replies([1]))
        self.main("s2", "2-b", self.replies([2]))
        self.main("s5", "5-e", self.replies([1]))
        text = self.tokens()
        jobs = text[text.index("## Jobs\n"):text.index("## Flagged\n")]
        self.assertEqual(jobs, (
            "## Jobs\n"
            "- 2-b · lane standard · +? lines · $2.00 · 80,000 tokens · - tokens per added line\n"
            "  - main · round - · claude-opus-4-5 · $2.00 · 80,000 tokens\n"
            "- 5-e · lane standard · +3 lines · $1.00 · 40,000 tokens · 13,333 tokens per added line\n"
            "  - main · round - · claude-opus-4-5 · $1.00 · 40,000 tokens\n"
            "- 1-a · lane standard · +0 lines · $1.00 · 40,000 tokens · - tokens per added line\n"
            "  - main · round - · claude-opus-4-5 · $1.00 · 40,000 tokens\n"
            "- 4-d · no transcript rows\n"
            "- 3-c · no transcript rows\n"
            "\n"))
        flagged = text[text.index("## Flagged\n"):]
        self.assertNotIn("4-d", flagged)
        self.assertNotIn("3-c", flagged)
        self.assertNotIn("% of job cost", flagged)  # a one-agent job is never flagged for one agent's share

    def mocked_row(self, job, ts):
        return {"ts": ts, "model": "claude-opus-4-5", "project": "app", "job": job, "agent": "main", "skill": None,
                "round": None, "transcript": "/t.jsonl", **{k: 0 for k in board.TOKEN_KEYS}, "output_tokens": 40_000}

    def window(self, now):
        calls = []

        def tt(start, end, *rest):
            calls.append((start, end))
            return [self.mocked_row("1-a", end - 1)]
        with mock.patch.object(board, "transcript_tokens", side_effect=tt), \
                mock.patch.object(board.time, "time", return_value=now):
            board.write_tokens(self.root, "001")
        return calls, (self.root / "digests" / "001" / "tokens.md").read_text()

    def stamp(self, job, name, t):
        p = self.root / "jobs" / job / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        os.utime(p, (t, t))

    def test_tokens_window_start(self):
        now = 1_800_000_000  # 2027-01-15T08:00Z
        self.board_jobs(("1-a", None), ("2-b", None), ("3-c", None), ("4-d", None))
        self.jobs_txt("1-a", "2-b", "3-c")
        calls, text = self.window(now)  # no claimed job has a folder: the 7-day floor
        self.assertEqual(calls, [(1_799_395_200, now)])
        self.assertIn("\nWindow: 2027-01-08T08:00+00:00 to 2027-01-15T08:00+00:00\n", text)
        self.stamp("1-a", "feature.md", now - 3600)
        self.stamp("1-a", "spec.md", now - 5 * 86400)  # feature.md wins over an older spec.md
        self.stamp("2-b", "spec.md", 1_799_740_800)  # spec.md only: 2027-01-12T08:00Z, the earliest
        self.stamp("3-c", "feature.md", now - 86400)
        self.stamp("4-d", "feature.md", now - 6 * 86400)  # not claimed
        calls, text = self.window(now)
        self.assertEqual(calls, [(1_799_740_800, now)])
        self.assertIn("\nWindow: 2027-01-12T08:00+00:00 to 2027-01-15T08:00+00:00\n", text)
        self.stamp("3-c", "feature.md", now - 10 * 86400)  # older than the floor
        calls, text = self.window(now)
        self.assertEqual(calls, [(1_799_395_200, now)])
        self.assertIn("\nWindow: 2027-01-08T08:00+00:00 to 2027-01-15T08:00+00:00\n", text)
        self.assertNotIn("Rows: the last", text)

    def test_tokens_skips_read_when_unregistered(self):
        self.board_jobs(("1-a", None))
        self.jobs_txt("1-a")
        other = Path(self.tmp.name).resolve() / "other"
        (other / "scrum").mkdir(parents=True)
        reg = Path(self.tmp.name).resolve() / "machine" / "other.json"
        reg.write_text(json.dumps([str(other)]))
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)}), \
                mock.patch.object(board, "transcript_tokens") as tt:
            self.assertEqual(self.tokens(), "No transcript rows for this digest's jobs\n")
        tt.assert_not_called()

    def test_digest_start_tokens_failure_does_not_stop(self):
        (self.root / "digests" / "001").rmdir()
        for i, err in enumerate([OSError("boom"), board.subprocess.TimeoutExpired(["gh"], 30)]):
            self.done_job(f"done {i}")
            digest = f"00{i + 1}"
            out = io.StringIO()
            with mock.patch.object(board, "write_tokens", side_effect=err), redirect_stderr(out):
                got = board.cmd_digest_start(self.root)
            self.assertEqual(sorted(got), ["id", "jobs", "windows"])
            self.assertEqual(got["id"], digest)
            self.assertIn(f"digest-start: tokens: {err}\n", out.getvalue())
            for name in ("timing.md", "processes.md", "waste.md"):
                self.assertTrue((self.root / "digests" / digest / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
