#!/usr/bin/env python3
"""Scoped Ollama launcher; leaves global agent configuration untouched."""
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get('SCRUM_LOCAL_MODEL', 'scrum-local')
CONTEXT = int(os.environ.get('SCRUM_LOCAL_CONTEXT', '65536'))
BASE = os.environ.get('SCRUM_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
# --bare drops settings hooks, so the global git/prisma safety hook is restated as deny rules on -p runs.
SAFETY_DENY = ['Bash(git reset:*)', 'Bash(git rebase:*)', 'Bash(git -C * reset:*)', 'Bash(git -C * rebase:*)',
               'Bash(git push --force:*)', 'Bash(git push -f:*)', 'Bash(git push --force-with-lease:*)',
               'Bash(*prisma migrate reset*)', 'Bash(*--accept-data-loss*)', 'Bash(*--force-reset*)',
               'Bash(*prisma db push*)']


def user_deny():
    """permissions.deny from ~/.claude/settings.json; [] when it is missing or unreadable."""
    try:
        deny = json.loads((Path.home() / '.claude' / 'settings.json').read_text())['permissions']['deny']
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return deny if isinstance(deny, list) else []


def preflight(base: str, model: str, context: int) -> None:
    """Load `model` the way the compat endpoint will, then refuse if Ollama gave it less than `context`."""
    load = urllib.request.Request(base + '/api/generate', method='POST',
                                  data=json.dumps({'model': model, 'keep_alive': '10m'}).encode(),
                                  headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(load, timeout=300) as reply:
            reply.read()
        with urllib.request.urlopen(base + '/api/ps', timeout=10) as reply:
            loaded = json.loads(reply.read()).get('models') or []
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SystemExit(f'Ollama preflight failed at {base}: {e}')
    want = model if ':' in model else model + ':latest'  # /api/ps always reports the tag
    entry = next((m for m in loaded if want in (m.get('name'), m.get('model'))), None)
    if entry is None:
        raise SystemExit(f'Ollama preflight: {model} is not loaded after /api/generate')
    if 'context_length' not in entry:
        print(f'warning: Ollama /api/ps reports no context_length for {model}; cannot check it is >= {context}',
              file=sys.stderr)
    elif entry['context_length'] < context:
        raise SystemExit(f'Ollama loaded {model} with context {entry["context_length"]} < {context}; '
                         f'start Ollama with OLLAMA_CONTEXT_LENGTH={context}')

def without_model(args):
    result = []
    iterator = iter(args)
    for arg in iterator:
        if arg in ('-m', '--model'):
            next(iterator)
        elif not arg.startswith(('--model=', '-m=')):
            result.append(arg)
    return result

def main():
    mode, *args = sys.argv[1:]
    if 'cloud' in MODEL.lower():
        raise SystemExit('This launcher requires a local Ollama model, without a cloud tag')
    env = dict(os.environ)
    # Resolve binaries before adding our scoped Codex shim to PATH.
    env.setdefault('SCRUM_REAL_CODEX', shutil.which('codex') or '/opt/homebrew/bin/codex')
    env.setdefault('SCRUM_REAL_CLAUDE', shutil.which('claude') or '/opt/homebrew/bin/claude')
    env['PATH'] = str(HERE / 'bin') + os.pathsep + env.get('PATH', '')
    env['SCRUM_CLAUDE'] = str(HERE / 'bin' / 'claude-local')
    if mode == 'dashboard':
        command = [sys.executable, str(HERE.parent / 'skills/trevskills-scrum/serve.py'), *args]
    elif mode == 'claude':
        settings = {'ANTHROPIC_BASE_URL': BASE,
                    'ANTHROPIC_AUTH_TOKEN': 'ollama', 'ANTHROPIC_API_KEY': '',
                    'ANTHROPIC_MODEL': MODEL, 'CLAUDE_CODE_SUBAGENT_MODEL': MODEL,
                    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
                    'CLAUDE_CODE_MAX_CONTEXT_TOKENS': str(CONTEXT),
                    'CLAUDE_CODE_AUTO_COMPACT_WINDOW': str(CONTEXT * 3 // 4),
                    'DISABLE_PROMPT_CACHING': '1'}
        for alias in ('SONNET', 'OPUS', 'HAIKU', 'FABLE'):
            settings['ANTHROPIC_DEFAULT_' + alias + '_MODEL'] = MODEL
        for key in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
            settings[key] = '0'
        env.update(settings)
        extra, config = [], {'env': settings}
        if '-p' in args or '--print' in args:
            # Claude Code's own prompt, CLAUDE.md, rules, hooks and plugins overflow a 32K local context;
            # --bare skips them, so the prompt must carry everything the run needs.
            extra = ['--bare', '--strict-mcp-config']
            config['permissions'] = {'deny': user_deny() + SAFETY_DENY}
        command = [env['SCRUM_REAL_CLAUDE'], *extra, *without_model(args), '--model', MODEL,
                   '--settings', json.dumps(config)]
    elif mode == 'codex':
        command = [env['SCRUM_REAL_CODEX'], '--oss', '--local-provider', 'ollama',
                   '-m', MODEL, '-c', f'model_context_window={CONTEXT}',
                   '-c', f'model_auto_compact_token_limit={CONTEXT * 3 // 4}',
                   '-c', 'web_search="disabled"', *without_model(args)]
    else:
        raise SystemExit('Usage: local/run.py dashboard|claude|codex [arguments]')
    if mode == 'claude':
        preflight(BASE, MODEL, CONTEXT)
    os.execvpe(command[0], command, env)

if __name__ == '__main__':
    main()
