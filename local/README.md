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
# 32K variants (no extra disk): Ollama's Anthropic endpoint ignores per-request context, so it lives in the model
printf 'FROM qwen3.5:4b\nPARAMETER num_ctx 32768\n' | ollama create scrum-qwen3.5:4b -f /dev/stdin
printf 'FROM qwen2.5-coder:7b\nPARAMETER num_ctx 32768\n' | ollama create scrum-qwen2.5-coder:7b -f /dev/stdin
ollama list
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b python3 local/diagnose.py
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py codex exec --sandbox read-only --ephemeral 'Reply with local-ok. Do not use tools.'
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py claude -p 'Reply with local-ok. Do not use tools.' --allowedTools 'Read,Grep,Glob'
```

The router uses two models, both named in `local/routing.json`: Qwen2.5-Coder 7B for the
spec writer, the builder and the Codex review, and Qwen3.5 4B for the estimator and the
digest reader. Every routed run asks for a 32K context, so `routing.json` names the `scrum-`
variants created above, which carry `num_ctx 32768`; `run.py` refuses to start a Claude run when
Ollama loaded the model with less (`Ollama loaded <model> with context 4096 < 32768`). Check
`ollama ps` after the probe for heavy offloading.

A `claude -p` run through `run.py` adds `--bare --strict-mcp-config`: Claude Code's own prompt,
CLAUDE.md, rules, hooks and plugins overflow 32K (`Prompt is too long`), so the prompt must carry
everything the run needs. `--bare` also drops hooks, so `run.py` passes `~/.claude/settings.json`'s
`permissions.deny` plus `SAFETY_DENY` (the global git/prisma hook restated as deny rules). Put the
prompt right after `-p`: `--allowedTools` takes every value after it, and a prompt placed later is
swallowed as a tool name (`Input must be provided ...`).

## What the local models can do (measured 2026-10-15, M2 Air 16 GB)

| Role | Local result | Trust |
| --- | --- | --- |
| Estimator | 26/26 valid, ~2 s each, as one `/api/chat` call with the repo's file list (`serve.local_estimate`) | approved |
| Digest reader | Valid format, wrong content: invents counts and misses or splits the recurring findings (4B and 7B) | off |
| Codex review | 7B prints its tool calls as text and reviews nothing (~3 min) | off |
| Spec writer, builder | Not viable: in a Claude Code agent loop a 4B model fills 32K with tool output and auto-compacts until it gives up | off |

The rule that follows: local work is **one bounded `route.chat` call with the context gathered by
code**, never an agent loop, and anything countable is counted by code, not the model.

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
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 local/run.py dashboard
```

Open http://localhost:8765/dashboard.html. All model requests launched by this
server, including estimates and the secondary Codex review, use the local
wrappers. For an interactive Scrum session in any project:

```sh
cd /path/to/project
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 ~/Developer/repos/trevskills-scrum/local/run.py claude
```

Use `/trevskills-scrum` as usual. For a separate local Codex coding session:

```sh
SCRUM_LOCAL_MODEL=scrum-qwen2.5-coder:7b SCRUM_LOCAL_CONTEXT=32768 python3 ~/Developer/repos/trevskills-scrum/local/run.py codex --sandbox workspace-write
```

To return to the original cloud pipeline, stop the local dashboard and start
`python3 skills/trevskills-scrum/serve.py`, or reopen the Dock app. An already
running dashboard is not reconfigured by opening another launcher. This switch
does not change the backend of an existing Codex desktop conversation.

## Benchmark

Measure the routed models on the three bounded local tasks before trusting a role:

```sh
python3 local/bench.py --runs 3
python3 local/bench.py --model scrum-qwen3.5:4b --task estimate --runs 5
```

Defaults: both models named in `routing.json` `models`, three runs, all three tasks. Requests
go one at a time to `$SCRUM_OLLAMA_URL` (`POST /api/chat` through `route.chat`: thinking off, the model's own 32K context). Each run prints one
JSON line (`model`, `task`, `run`, `pass`, `why`, `duration_s`, and `ps`: `size`, `size_vram`,
`context_length` from `/api/ps`), then one `passed/total` line per model and task. Exit 0 when
every run passed, 1 when any failed, 2 when Ollama is down or a model is missing or cloud-tagged.

- **estimate** passes when the reply holds a JSON object with `points` in 1, 2, 3, 5, 8, 13
  and a non-empty `why`.
- **summary** passes when the reply has 2–5 `- ` bullets and every bullet cites one of the two
  supplied paths (`[jobs/a/feature.md]`, `[jobs/b/spec.md]`) and no other.
- **edit** passes when the reply is `{"path": "calc.py", "content": …}`, `test_calc.py` is
  unchanged afterwards, and `python3 -m unittest test_calc` exits 0 in a temp dir. Any other
  path fails without writing anything.

Duration is recorded, never a pass rule. Run with nothing else loaded, and check `ollama ps`
for CPU offload (a `size_vram` below `size` means part of the model is on the CPU).

## Recovery

When a local run fails partway through a job:

1. Read the job's `routing.log` (`scrum/jobs/<id>/routing.log`) to see which step ran local
   and its `outcome`.
2. Force cloud and resume: start the dashboard or session with `SCRUM_ROUTE=cloud`, then press
   Resume on the job (or resume it from `/trevskills-scrum`).
3. Leave a full-local session: stop the `local/run.py dashboard` server the same way as in
   "Switch the dashboard", then restart `python3 skills/trevskills-scrum/serve.py`.
4. Free memory with `ollama stop <model>` (`ollama ps` lists what is loaded).

`.agents/skills/trevskills-scrum` is the committed symlink that lets Codex discover the scrum
skill from this repo.

Scope: model inference is local. Existing hooks, MCP integrations, web tools, and
project commands may still use external services; web research is not provided
by the local model itself. No cloud-tagged Ollama models are used by default.

References: https://docs.ollama.com/integrations/claude-code,
https://docs.ollama.com/integrations/codex,
https://docs.ollama.com/context-length.
