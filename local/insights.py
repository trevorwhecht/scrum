#!/usr/bin/env python3
"""Insight notes for finished scrum jobs, written before the digest trims their folders.

  insights.py SCRUM_DIR [--model M]   -> writes SCRUM_DIR/insights/<job id>.md for each done job that has none

Code computes the facts (lane, rounds, verdicts, checks, local routing). The optional local model adds only 2-5
summary bullets, each citing a file of that job; a bullet citing anything else is dropped. Measured: small models
invent counts, so they never count here. The paid digest reader reads these files (agents/scrum-digest-reader.md).
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route  # noqa: E402

PER_FILE, TOTAL = 4000, 14000  # chars sent to the model: well inside 32K with room for the reply
SUMMARY = ('Summarise what the reviewers and the approver found in the job files below, in 2 to 5 bullets. '
           'Each bullet starts with "- " and ends with the bracketed path of the file it came from, e.g. '
           '[round-1/review-code.md]. Use only facts in the files. Reply with the bullets only.')


def first_line(path):
    try:
        return path.read_text(errors='replace').split('\n', 1)[0].strip()
    except OSError:
        return ''


def facts(job_dir, job):
    rounds = sorted(job_dir.glob('round-*'), key=lambda p: int(p.name.split('-')[1]) if p.name[6:].isdigit() else 0)
    lines = [f'INSIGHTS {job_dir.name}',
             f'Lane: {job.get("lane") or "standard"} · rounds: {len(rounds)} · decision: '
             f'{first_line(job_dir / "decision.md") or "none"} · rework: {"yes" if (job_dir / "rework.md").exists() else "no"}'
             f' · promoted: {first_line(job_dir / "promoted.md") or "no"}']
    for r in rounds:
        reviews = ', '.join(f'{f.stem.removeprefix("review-")} {first_line(f).removeprefix("VERDICT: ")}'
                            for f in sorted(r.glob('review-*.md'))
                            if 'Skipped by orchestrator' not in f.read_text(errors='replace'))
        lines.append(f'{r.name}: check {first_line(r / "check.md").removeprefix("CHECK: ") or "-"} · '
                     f'reviews: {reviews or "-"}')
    counts = Counter()
    for raw in (job_dir / 'routing.log').read_text().splitlines() if (job_dir / 'routing.log').is_file() else []:
        try:
            d = json.loads(raw)
            counts[f'{d["role"]} {d["runner"]} {d["outcome"]}'] += 1
        except (ValueError, KeyError, TypeError):
            continue
    lines.append('Routing: ' + (', '.join(f'{k} ×{v}' for k, v in sorted(counts.items())) or 'none'))
    return lines


def sources(job_dir):
    """{relative path: trimmed text} of the files worth summarising, within TOTAL chars."""
    files = [job_dir / 'decision.md', *sorted(job_dir.glob('round-*/review-*.md')), job_dir / 'rework.md']
    out, used = {}, 0
    for f in files:
        if not f.is_file():
            continue
        text = f.read_text(errors='replace')
        if 'Skipped by orchestrator' in text or used >= TOTAL:
            continue
        out[str(f.relative_to(job_dir))] = text[:min(PER_FILE, TOTAL - used)]
        used += len(out[str(f.relative_to(job_dir))])
    return out


def summary(job_dir, model):
    """Validated bullets from the local model, or [] (no model, no files, or nothing valid)."""
    files = sources(job_dir)
    if not model or not files:
        return []
    prompt = SUMMARY + '\n\n' + '\n\n'.join(f'{path}:\n{text}' for path, text in files.items())
    try:
        reply = route.chat(model, prompt, timeout=300, max_tokens=600)
    except (OSError, ValueError, KeyError):
        return []
    keep = []
    for line in reply.splitlines():
        m = re.match(r'^- (.+?)\s*\[([^\]]+)\]\s*$', line.strip())
        if m and m[2] in files:
            keep.append(f'- {m[1]} [{m[2]}]')
    return keep[:5]


def write(root, job, model=None):
    job_dir = Path(root) / 'jobs' / job['id']
    lines = facts(job_dir, job)
    bullets = summary(job_dir, model)
    if bullets:
        lines += [f'## Findings (local {model}, unverified: check the cited file)', *bullets]
    out = Path(root) / 'insights' / f'{job["id"]}.md'
    out.parent.mkdir(exist_ok=True)
    out.write_text('\n'.join(lines) + '\n')
    return out


def pending(root):
    """Done jobs with a folder, no insights file yet, and not already in a digest (those are trimmed and read), oldest
    first."""
    try:
        jobs = json.loads((Path(root) / 'board.json').read_text())['jobs']
    except (OSError, ValueError, KeyError):
        return []
    digested = {i for f in Path(root).glob('digests/*/jobs.txt') for i in f.read_text().split()}
    return [j for j in jobs if j.get('stage') == 'done' and j['id'] not in digested
            and (Path(root) / 'jobs' / j['id']).is_dir() and not (Path(root) / 'insights' / f'{j["id"]}.md').exists()]


def main(argv=None):
    p = argparse.ArgumentParser(prog='insights.py')
    p.add_argument('scrum', type=Path)
    p.add_argument('--model')
    a = p.parse_args(argv)
    for job in pending(a.scrum):
        print(write(a.scrum, job, a.model))


if __name__ == '__main__':
    main()
