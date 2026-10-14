# Ollama fallback and small-task workers for Trevskills Scrum

Research date: 2026-10-13, refreshed from official docs, repository implementations, and dated developer reports. Uses trevskills-research. This is a recommendation, not an implementation or a successful inference benchmark.

## Recommendation: explicit local workers with a full-local session fallback

Keep the existing Scrum workflow and choose the provider when starting a task. Use Ollama for bounded auxiliary work; keep Claude/Codex for complex planning, security review, and final approval initially. Add a separately selected fully local session for quota exhaustion, continuing from task artifacts rather than silently swapping models inside a long conversation. This recommendation is an engineering inference from existing subprocess boundaries, auxiliary-model prior art, and compatibility reports.

**Confidence:** medium. Native integrations exist and fit the workspace, but no local inference or full pipeline acceptance has been measured here. The machine is an Apple M2 MacBook Air with 16GB unified memory, detected through system_profiler. Context allocation, latency, and quality still need a local benchmark.

## Understand

Feature: preserve Claude/Codex usage by assigning small Scrum tasks to local inference and provide an explicitly selected fallback when hosted usage is exhausted.

Constraints: existing Python stdlib dashboard, Markdown Scrum agents and artifact contracts, current Claude Code orchestrator, Codex secondary review, 16GB unified memory, no unnecessary framework replacement. Local inference must not silently use Ollama cloud models. Existing hooks, web tools, and MCP servers can still access external services.

Search phrasings: Ollama Claude Code Anthropic compatibility; local coding agent small tasks; Codex Ollama tool dispatch; auxiliary weak model routing; local provider quota fallback; Ollama agent context memory.

Workspace evidence: serve.py chooses SCRUM_CLAUDE at startup and starts subprocesses in spawn/estimate. Agents use opus/sonnet aliases. scrum-review-code hardcodes a hosted Codex model. The existing local/run.py overrides all model aliases and the review command for a full-local session; it does not implement per-role hybrid dispatch. No existing Ollama research report was found.

## How the options compare

| | Explicit local workers | Full-local session | Gateway with automatic provider fallback |
|---|---|---|---|
| Prior art | Aider auxiliary model split; native Ollama APIs | Ollama Claude Code and Codex integrations | LiteLLM model groups and fallbacks |
| Fit with current Scrum | Strong for estimates and bounded summaries; agent-stage routing needs explicit process dispatch | Strongest reuse of existing agent runner; current launcher is this mode | Endpoint adapter plus gateway service and credentials |
| Implementation effort (inference) | Small for estimates; moderate for selected pipeline roles | Small integration effort, substantial behavior validation | Highest |
| Quota effect | Local tasks avoid hosted inference; cloud orchestration still consumes quota | Local model inference avoids Claude/Codex usage | Depends on provider credentials and actual routing |
| Main risk | Low-quality output causes expensive retries | Small model struggles with large context or approval decisions | Transcript incompatibility, extra failure modes, API billing confusion |
| Ruled out if | Local results need so much cloud correction that savings disappear | Tools, context, task quality, or latency fail acceptance | It cannot retain the intended auth model or route exact protocols reliably |

### Approach 1: explicit local workers

Start with the estimator in serve.py: it already expects a small JSON result and restricts repository tools. A direct Ollama request can be the lightest runner when supplied a bounded excerpt; when repository tools are necessary, launch a separate local Claude/Codex process with the stage's existing prompt. Treat these as two runner choices, not identical capabilities. Native API workers do not automatically inherit skills, tool permissions, or repository discovery.

Next candidates: a digest of a small, explicit group of job files, test-output summaries, documentation drafting, and one-file code changes with objective tests. Keep broad triage, security verdicts, architectural plans, and merge authority cloud initially. These assignments are our proposed policy, not a claim that every role has been validated locally.

