# Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `scrum-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.` Pass Agent override `model: "sonnet"` only when `$F/jobs/$ID/jev.log` has a `model` line that decided `sonnet` and no `promote` line; otherwise (jev.log missing included) no override (Opus). It makes no Jev call.
2. Run `B set $ID builder=<new id>`.

In a headless (`claude -p`) session, skip SendMessage: its reply would arrive after the turn ends, and the process exits with it (see **Headless sessions block.**). Resume through step 1 instead (spawn a fresh `scrum-builder` in the foreground and wait for it to return), then step 2.

**Sonnet promotion.** A cloud builder runs as Sonnet while `$F/jobs/$ID/jev.log`'s `model` line decided `sonnet` and it has no `promote` line. On its first `CHECK: FAIL` (**Check gate** step 4) or `VERDICT: CHANGES` round (**Review** step 5), instead of SendMessage:
1. Run `printf '%s\n' '<check-fail round N|changes round N>' | python3 ~/.claude/skills/trevskills-scrum/jev-gate.py promote $F/jobs/$ID` with Bash timeout 90000.
2. Spawn a fresh `scrum-builder` with Agent override `model: "opus"`: step 1's prompt above plus the resume text.
3. Run `B set $ID builder=<new id>`.

A builder already promoted is never promoted again.

Outside the **Lilguy lane**, the orchestrator never edits code or review files itself, except for these sanctioned review files: the UI/UX skip, security skip and `Carried forward from round` files that `B review-plan` writes in **Review** step 2, the `Reviewer produced no output.` fallback, and the fast lane skip files in **Fast lane** step 2.
