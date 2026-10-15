#!/usr/bin/env python3
"""One-shot local builder: the scrum-builder's job for a small fast-lane spec, without an agent loop.

  build.py JOB_DIR WORKTREE MODEL [RESUME_TEXT]

Code gathers the context: spec.md, the files under its `## Likely files`, and on a resume the check/review files
the resume text names. One Ollama chat returns SEARCH/REPLACE blocks; they are applied only to those files and
committed on the job branch, and build.md is written. The model never runs a command.
Exit 0 = built. Non-zero = invalid run: the last stderr line is the reason, and the orchestrator retries on cloud.
"""
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route  # noqa: E402

BUDGET = 60000  # chars of file content, ~15K tokens; a bigger file is sent as excerpts around the lines the spec names
PROTECTED = re.compile(r'(^|/)\.env|(^|/)prisma/(schema\.prisma|migrations/)|\.sql$')
BLOCK = re.compile(r'^FILE: *(\S+)\s*\n<<<<<<< SEARCH\n(.*?)^=======\n(.*?)^>>>>>>> REPLACE', re.M | re.S)
RULES = """You are the builder. Implement the spec below by editing the files shown. Change nothing the spec does not ask for.
Reply with edit blocks only, one per change, in exactly this form:

FILE: path/from/repo/root
<<<<<<< SEARCH
exact lines copied from the current file
=======
the new lines
>>>>>>> REPLACE

SEARCH must match the current file exactly, once. Keep each SEARCH small: a few lines around the change.
To create a new file, use an empty SEARCH. Only edit the files listed under FILES."""


def fail(reason):
    sys.exit(f'local build: {reason}')


