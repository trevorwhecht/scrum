#!/usr/bin/env python3
"""Scoped Ollama launcher; leaves global agent configuration untouched."""
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
MODEL = os.environ.get('SCRUM_LOCAL_MODEL', 'scrum-local')
CONTEXT = int(os.environ.get('SCRUM_LOCAL_CONTEXT', '65536'))

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
        settings = {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:11434',
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
        command = [env['SCRUM_REAL_CLAUDE'], *without_model(args), '--model', MODEL,
                   '--settings', json.dumps({'env': settings})]
    elif mode == 'codex':
        command = [env['SCRUM_REAL_CODEX'], '--oss', '--local-provider', 'ollama',
                   '-m', MODEL, '-c', f'model_context_window={CONTEXT}',
                   '-c', f'model_auto_compact_token_limit={CONTEXT * 3 // 4}',
                   '-c', 'web_search="disabled"', *without_model(args)]
    else:
        raise SystemExit('Usage: local/run.py dashboard|claude|codex [arguments]')
    os.execvpe(command[0], command, env)

if __name__ == '__main__':
    main()