Prior art: Aider explicitly distinguishes main, weak, and editor models and uses auxiliary candidates for commit messages in [aider/models.py](https://github.com/Aider-AI/aider/blob/main/aider/models.py). It also sets Ollama context based on prompt size unless overridden. This supports task-specific model choice, not automatic replacement of an entire agent framework.

### Approach 2: full-local Claude Code or Codex

Ollama documents both [Claude Code integration](https://docs.ollama.com/integrations/claude-code) and [Codex integration](https://docs.ollama.com/integrations/codex). The runner remains responsible for skills and tools; Ollama supplies inference. The native [Anthropic adapter implementation](https://github.com/ollama/ollama/blob/main/anthropic/anthropic.go) converts tool schemas, calls, results, and streaming events. Model names pass through, so aliases need explicit mapping.

Claude aliases change model IDs; the process-level ANTHROPIC_BASE_URL selects the endpoint. Mapping sonnet to a local tag and opus to a Claude tag does not itself create a hybrid provider connection. [Claude model configuration](https://code.claude.com/docs/en/model-config).

Use this as a manual, task-boundary fallback first. A local coding session is separate from the current hosted Codex conversation. The existing local launcher is provisional and has not passed live inference tests from this sandbox.

### Approach 3: a routing gateway

[LiteLLM fallbacks](https://docs.litellm.ai/docs/proxy/reliability) support model-group failover after retries, including rate-limit and context errors; [its Ollama provider](https://docs.litellm.ai/docs/providers/ollama) supplies local-model connectivity. This is a real option if centralized per-model routing becomes necessary. API error fallback does not establish that a gateway can consume remaining Claude/ChatGPT subscription quota; verify authentication separately and assume API-key traffic has its own usage/billing arrangement.

Engineering inference: request-level fallback can bring a long or provider-specific transcript to a small local model. Switching at a completed task boundary with recorded repository state is easier to diagnose. Gateway overhead is unnecessary before local task quality has been established.

OpenCode is another viable runner: [provider.ts](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/provider.ts) separates provider adapters and model configuration. It is not evidence that the current Scrum skill can be moved unchanged, or that automatic cloud-to-local fallback is already available there.

## Model shortlist for this Mac

| Candidate | Verified listing | Proposed use |
|---|---|---|
| [Qwen3.5 4B](https://ollama.com/library/qwen3.5:4b) | Tools; roughly 3.3–4.0GB artifacts depending on backend | First small-task candidate: classification, estimates, summaries |
| [Qwen2.5-Coder 7B](https://ollama.com/library/qwen2.5-coder:7b) | Tools; 4.7GB; advertised 32K context | Preferred coding-specialist baseline for bounded edits |
| [Llama 3.1 8B](https://ollama.com/library/llama3.1) | Tools; 4.9GB; advertised 128K maximum | Compare if already installed; not automatically the best coder |
| [Qwen3-Coder 30B](https://ollama.com/library/qwen3-coder) | Approximately 19GB weights | Exclude as the default on a 16GB machine |

Artifact size is not total runtime memory. Model-family benchmarks do not prove performance of the 4B variant. Start bounded native-API tasks at 8–16K context; that is deliberately a small-task experiment, below Ollama's 64K recommendation for full coding agents. Raising context does not improve unsupported context limits or guarantee memory fit. Measure actual allocation and processor placement using ollama ps. [Context guidance](https://docs.ollama.com/context-length).

## What to borrow

- Main versus auxiliary model roles from [Aider model implementation](https://github.com/Aider-AI/aider/blob/main/aider/models.py).
- Reuse native API translation rather than inventing a second Claude protocol bridge: [Ollama Anthropic adapter](https://github.com/ollama/ollama/blob/main/anthropic/anthropic.go).
- Keep provider/model configuration distinct from runner behavior, as in [OpenCode provider implementation](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/provider.ts).
- Record selected provider, model, duration, attempts, output validation, and test result per task. This logging policy is our inference, not an upstream guarantee.

Implementation links above are moving branch links inspected on the research date; immutable commit permalinks were not established.

## Risks and how to handle them

- Tool discovery succeeds but actual tool execution fails: validate read, allowed write, and test execution in the exact installed runner. A dated [Ollama issue, 2026-09-08](https://github.com/ollama/ollama/issues/18306) reports MCP tools discovered but not offered on the next request. It concerns specific versions, not every Ollama task.
- The agent spends more time processing harness context than doing useful work: start with bounded excerpts and measure end-to-end latency. [Ollama PR #17918, merged 2026-08-22](https://github.com/ollama/ollama/pull/17918) fixes Claude launch token-countdown behavior that invalidated the prompt cache. Confirm installed integration behavior rather than guessing a minimum release.
- RAM pressure or simultaneous workers defeats savings: serialize local tasks and limit loaded models; context and concurrency multiply memory demand. [Ollama FAQ](https://docs.ollama.com/faq). The prior Llama 8B/64K Modelfile should be treated as provisional rather than a proven fit.
- Retries consume more hosted quota than the task would have: allow a bounded local attempt, validate its artifact, escalate once with a short failure summary and repository state. Suggested retry limits are an engineering choice.
- Localhost is mistaken for guaranteed offline inference: avoid cloud tags and consider server-level OLLAMA_NO_CLOUD=1. This setting disables Ollama cloud features; it does not disable external integrations the agent itself invokes. [Ollama FAQ](https://docs.ollama.com/faq).

Community evidence is issue-based and anecdotal, not a comparative model benchmark. Additional reports include [Codex MCP dispatch issue #19871, 2026-04-27](https://github.com/openai/codex/issues/19871) and [OpenCode compaction report #49965, 2026-09-19](https://github.com/anomalyco/opencode/issues/49965). These motivate checks, not blanket product rejection.

The research skill's last30days supplement was unavailable: its free-source network probe failed DNS resolution in this sandbox. No paid research API was used, and ordinary web research is not represented as a completed last30days engine run. No additional paid Codex evaluation was launched.

## What I'd skip, and why

- Replacing the Scrum workflow with OpenCode or Aider immediately: useful alternatives, but a migration adds work before proving local model quality.
- Sending every opus/sonnet stage to one small local model: preserves neither role quality nor predictable task completion.
- Silent mid-session failover: request-level compatibility is weaker evidence than successful task completion.
- Treating a successful greeting or one tool call as a passed Scrum pipeline.

## Sources

Repos inspected 2026-10-13 (metadata available at retrieval time):
- [Ollama](https://github.com/ollama/ollama): approximately 183K stars, MIT; last push retrieved as 2026-10-14 UTC via [GitHub metadata](https://api.github.com/repos/ollama/ollama), within the local research date's UTC window.
- [OpenCode](https://github.com/anomalyco/opencode): approximately 213K stars, MIT; last-push timestamp not established.
- [Aider](https://github.com/Aider-AI/aider): approximately 49.5K stars, Apache-2.0; last-push timestamp not established.

Exact metadata gaps are retained rather than inferred from popularity. Specific code, model listings, dated discussions, and current docs are linked next to their claims above. Official pages had no publication date; they were accessed on the research date.

## Next step

Choose explicit local workers as the initial approach, with full-local mode as the separate fallback. Before implementation, benchmark three tasks using Qwen3.5 4B and Qwen2.5-Coder 7B: one estimator JSON result, one summary with citations to supplied job files, and one small code edit with a deterministic test. Run one worker at a time. Validate output schema, tool behavior where applicable, tests, retry count, duration, and memory allocation. Accept local routing only when task quality and total effort are satisfactory. Retain cloud approval for the pilot.

Suggested pass conditions: estimator produces valid allowed points and a nonempty reason; summary has verifiable source references and no invented facts; code task passes tests and touches only the allowed files. Run each task multiple times to expose inconsistency. Latency thresholds should be agreed for this workstation rather than fabricated from model size.

No implementation changes were made as part of this research. Live Ollama inference remains blocked from this session's sandbox.
