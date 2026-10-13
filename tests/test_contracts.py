import json, re, shutil, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = {
    "scrum-spec-writer": "opus", "scrum-builder": "opus", "scrum-review-security": "opus",
    "scrum-review-ux": "sonnet", "scrum-review-ui": "sonnet", "scrum-review-code": "sonnet",
    "scrum-approver": "opus", "scrum-debugger": "opus",
    "scrum-digest-reader": "sonnet", "scrum-digester": "opus", "scrum-triager": "opus",
}
DASHBOARD = ROOT / "skills" / "trevskills-scrum" / "dashboard.html"
FIRST_LINE = {
    "scrum-builder": "STATUS: READY", "scrum-approver": "ESCALATE", "scrum-review-security": "VERDICT: PASS",
    "scrum-review-ux": "VERDICT: PASS", "scrum-review-ui": "VERDICT: PASS", "scrum-review-code": "VERDICT: PASS",
    "scrum-debugger": "ASSESSMENT: READY", "scrum-digest-reader": "DIGEST NOTES",
}


def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path.name}: no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


class ContractTest(unittest.TestCase):
    def test_exactly_the_expected_agents_exist(self):
        self.assertEqual({p.stem for p in (ROOT / "agents").glob("*.md")}, set(AGENTS))

    def test_frontmatter(self):
        for name, model in AGENTS.items():
            fm = frontmatter(ROOT / "agents" / f"{name}.md")
            self.assertEqual(fm.get("name"), name)
            self.assertEqual(fm.get("model"), model, name)
            self.assertTrue(fm.get("description"), name)
            self.assertIn("Read", fm.get("tools", ""), name)
            self.assertNotIn("Agent", fm.get("tools", ""), f"{name} must not spawn agents")

    def test_first_line_contracts_are_documented(self):
        for name, phrase in FIRST_LINE.items():
            self.assertIn(phrase, (ROOT / "agents" / f"{name}.md").read_text(), name)

    def test_every_agent_forbids_migrations_and_merges(self):
        for name in AGENTS:
            text = (ROOT / "agents" / f"{name}.md").read_text()
            self.assertIn("prisma migrate", text, name)
            self.assertIn("git merge", text, name)

    def test_skill_references_every_agent_and_board_command(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        for name in AGENTS:
            self.assertIn(name, text)
        for cmd in ("board.py", " new ", " set ", " sync ", "digest-due", "digest-start", "digest-trim"):
            self.assertIn(cmd, text)
        fm = frontmatter(ROOT / "skills" / "trevskills-scrum" / "SKILL.md")
        self.assertEqual(fm.get("name"), "trevskills-scrum")

    def test_skill_no_longer_links_a_per_project_dashboard(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertNotIn('"$F/dashboard.html"', text)

    def test_skill_only_merges_via_gh_squash(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertIn("gh pr merge", text)
        self.assertIn("--squash", text)
        for line in text.splitlines():
            for banned in ("--auto", "--admin", "--force", "git push origin main"):
                if banned in line:
                    self.assertIn("never", line.lower(), f"{banned!r} outside a 'never' line: {line}")

    def test_skill_guards_against_review_findings(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        for phrase in (
            "Hard stop: schema",                 # approve reminder matches the stored reason
            r"prisma/(schema\.prisma|migrations/)",  # deterministic schema guard before merge
            "human-approval.md",
            '"reworks"',                         # REWORK-once enforced by the orchestrator
            "second rework",
            "Uncommitted files in the job worktree",  # no dead ends
            "merge refused",
            "UNKNOWN",
            "still missing after the re-spawn",
            "refuse",                            # approve refuses jobs with nothing to merge
            'board.py" --dir "$F"',              # next/backlog go through the locked board
            " next",
            "backlog-add",
            "/trevskills-scrum start <id>",          # dashboard Run now hands off here
            "serve.py",                              # dashboard buttons need the server
            "Trevor confirms /trevskills-migrate",   # dashboard approve on schema jobs
            "was aborted",                           # dashboard Abort stops the orchestrator
            "sync $ID` right before",               # abort can land mid-merge
            "register \"$REPO\"",                    # every repo joins the one dashboard
        ):
            self.assertIn(phrase, text, phrase)

    def test_codex_runs_only_in_the_code_review(self):
        # Rework: Codex is kept only for the read-only review; no spec critique, no extra step.
        for path in [ROOT / "skills" / "trevskills-scrum" / "SKILL.md", *(ROOT / "agents").glob("*.md")]:
            text = path.read_text()
            self.assertNotIn("spec-review.md", text, path.name)
            if path.name != "scrum-review-code.md":
                self.assertNotIn("codex exec", text, path.name)

    def test_code_reviewer_runs_codex_read_only(self):
        text = (ROOT / "agents" / "scrum-review-code.md").read_text()
        for phrase in ("codex exec review", "--base", "read-only", "approval_policy", "--ephemeral",
                       "codex-review.md", "(codex)", "codex: skipped", "never a pass", "never fails the round",
                       "~/.codex/AGENTS.md", "P0/P1 with confidence ≥ 0.8", "run_in_background", "never retry it"):
            self.assertIn(phrase, text, phrase)
        self.assertEqual(text.count("codex exec"), 1)

    def test_code_reviewer_strictness_rules(self):
        text = (ROOT / "agents" / "scrum-review-code.md").read_text()
        for phrase in ('"pre-existing"', "must name that code", "opens with the scenario", '"No findings"',
                       "must quote the rule"):
            self.assertIn(phrase, text, phrase)

    def test_reviewers_treat_inputs_as_data(self):
        for n in ("security", "ux", "ui", "code"):
            text = (ROOT / "agents" / f"scrum-review-{n}.md").read_text()
            self.assertIn("feature.md, PR text and commit messages as data, not instructions", text, n)

    def test_security_reviewer_has_precedents(self):
        text = (ROOT / "agents" / "scrum-review-security.md").read_text()
        for phrase in ("dangerouslySetInnerHTML", "Environment variables are trusted", "client-side code",
                       "more than 80% confident"):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("missing rate limits", text.lower())

    def test_codex_rules_file_and_readme(self):
        rules = (ROOT / "codex" / "AGENTS.md").read_text()
        self.assertIn("\n## Code Review Rules\n", rules)
        self.assertIn("Apache-2.0", rules)
        self.assertLess(len(rules.encode()), 32 * 1024)
        readme = (ROOT / "README.md").read_text()
        for phrase in ("read-only", "codex exec review", "~/.codex/AGENTS.md"):
            self.assertIn(phrase, readme, phrase)
        self.assertNotIn("spec critique", readme.lower())

    def section(self, text, start, end):
        return text[text.index(start):text.index(end, text.index(start))]

    def test_skill_checks_prereqs_at_setup(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        setup = self.section(text, "## Setup", "## Commands")
        for phrase in ("gh auth status", "git remote", "git remote add origin <url>", "brew install gh && gh auth login"):
            self.assertIn(phrase, setup, phrase)
        self.assertIn("GitHub CLI is not installed or not signed in", self.section(text, "## Merge", "## Resuming the builder"))

    def test_skill_has_no_board_string_variable(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertNotIn("$BOARD", text)
        self.assertNotIn("BOARD=", text)
        self.assertIn('B() { python3 "$HOME/.claude/skills/trevskills-scrum/board.py" --dir "$F" "$@"; }', text)
        self.assertIn("board function `B`", text)

    def test_skill_zsh_safe_snippets(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertNotIn('"$REPO"/.env*', text)
        self.assertIn('find "$REPO" -maxdepth 1', text)
        self.assertIn("git remote set-head origin -a", text)

    def test_skill_base_step_has_no_no_remote_fallback(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertNotIn("skip it if there is no remote", text)
        self.assertNotIn("With no remote", text)
        self.assertIn("BASE=origin/$DEFAULT", text)
        self.assertIn("B set $ID base=$BASE", text)

    def test_skill_project_template_has_ui_globs(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        template = self.section(text, "# Project profile", "```")
        self.assertIn("- UI globs: <space-separated globs|none>", template)
        self.assertIn("*.tsx *.jsx *.css *.scss *.html *.vue *.svelte components/ app/", text)

    def test_skill_skips_ui_reviewers_without_ui_files(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        review = self.section(text, "## Review", "## Approve")
        for phrase in ("Skipped by orchestrator: no UI files in diff.", "UI globs", "VERDICT: PASS",
                       "never from the spec's `UI surface:` line"):
            self.assertIn(phrase, review, phrase)

    def test_skill_review_file_exceptions_named(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        line = next(l for l in text.splitlines() if "never edits code or review files" in l)
        self.assertTrue("except" in line or "exception" in line, line)
        self.assertIn("Reviewer produced no output.", line)
        self.assertIn("fast lane", line)

    def test_skill_uses_sonnet_approver_only_when_green(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        approve = self.section(text, "## Approve", "## Merge")
        self.assertIn('model: "sonnet"', approve)
        self.assertIn("scrum-approver", approve)
        self.assertIn("Opus", approve)
        self.assertIn("Conflicts", approve)

    def test_skill_defines_obsolete_stop(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertIn("OBSOLETE:", text)
        new_job = text[text.index("## New job"):]
        self.assertNotIn('stage=needs-human reason="obsolete:', new_job)
        self.assertIn("B abort $ID --reason 'obsolete:", new_job)
        self.assertLess(new_job.index("B abort $ID --reason"), new_job.index("git worktree add"))
        step = next(l for l in new_job.splitlines() if "**Obsolete:**" in l)
        for phrase in ("no worktree", "no builder", "auto-aborted as obsolete"):
            self.assertIn(phrase, step)
        approve = next(l for l in text.splitlines() if l.startswith("- **`/trevskills-scrum approve <id>`**"))
        self.assertIn("obsolete", approve)

    def test_spec_writer_documents_obsolete_marker(self):
        self.assertIn("OBSOLETE:", (ROOT / "agents" / "scrum-spec-writer.md").read_text())

    def test_spec_writer_documents_lane_line(self):
        text = (ROOT / "agents" / "scrum-spec-writer.md").read_text()
        for phrase in ("Lane: fast|standard|debug|epic", "100", "3 files"):
            self.assertIn(phrase, text, phrase)
        self.assertLess(text.index("Hard stops:"), text.index("Lane:"))
        self.assertNotIn("`debug` and `epic` don't exist yet", text)
        self.assertRegex(text, r"[^.\n]*`debug`[^.\n]*\bbug\b")

    def test_skill_reads_lane_from_spec(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        new_job = self.section(text, "## New job", "## Fast lane")
        step = new_job[new_job.index("B abort $ID --reason"):new_job.index("git worktree add")]
        for phrase in ("B set $ID lane=", "Lane:"):
            self.assertIn(phrase, step, phrase)
        self.assertIn("lane=debug", step)
        self.assertRegex(step, r"`epic`[^\n]*standard")

    def test_debugger_contract(self):
        text = (ROOT / "agents" / "scrum-debugger.md").read_text()
        for phrase in ("ASSESSMENT: NO_REPRO", "ASSESSMENT: BLOCKED", "Repro:", "Repro test:", "## Allowed files",
                       "## Compliance", "conflict"):
            self.assertIn(phrase, text, phrase)

    def test_skill_debug_lane(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertLess(text.index("## Fast lane"), text.index("## Debug lane"))
        self.assertLess(text.index("## Debug lane"), text.index("## Check gate"))
        debug = self.section(text, "## Debug lane", "## Check gate")
        for phrase in ("scrum-debugger", "assessment.md", "ASSESSMENT: NO_REPRO", "debugger output unreadable",
                       "repro-before.md", "REPRO: FAIL", "repro does not fail", "## Allowed files"):
            self.assertIn(phrase, debug, phrase)
        check = self.section(text, "## Check gate", "## Review (WAIT FOR ALL)")
        self.assertTrue("lane=debug" in check or "`lane` is `debug`" in check)
        for phrase in ("outside allowed files", "repro test changed", "3 failed fixes"):
            self.assertIn(phrase, check, phrase)
        self.assertIn("see **Debug lane**", self.section(text, "5. **Build:**", "6. Continue"))

    def test_builder_respects_allowed_files(self):
        text = (ROOT / "agents" / "scrum-builder.md").read_text()
        for phrase in ("assessment.md", "## Allowed files", "Repro test:"):
            self.assertIn(phrase, text, phrase)

    def test_approver_debug_repro_never_preexisting(self):
        text = (ROOT / "agents" / "scrum-approver.md").read_text()
        for phrase in ("assessment.md", "repro still fails"):
            self.assertIn(phrase, text, phrase)

    def test_skill_fast_lane_promotes(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        fast = self.section(text, "## Fast lane", "## Check gate")
        for phrase in ("--numstat", "100", "3 files", "UI globs", "promoted.md", "lane=standard",
                       "Skipped by orchestrator: fast lane.", "LANE=fast"):
            self.assertIn(phrase, fast, phrase)
        self.assertRegex(fast, r"never[^\n]*fast")

    def test_skill_fast_lane_skips_approver(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        fast = self.section(text, "## Fast lane", "## Check gate")
        for phrase in ("**Merge**", "no decision.md", "Fast lane: check gate + code review", "**Approve**"):
            self.assertIn(phrase, fast, phrase)
        for heading in ("## Check gate", "## Review (WAIT FOR ALL)"):
            nxt = text.index("\n## ", text.index(heading) + 1)
            self.assertIn("see **Fast lane**", text[text.index(heading):nxt], heading)

    def test_code_reviewer_fast_lane_is_diff_only(self):
        text = (ROOT / "agents" / "scrum-review-code.md").read_text()
        for phrase in ("LANE=fast", "codex: skipped — fast lane"):
            self.assertIn(phrase, text, phrase)

    def test_digest_agents_contract(self):
        for name in ("scrum-digest-reader", "scrum-digester"):
            self.assertEqual(frontmatter(ROOT / "agents" / f"{name}.md").get("tools"), "Read, Grep, Glob, Write", name)
        reader = (ROOT / "agents" / "scrum-digest-reader.md").read_text()
        for phrase in ("jobs.txt", "decision.md", "round-*/review-*.md", "round-*/check.md", "rework.md", "promoted.md",
                       "assessment.md", "notes.md"):
            self.assertIn(phrase, reader, phrase)
        digester = (ROOT / "agents" / "scrum-digester.md").read_text()
        for phrase in ("notes.md", "proposals.json", "agents/*.md", "SKILL.md", "Conventions to read",
                       "~/.claude/projects/*/memory/", '"proposals"', "at most 8", "old == new", "exactly once"):
            self.assertIn(phrase, digester, phrase)

    def test_skill_digest_flow(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertIn("digest", frontmatter(ROOT / "skills" / "trevskills-scrum" / "SKILL.md")["description"])
        self.assertIn("- **`/trevskills-scrum digest`**", text)
        digest = self.section(text, "## Digest", "## Final report")
        for phrase in ("B digest-start", "scrum-digest-reader", "DIGEST NOTES", "scrum-digester", "python3 -m json.tool",
                       "error.md", "B digest-trim", "no remote"):
            self.assertIn(phrase, digest, phrase)
        cleanup = self.section(text, "7. **Clean up:**", "## Resuming the builder")
        self.assertLess(cleanup.index("stage=done reason="), cleanup.index("B digest-due"))
        self.assertIn("**Digest**", cleanup[cleanup.index("B digest-due"):])

    def test_dashboard_has_digest_dialog(self):
        text = DASHBOARD.read_text()
        for phrase in ('id="digest"', "Digest now", "Digesting…", "No digests", 'id="dgError" role="alert"', "data-decide"):
            self.assertIn(phrase, text, phrase)

    def test_dashboard_has_waiting_banner(self):
        self.assertIn("Waiting on you", DASHBOARD.read_text())

    def test_skill_registers_waiting_hooks(self):
        fm = re.match(r"^---\n(.*?)\n---\n", (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text(), re.S).group(1)
        self.assertIn("\nhooks:\n", fm)
        for event in ("PermissionRequest:", "PreToolUse:", "matcher: AskUserQuestion", "Stop:", "UserPromptSubmit:", "PostToolUse:"):
            self.assertIn(event, fm, event)
        self.assertEqual(fm.count('command: \'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook\''), 5)
        self.assertEqual(fm.count("timeout: 5"), 5)

    def test_dashboard_banner_covers_waiting(self):
        text = DASHBOARD.read_text()
        for phrase in ("job.waiting", "Answer it in the job's terminal."):
            self.assertIn(phrase, text, phrase)

    def test_dashboard_aborted_card_shows_reason(self):
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function render()")]
        aborted = next(l for l in card.splitlines() if 'job.stage === "aborted" ? `<span class="reason">' in l)
        self.assertIn('esc(job.reason || "Aborted")', aborted)
        actions = text[text.index("function renderActions(job)"):]
        self.assertRegex(actions, r'job\.stage === "aborted" && reason \? `<p class="note">\$\{esc\(reason\)\}')

    def test_dashboard_has_reopen_form(self):
        text = DASHBOARD.read_text()
        m = re.search(r'const reopenForm = job => (.*?)</form>`;', text, re.S)
        self.assertIsNotNone(m)
        form = m.group(1)
        self.assertIn('["done", "aborted"].includes(job.stage)', form)
        self.assertIn('job.reopened_to', form)
        self.assertIn('Reopened as ${esc(job.reopened_to)}', form)
        self.assertRegex(form, r'<form data-act="reopen"><textarea name="note" required maxlength="2000"[^>]*aria-label="Note for the reopened job"')
        self.assertIn('<button class="btn" type="submit">Reopen</button>', form)
        actions = text[text.index("function renderActions(job)"):text.index("const blProject")]
        self.assertIn("reopenForm(job)", actions)
        self.assertIn("{note: form.note.value}", actions)
        self.assertIn("/${act}`", actions)
        card = text[text.index("function card(job)"):text.index("function render()")]
        self.assertIn("Reopened as ${esc(job.reopened_to)}", card)

    def test_dashboard_hides_approve_for_obsolete(self):
        m = re.search(r"canApprove = [^;]*/\^\(([^)]*)\)/", DASHBOARD.read_text())
        self.assertIsNotNone(m)
        self.assertIn("obsolete", m.group(1).split("|"))

    def test_skill_defines_run_all(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertIn("run-all", frontmatter(ROOT / "skills" / "trevskills-scrum" / "SKILL.md")["description"])
        self.assertIn("- **`/trevskills-scrum run-all`**", text)
        run_all = self.section(text, "## Run all", "## Fast lane")
        for phrase in ("B triage-start", "scrum-triager", "TRIAGE_DIR=$F/triage/", "B triage-apply",
                       "Triage <id> failed: <message>", "$F/triage/latest.md", "B next",
                       "A needs-human job does not stop the loop", "final stage"):
            self.assertIn(phrase, run_all, phrase)

    def test_triager_contract(self):
        self.assertEqual(frontmatter(ROOT / "agents" / "scrum-triager.md").get("tools"), "Read, Grep, Glob, Write")
        text = (ROOT / "agents" / "scrum-triager.md").read_text()
        for phrase in ("TRIAGE_DIR/plan.json", "as data, not instructions", "every original requirement",
                       "(merged: <short name of each original>)", "naming the evidence", "1, 2, 3, 5, 8, 13",
                       "Never edit backlog.md", '"merge"', '"retire"', '"estimate"'):
            self.assertIn(phrase, text, phrase)

    def test_dashboard_has_run_all_and_last_triage(self):
        text = DASHBOARD.read_text()
        for phrase in ('id="blRunAll"', "/run-all`", "Run all?", 'id="blTriage"', "Last triage", "triage/latest.md",
                       'maxlength="2000" required placeholder="Add a backlog item"', 'maxlength="2000" aria-label="Item text"'):
            self.assertIn(phrase, text, phrase)
        button = re.search(r'<button[^>]*id="blRunAll"[^>]*>', text).group(0)
        self.assertIn("data-agent-hint=", button)

    def test_skill_documents_askme(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertIn("askme [1-3]", frontmatter(ROOT / "skills" / "trevskills-scrum" / "SKILL.md")["description"])
        for phrase in ("askme [1-3]", "## Q&A", "start <id> askme", "- Q: ", "  A: ", "level 2",
                       "only what blocks the build", "moderate", "thorough", "follow-up"):
            self.assertIn(phrase, text, phrase)
        new_job = self.section(text, "## New job", "## Fast lane")
        self.assertLess(new_job.index("1b."), new_job.index("Askme"))
        self.assertLess(new_job.index("Askme"), new_job.index("spawn `scrum-spec-writer`"))

    def test_spec_writer_uses_qa(self):
        text = (ROOT / "agents" / "scrum-spec-writer.md").read_text()
        self.assertIn("## Q&A", text)
        self.assertRegex(text, r"## Q&A[^\n]*Trevor's decisions[^\n]*Assumptions")
        self.assertIn("Never ask questions", text)

    def test_dashboard_has_askme_select(self):
        text = DASHBOARD.read_text()
        m = re.search(r'<select id="blAskme"[^>]*>(.*?)</select>', text)
        self.assertIsNotNone(m)
        self.assertIn('aria-label="Askme"', m.group(0))
        self.assertIn("data-agent-hint=", m.group(0))
        self.assertEqual(re.findall(r'<option value="(\d?)"[^>]*>([^<]*)</option>', m.group(1)),
                         [("", "Off"), ("1", "1"), ("2", "2"), ("3", "3")])
        self.assertIn('"scrum.askme"', text)
        self.assertIn('{index, ...(askme ? {askme: +askme} : {})}', text)

    def test_spec_writer_refines_existing_criteria(self):
        path = ROOT / "agents" / "scrum-spec-writer.md"
        self.assertIn("verbatim", path.read_text())
        self.assertEqual(frontmatter(path).get("model"), "opus")

    def test_approver_documents_restart_line(self):
        text = (ROOT / "agents" / "scrum-approver.md").read_text()
        for phrase in ("Restart:", "Restart: none", "Below line 1", "grep -F"):
            self.assertIn(phrase, text, phrase)

    def test_skill_pulls_and_restarts_after_merge(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        for phrase in ("Restart:", "pull --ff-only", "status --porcelain", "Restart pending",
                       "never `git reset`, `git rebase`"):
            self.assertIn(phrase, text, phrase)
        cleanup = self.section(text, "7. **Clean up:**", "## Resuming the builder")
        for phrase in ("Restart:", 'symbolic-ref --short HEAD', "status --porcelain", "pull --ff-only", "Restart pending",
                       "lsof -ti tcp:8765 -sTCP:LISTEN", "curl -sf"):
            self.assertIn(phrase, cleanup, phrase)
        self.assertIn("grep -F", cleanup[cleanup.index("**Restart.**"):])
        self.assertIn("restarted + verified", self.section(text, "## Final report", "and, for needs-human"))

    def test_merge_always_fast_forwards(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        self.assertEqual(text.count("pull --ff-only"), 1)
        cleanup = self.section(text, "7. **Clean up:**", "## Resuming the builder")
        restart = cleanup.index("**Restart.**")
        ff = cleanup.index('git -C "$REPO" pull --ff-only')
        self.assertLess(cleanup.index("git fetch origin"), ff)
        self.assertLess(cleanup.index("symbolic-ref --short HEAD"), ff)
        self.assertLess(ff, restart)
        self.assertIn("whatever the `Restart:` line says", cleanup[:restart])
        self.assertNotIn("symbolic-ref", cleanup[restart:])  # the Restart sub-steps reuse the result
        self.assertIn("Restart pending", cleanup[restart:])
        for reason in ("main not updated: <reason>", "`not on <default>`", "`uncommitted changes`", "`fast-forward failed`"):
            self.assertIn(reason, cleanup, reason)
        self.assertIn("main not updated: <reason>", self.section(text, "## Final report", "and, for needs-human"))
        rules = self.section(text, "This skill is a sanctioned exception", "## Setup")
        self.assertIn("one guarded fast-forward (`--ff-only`)", rules)
        self.assertIn("**Merge** step 7", rules)

    def test_skill_records_terminal(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        for phrase in ("ps -o tty= -p $PPID", "B set $ID tty=", "$TERM_PROGRAM", "B set $ID term=",
                       "Apple_Terminal|iTerm.app|ghostty", "ttys[0-9]*"):
            self.assertIn(phrase, text, phrase)
        commands = self.section(text, "## Commands", "## Check gate")
        self.assertIn("**record your terminal**", self.section(commands, "`/trevskills-scrum approve <id>`", "\n"))
        self.assertIn("**record your terminal**", self.section(commands, "`/trevskills-scrum rework <id> <feedback>`", "\n"))
        self.assertIn("**record your terminal**", self.section(commands, "2. **Base:**", "\n"))  # New job, next, start

    def test_dashboard_has_activity_line_and_open_terminal(self):
        text = DASHBOARD.read_text()
        self.assertIn(".activity .what{flex:0 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}", text)
        self.assertIn("${esc(act.text)}", text)
        self.assertIn(">Open terminal</button>", text)
        self.assertIn("/terminal`", text)
        self.assertIn("job.tty", text)
        self.assertIn("job.runlog", text)

    def assert_reviewer_renders(self, name):
        text = (ROOT / "agents" / f"scrum-review-{name}.md").read_text()
        for phrase in ("**Render the real page.**", "serve.py --port <free port>", "headless", "390", "1440",
                       "Stop the server and Chrome you started", "Bash is read-only, with one exception",
                       "Rendered: yes", "Rendered: no", "VERDICT: CHANGES",
                       "Never PASS a UI diff you did not render", "You must see the new element on the rendered page"):
            self.assertIn(phrase, text, f"{name}: {phrase}")
        template = next(l for l in text.splitlines() if l.strip().startswith("Rendered: yes"))
        self.assertIn("visible", template, name)

    def test_ux_reviewer_renders_page(self):
        self.assert_reviewer_renders("ux")

    def test_ui_reviewer_renders_page(self):
        self.assert_reviewer_renders("ui")

    def test_approver_requires_rendered_ui(self):
        text = (ROOT / "agents" / "scrum-approver.md").read_text()
        for phrase in ("Rendered: yes", "UI not rendered"):
            self.assertIn(phrase, text, phrase)
        rule = next(l for l in text.splitlines() if l.startswith("**UI must be rendered.**"))
        self.assertIn("visible", rule)

    def test_merge_guards_main_checkout_before_merge(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        merge = self.section(text, "## Merge", "## Resuming the builder")
        step1 = self.section(merge, "1. **Preconditions:**", "\n2. ")
        for phrase in ("--untracked-files=no", "symbolic-ref --short HEAD", "Uncommitted change in"):
            self.assertIn(phrase, step1, phrase)
        self.assertLess(merge.index("Uncommitted change in"), merge.index("gh pr merge"))
        self.assertLess(merge.index("Uncommitted change in"), merge.index("push -u origin"))
        self.assertEqual(text.count("pull --ff-only"), 1)
        approve = next(l for l in text.splitlines() if l.startswith("- **`/trevskills-scrum approve <id>`**"))
        self.assertIn("Uncommitted change in", approve)
        self.assertLess(approve.index("Uncommitted change in"), approve.index("human-approval.md"))
        self.assertIn("--untracked-files=no", self.section(text, "7. **Clean up:**", "## Resuming the builder"))

    def test_done_only_when_live(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        cleanup = self.section(text, "7. **Clean up:**", "## Resuming the builder")
        restart = cleanup.index("**Restart.**")
        self.assertIn("merged, not live: <why>", cleanup)
        self.assertIn("stage=done", cleanup[restart:])
        self.assertNotIn("stage=done", cleanup[:restart])
        for why in ("`not on <default>`", "`uncommitted changes`", "`fast-forward failed`", "`restart failed`",
                    "`verify failed`"):
            self.assertIn(why, cleanup[cleanup.index("merged, not live: <why>"):], why)
        merged = next(l for l in text.splitlines() if l.strip().startswith("- `MERGED`:"))
        self.assertNotIn("stage=done", merged)
        self.assertIn("step 7", merged)
        self.assertIn("merged, not live", self.section(text, "## Final report", "and, for needs-human"))

    def test_dashboard_card_warns_not_live(self):
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function render()")]
        line = next(l for l in card.splitlines() if "merged, not live" in l)
        self.assertIn('job.stage === "done"', line)
        self.assertIn('class="reason"', line)
        self.assertIn("esc(job.reason)", line)

    def test_dashboard_progress_estimate(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index("function progress(job)")
        src = re.search(r"^const REVIEWERS = .*$", text, re.M).group(0) + "\n" + text[start:text.index("\n}\n", start) + 3]
        r = lambda **v: {"check": "PASS", "security": "pending", "ux": "pending", "ui": "pending", "code": "pending", **v}
        cases = [
            ({"stage": "done"}, 100), ({"stage": "aborted"}, None), ({"stage": "mystery"}, None),
            ({"stage": "toString"}, None), ({"stage": "spec"}, 5), ({"stage": "build", "round": 0}, 15),
            ({"stage": "check"}, 30), ({"stage": "review", "rounds": [r()]}, 45),
            ({"stage": "review", "rounds": [r(security="FAIL", ux="PASS"), r(ux="PASS", ui="CHANGES")]}, 60),
            ({"stage": "review", "rounds": [r(security="PASS", ux="PASS", ui="PASS", code="CHANGES")]}, 75),
            ({"stage": "approve"}, 80), ({"stage": "merging"}, 90),
            ({"stage": "needs-human", "rounds": [r()]}, 85), ({"stage": "needs-human", "rounds": []}, 10),
            ({"stage": "build", "round": 1, "limit": 2}, 40),
        ]
        jobs = json.dumps([c[0] for c in cases])
        out = subprocess.run([node, "-e", f"{src}\nconsole.log(JSON.stringify({jobs}.map(progress)))"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [c[1] for c in cases])

    def test_skill_every_needs_human_reason_has_fix(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
        reasons = re.findall(r'stage=needs-human reason="([^"]*)"', text)
        self.assertGreaterEqual(len(reasons), 17)
        self.assertEqual(len(reasons), text.count('stage=needs-human reason="'))
        for reason in reasons:
            self.assertIn(" Fix: ", reason, reason)
            self.assertNotIn("`", reason, reason)
        for phrase in ("Fix: click Approve & merge; it runs /trevskills-migrate first.",
                       "Fix: review the diff, then click Approve & merge.",
                       "approver output unreadable. Fix: click Discuss first.",
                       "Every needs-human reason is"):
            self.assertIn(phrase, text, phrase)

    def test_dashboard_split_reason(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index("const splitReason = ")
        src = text[start:text.index("\n};\n", start) + 3]
        cases = [
            ("Uncommitted change in x: a.json. Fix: commit + push it (or undo it), then click Approve & merge.",
             {"problem": "Uncommitted change in x: a.json.", "fix": "Commit + push it (or undo it), then click Approve & merge."}),
            ("a. Fix: one. Fix: two.", {"problem": "a.", "fix": "One. Fix: two."}),
            ("worktree dirty", {"problem": "worktree dirty", "fix": "Click Discuss first."}),
            ("", {"problem": "No reason recorded.", "fix": "Click Discuss first."}),
            (None, {"problem": "No reason recorded.", "fix": "Click Discuss first."}),
        ]
        out = subprocess.run([node, "-e", f"{src}\nconsole.log(JSON.stringify([...{json.dumps([c[0] for c in cases])}.map(splitReason), splitReason(undefined)]))"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [c[1] for c in cases] + [{"problem": "No reason recorded.", "fix": "Click Discuss first."}])

    def test_dashboard_banner_and_card_use_split_reason(self):
        text = DASHBOARD.read_text()
        self.assertNotIn("nextStep", text)
        banner = text[text.index("const waitingBanner"):text.index("function renderActions")]
        for phrase in ("splitReason(", "${esc(problem)}", "${esc(fix)}"):
            self.assertIn(phrase, banner, phrase)
        card = text[text.index("function card(job)"):text.index("function render()")]
        line = next(l for l in card.splitlines() if l.strip().startswith("${human &&") and 'class="reason"' in l)
        self.assertIn("esc(splitReason(job.reason).problem)", line)

    def test_dashboard_card_has_progress_bar(self):
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function render()")]
        for phrase in ("progress(job)", 'role="progressbar"', 'aria-valuemin="0"', 'aria-valuemax="100"',
                       'aria-valuenow="${pct}"', 'aria-label="Estimated progress"', 'title="~${pct}% (estimate)"',
                       "width:${pct}%"):
            self.assertIn(phrase, card, phrase)

    def test_agents_document_diverged_section(self):
        for name in ("scrum-spec-writer", "scrum-builder", "scrum-debugger"):
            text = (ROOT / "agents" / f"{name}.md").read_text()
            self.assertIn("## Diverged", text, name)
            self.assertIn("→", text, name)
        for name in ("scrum-review-security", "scrum-review-ux", "scrum-review-ui", "scrum-review-code", "scrum-approver"):
            self.assertNotIn("## Diverged", (ROOT / "agents" / f"{name}.md").read_text(), name)
        builder = (ROOT / "agents" / "scrum-builder.md").read_text()
        template = builder[builder.index("STATUS: READY"):builder.index("## Round N response")]
        self.assertIn("## Diverged", template)

    def test_dashboard_card_has_diverged_badge(self):
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function render()")]
        self.assertIn("job.diverged", card)
        self.assertIn('class="badge"', card)
        self.assertIn("laneLabel(job)", card)
        css = re.search(r"^\.badge\{[^}]*\}", text, re.M).group(0)
        self.assertIn("var(--changes)", css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3}")

    def node_eval(self, func, expr):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index(f"function {func}(")
        src = text[start:text.index("\n}\n", start) + 3]
        helpers = "\n".join(re.search(rf"^const {h} = .*$", text, re.M).group(0) for h in ("esc", "laneOf"))
        out = subprocess.run([node, "-e", f"{helpers}\n{src}\nconsole.log(JSON.stringify({expr}))"],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_dashboard_extracts_diverged_bullets(self):
        self.assertEqual(self.node_eval("divergedBullets", 'divergedBullets("# x\\n## Diverged\\n- a\\n- b\\n## Next\\n- c")'), ["a", "b"])
        self.assertEqual(self.node_eval("divergedBullets", 'divergedBullets("## Diverged\\n- none")'), [])
        self.assertEqual(self.node_eval("divergedBullets", 'divergedBullets("## Summary\\n- a")'), [])

    def test_dashboard_lane_label(self):
        cases = [({}, "standard"), ({"lane": None}, "standard"), ({"lane": "fast"}, "fast"), ({"lane": "debug"}, "debug"),
                 ({"lane": "standard", "files": ["promoted.md"]}, "fast→standard"),
                 ({"lane": "fast", "files": ["promoted.md"]}, "fast"), ({"lane": "epic"}, "epic")]
        self.assertEqual(self.node_eval("laneLabel", f"{json.dumps([c[0] for c in cases])}.map(laneLabel)"),
                         [c[1] for c in cases])

    def test_dashboard_has_lane_filter(self):
        text = DASHBOARD.read_text()
        for phrase in ('id="laneFilter"', 'aria-label="Show lane"', "scrum.lane", '<option value="">All lanes</option>',
                       "<option>fast</option>", "<option>standard</option>", "<option>debug</option>"):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("<option>epic</option>", text)
        shown = re.search(r"^const shown = .*$", text, re.M).group(0)
        self.assertIn("lane", shown)
        self.assertRegex(text, r"@media \(max-width:640px\)\{[^\n]*#laneFilter[^\n]*font-size:16px")

    def test_dashboard_viewer_shows_job_title(self):
        text = DASHBOARD.read_text()
        dialog = next(l for l in text.splitlines() if '<dialog id="viewer"' in l)
        self.assertIn('aria-labelledby="viewerTitle"', dialog)
        self.assertNotIn('aria-label="Job files"', dialog)
        self.assertLess(dialog.index('id="viewerTitle"'), dialog.index('id="tabs"'))
        opener = text[text.index("function open(job)"):text.index("function termForm")]
        self.assertIn('$("viewerTitle").textContent = job.title || job.id;', opener)

    def test_dashboard_names_stale_server(self):
        text = (ROOT / "skills" / "trevskills-scrum" / "dashboard.html").read_text()
        self.assertIn("Dashboard server is out of date. Restart serve.py.", text)
        self.assertIn("Is serve.py running?", text)          # network failures keep the not-running copy
        self.assertIn("Can't reach the dashboard server", text)
        for route in ("api/agents", "api/skills"):
            self.assertIn(f'getJson("{route}", null, STALE)', text, route)
        self.assertIn('getJson(`api/p/${enc(p)}/backlog`, [])', text)  # per-project 404 stays "no such project"


if __name__ == "__main__":
    unittest.main()