def section(text, name):
    m = re.search(rf'^## {name}\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return m[1] if m else ''


def likely_files(spec, wt):
    """Repo paths under ## Likely files (in backticks, or a bullet's first word): existing files, or new ones in an
    existing folder."""
    paths, text = [], section(spec, 'Likely files')
    for p in re.findall(r'`([^`\s]+)`', text) + re.findall(r'^- +([^\s`:]+)', text, re.M):
        p = p.split(':')[0].removeprefix('./')
        full = (wt / p).resolve()
        if p in paths or not full.is_relative_to(wt) or not ('/' in p or '.' in p):
            continue
        if full.is_file() or (full.parent.is_dir() and not full.exists() and '.' in full.name):
            paths.append(p)
    return paths


def view(text, spec, per_file):
    """The whole file when it fits per_file chars; else numbered-free excerpts (40 lines each side) around the
    lines holding a backticked spec token, or around `(line N)` hints. None when nothing in the spec points into it."""
    if len(text) <= per_file:
        return text
    lines = text.splitlines()
    tokens = {t for t in re.findall(r'`([^`\n]{4,80})`', spec) if '/' not in t}
    hits = [i for i, line in enumerate(lines) if any(t in line for t in tokens)]
    hits += [int(n) - 1 for n in re.findall(r'line ~?(\d+)', spec) if int(n) <= len(lines)]
    keep = set()
    for i in hits:
        keep.update(range(max(0, i - 40), min(len(lines), i + 41)))
    if not keep:
        return None
    out, prev = [], -2
    for i in sorted(keep):
        if i != prev + 1:
            out.append('... (lines omitted) ...')
        out.append(lines[i])
        prev = i
    return '\n'.join(out)[:per_file]  # ponytail: hard cut; many hits in one big file lose the later ones


def resume_files(text, job_dir):
    """The job's check/review/decision files a resume names, tail-trimmed."""
    out = []
    for p in dict.fromkeys(re.findall(r'(?:JOB_DIR|' + re.escape(str(job_dir)) + r')/([\w./-]+\.md)', text)):
        for f in sorted(job_dir.glob(p)) if '*' in p else [job_dir / p]:
            if f.is_file():
                out.append(f'--- {f.relative_to(job_dir)} ---\n{f.read_text(errors="replace")[-6000:]}')
    return '\n\n'.join(out)


def apply(reply, wt, allowed):
    """Apply every block to its file in memory, then write. Returns the changed paths; raises ValueError on a bad block."""
    blocks = BLOCK.findall(reply)
    if not blocks:
        raise ValueError('reply has no edit blocks')
    texts = {}
    for path, search, replace in blocks:
        path = path.strip('`').removeprefix('./')
        if path not in allowed:
            raise ValueError(f'edit to a file not under Likely files: {path}')
        full = wt / path
        cur = texts.get(path, full.read_text() if full.is_file() else None)
        if cur is None:
            if search.strip():
                raise ValueError(f'SEARCH given for missing file {path}')
            texts[path] = replace
        elif not search.strip():
            raise ValueError(f'empty SEARCH for existing file {path}')
        elif cur.count(search) != 1:
            raise ValueError(f'SEARCH matched {cur.count(search)} times in {path}')
        else:
            texts[path] = cur.replace(search, replace)
    if all(text == ((wt / path).read_text() if (wt / path).is_file() else None) for path, text in texts.items()):
        raise ValueError('the edits change nothing')
    for path, text in texts.items():
        (wt / path).write_text(text)
    return list(texts)


def git(wt, *args):
    return subprocess.run(['git', '-C', str(wt), *args], capture_output=True, text=True, timeout=60)


def main(argv):
    if len(argv) not in (3, 4):
        fail('usage: build.py JOB_DIR WORKTREE MODEL [RESUME_TEXT]')
    job_dir, wt, model = Path(argv[0]).resolve(), Path(argv[1]).resolve(), argv[2]
    resume = argv[3] if len(argv) == 4 else ''
    spec = (job_dir / 'spec.md').read_text() if (job_dir / 'spec.md').is_file() else fail('no spec.md')
    if (job_dir / 'assessment.md').exists():
        fail('debug-lane job: allowed-files rules need the cloud builder')
    allowed = likely_files(spec, wt) or fail('spec.md names no Likely files that exist in the worktree')
    if bad := [p for p in allowed if PROTECTED.search(p)]:
        fail(f'protected path {bad[0]}')
    parts = []
    for p in allowed:
        body = view((wt / p).read_text(errors='replace'), spec, BUDGET // len(allowed)) if (wt / p).is_file() \
            else '(new file)'
        if body is None:
            fail(f'{p} is too large for local and the spec points at no line in it')
        parts.append(f'--- FILE {p} ---\n{body}')
    files = '\n\n'.join(parts)
    prompt = f'{RULES}\n\n=== SPEC ===\n{spec}\n\n=== FILES ===\n{files}'
    if resume:
        prompt += f'\n\n=== FIX REQUEST ===\n{resume}\n\n{resume_files(resume, job_dir)}'
    error = ''
    for _ in range(2):  # ponytail: one local re-ask with the apply error; the cloud retry is the real fallback
        try:
            reply = route.chat(model, prompt + (f'\n\nYour last reply could not be applied: {error}. Reply again.'
                                                if error else ''), timeout=600, max_tokens=4096)
            changed = apply(reply, wt, allowed)
            break
        except (OSError, ValueError, KeyError) as e:
            error = str(e)
    else:
        fail(error)
    git(wt, 'add', '--', *changed)
    title = spec.splitlines()[0].lstrip('# ').strip()[:60]
    done = git(wt, 'commit', '-m', f'{"Fix" if resume else "Build"}: {title}\n\nBuilt locally by {model} (one-shot, no tests run by the builder).')
    if done.returncode:
        fail(f'git commit failed: {(done.stderr or done.stdout).strip().splitlines()[-1:]}')
    sha = git(wt, 'rev-parse', '--short', 'HEAD').stdout.strip()
    build = job_dir / 'build.md'
    if resume and build.is_file():
        note = build.read_text().rstrip() + f'\n\n## Round response (local {model})\n- {resume.splitlines()[0]} — fixed in {sha}: {", ".join(changed)}\n'
    else:
        note = (f'STATUS: READY_WITH_CONCERNS\n## Summary\nOne-shot local build by {model}: edited {", ".join(changed)}.\n'
                f'## Acceptance criteria\n- Not verified by the builder: it runs no commands. The Check gate and the paid code review verify them.\n'
                f'## Rulings\n- Ruling: built locally — fast-lane spec with small Likely files — the Check gate or review sends it back if wrong\n'
                f'## Commits\n- {sha}\n')
    build.write_text(note)
    print(f'local build ok: {sha} {", ".join(changed)}')


if __name__ == '__main__':
    main(sys.argv[1:])
