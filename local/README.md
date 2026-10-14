# Ollama fallback for Trevskills Scrum

This opt-in launcher runs the existing Claude Code orchestrator and agents using
Ollama's Anthropic-compatible API. The scoped PATH shim also routes the code
reviewer's `codex exec review -m gpt-6.1-sol` invocation to local Codex, replacing
its hard-coded model. This retains the existing skill, tools, and permissions;
it does not convert the orchestration to a new framework. Global settings are
not modified. The Pipelines diagram still displays the agents' original aliases.

## Set up in Terminal

```sh
cd ~/Developer/repos/trevskills-scrum
sysctl -n hw.memsize
ollama pull qwen2.5-coder:7b
ollama pull qwen3.5:4b
launchctl setenv OLLAMA_CONTEXT_LENGTH 32768   # then quit and reopen the Ollama app
ollama list
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b python3 local/diagnose.py
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py codex exec --sandbox read-only --ephemeral 'Reply with local-ok. Do not use tools.'
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py claude -p --allowedTools 'Read,Grep,Glob' 'Reply with local-ok. Do not use tools.'
```

The router uses two models, both named in `local/routing.json`: Qwen2.5-Coder 7B for the
spec writer, the builder and the Codex review, and Qwen3.5 4B for the estimator and the
digest reader. Every routed run asks for a 32K context, so Ollama must load models with
`OLLAMA_CONTEXT_LENGTH=32768`; `run.py` refuses to start a Claude run when Ollama loaded
the model with less (`Ollama loaded <model> with context 4096 < 32768`). Check `ollama ps`
after the probe for heavy offloading.

## How routing decides

`local/route.py <role>` answers `cloud`, `local` or `skip` for one pipeline step, in this order:

1. **Always cloud.** The approver, the security, UI and UX reviewers, the planner, tracker,
   debugger, triager, digester and BigBoy reviewer never run locally, and neither does any role
   missing from `routing.json`.
2. **`SCRUM_ROUTE=cloud`** sends every routed role to cloud.
3. **Trust level** per role in `routing.json`: `off` always runs on cloud; `approved` runs local
   whenever the role is eligible; `trial` runs local when the role is eligible or the job is a
   BigBoy child. The digester proposes a trust flip from `routing.log` evidence.
4. **Eligibility.** The builder only for a `fast`-lane job. The spec writer only when its backlog
   item is pointed at `spec_writer_max_points` (2) or less. The estimator, the digest reader and
   the Codex review are always eligible.
5. **Claude session limit.** When a `scrum/runs/*.log` from the last 24 hours ends with Claude's
   `hit your session limit … resets <time> (<zone>)` line, every `trial` or `approved` role goes
   local until that reset, eligible or not.
6. **Codex quota** (Codex review only). It stays on cloud Codex until the newest
   `~/.codex/sessions/**/rollout-*.jsonl` reports the 5h window at `codex_5h` (85) % used or
   more, or the weekly window at `codex_weekly` (90) % or more. Then it runs local, or is
   skipped when Ollama is not ready.
7. **Ollama health check.** Before any `local` answer, `GET /api/tags` must answer 200 within
   2 s and list the role's model, and the model must not be cloud-tagged. Otherwise the step
   runs on cloud (the Codex review over quota is skipped instead).

`SCRUM_ROUTE=local` forces local for every eligible routed role and for the Codex review
whatever its quota, still only when Ollama is ready. Unset, routing follows the rules above.

**One cloud retry.** A local run that produces no valid artifact (no spec, no build, no
digest notes, no points JSON from the estimator, a timeout or a refused preflight) is retried
once on cloud with the same prompt. A cloud run, or that cloud retry, is never retried again,
and nothing goes back to local. The Codex review never retries: a failed local Codex run is a
skip.

Each attempt appends one JSON line (`ts`, `role`, `runner`, `model`, `duration_s`, `outcome`)
to the job's `routing.log`; estimates and the digest reader log to `scrum/routing.log`.
`outcome` is `ok`, `invalid-artifact`, `fallback` (the cloud retry), `check-pass` or
`check-fail` (a local build at the check gate) or `skipped`. The dashboard shows one tag per
line on the job's card, and its header shows Codex 5h and weekly use and whether Ollama is up
(`GET /api/routing-status`, which runs `route.py status`).

## Switch the dashboard

Stop the existing dashboard server in its original terminal first. If the Dock
app launched it, identify its PID with `lsof -nP -iTCP:8765 -sTCP:LISTEN` and
terminate that specific server with `kill PID`. Let running jobs finish first.
Then:

```sh
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py dashboard
```

Open http://localhost:8765/dashboard.html. All model requests launched by this
server, including estimates and the secondary Codex review, use the local
wrappers. For an interactive Scrum session in any project:

```sh
cd /path/to/project
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 ~/Developer/repos/trevskills-scrum/local/run.py claude
```

Use `/trevskills-scrum` as usual. For a separate local Codex coding session:

```sh
SCRUM_LOCAL_MODEL=qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 ~/Developer/repos/trevskills-scrum/local/run.py codex --sandbox workspace-write
```

To return to the original cloud pipeline, stop the local dashboard and start
`python3 skills/trevskills-scrum/serve.py`, or reopen the Dock app. An already
running dashboard is not reconfigured by opening another launcher. This switch
does not change the backend of an existing Codex desktop conversation.

Scope: model inference is local. Existing hooks, MCP integrations, web tools, and
project commands may still use external services; web research is not provided
by the local model itself. No cloud-tagged Ollama models are used by default.

References: https://docs.ollama.com/integrations/claude-code,
https://docs.ollama.com/integrations/codex,
https://docs.ollama.com/context-length.
