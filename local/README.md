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
ollama list
sysctl -n hw.memsize
ollama pull llama3.1:8b
ollama create scrum-local -f local/Modelfile
python3 local/diagnose.py
python3 local/run.py codex exec --sandbox read-only --ephemeral 'Reply with local-ok. Do not use tools.'
python3 local/run.py claude -p --allowedTools 'Read,Grep,Glob' 'Reply with local-ok. Do not use tools.'
```

The starting model is Llama 3.1 8B, with tools and a 64K context. Memory use grows
with context; check `ollama ps` after the probe and reduce context or use a smaller
model if it offloads heavily or exhausts memory. Model quality and full pipeline
reliability need validation on a small task before larger unattended builds.
Qwen2.5-Coder 7B is an alternative for smaller coding tasks: pull
`qwen2.5-coder:7b`, change FROM and num_ctx in Modelfile to that model and 32768,
recreate scrum-local, and launch with `SCRUM_LOCAL_CONTEXT=32768`. Its advertised
32K context is below Ollama's recommended 64K for coding agents.

## Switch the dashboard

Stop the existing dashboard server in its original terminal first. If the Dock
app launched it, identify its PID with `lsof -nP -iTCP:8765 -sTCP:LISTEN` and
terminate that specific server with `kill PID`. Let running jobs finish first.
Then:

```sh
python3 local/run.py dashboard
```

Open http://localhost:8765/dashboard.html. All model requests launched by this
server, including estimates and the secondary Codex review, use the local
wrappers. For an interactive Scrum session in any project:

```sh
cd /path/to/project
python3 ~/Developer/repos/trevskills-scrum/local/run.py claude
```

Use `/trevskills-scrum` as usual. For a separate local Codex coding session:

```sh
python3 ~/Developer/repos/trevskills-scrum/local/run.py codex --sandbox workspace-write
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
