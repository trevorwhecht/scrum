#!/usr/bin/env python3
"""Rank lines of text by relevance to a question using TypeSafe Jev.

usage: some-command | jev-rank.py "what I'm looking for" [--top N] [--min 0.5]
Each stdin line is one item. Prints the top items as "score<TAB>line", best first.
Key: $TYPESAFE_API_KEY, else the macOS Keychain item TypeSafe/typesafe.
"""
import argparse, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # works through the ~/.claude/scripts symlink
import jev  # noqa: E402

BATCH = 20        # items per request (one noul question each)
MAX_CHARS = 1500  # per item; Jev only needs enough to judge relevance


def score_batch(key, query, items):
    answers = jev.ask({"query": query, "items": {str(i): t[:MAX_CHARS] for i, t in enumerate(items)}},
                      {f"q{i}": {"type": "noul",
                                 "instructions": f"Item {i} is relevant to the query and worth reading in full"}
                       for i in range(len(items))}, key=key)
    return [jev.parse_noul(answers.get(f"q{i}")) for i in range(len(items))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min", type=float, default=0.0, help="drop items scoring below this")
    a = p.parse_args()
    lines = [l.rstrip("\n") for l in sys.stdin if l.strip()]
    if not lines:
        return
    batches = [lines[i:i + BATCH] for i in range(0, len(lines), BATCH)]
    try:
        key = jev.api_key()
        with ThreadPoolExecutor(4) as pool:
            scores = [s for b in pool.map(lambda b: score_batch(key, a.query, b), batches) for s in b]
    except jev.JevError as e:
        sys.exit(f"jev-rank: {e}")
    ranked = sorted(zip(scores, lines), key=lambda x: -x[0])
    for s, l in [x for x in ranked if x[0] >= a.min][:a.top]:
        print(f"{s:.2f}\t{l}")


if __name__ == "__main__":
    main()
