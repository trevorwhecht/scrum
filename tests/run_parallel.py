"""Run the unittest suite in parallel: deal the test ids round-robin into N shards, one `python -m unittest` each.

  python3 tests/run_parallel.py [-j N] [--start DIR] [TEST_FILE ...]

Ids are the ones `python3 -m unittest discover -s tests` uses (test_board.BoardTest.test_x), so sibling imports such as
`import test_serve` keep working. With TEST_FILE paths (the fast-lane Check gate passes `board.py related-tests`' list)
only those files' ids run; a missing file is refused, and one discovery skips is printed as `not in the suite: <path>`
and runs nothing, as in the full run. After the shards end, each failing test id (from the `FAIL:` and `ERROR:` lines)
is re-run once, alone and serially; one that passes then is printed as `flaky under load: <id>`. Exits 0 only when
every test passed in its shard or on that re-run.
"""
import argparse, os, re, subprocess, sys, tempfile, time, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# `FAIL: name (module.Class.name)` or `ERROR: ...`; a trailing subtest suffix is ignored
FAILED_ID = re.compile(r"^(?:FAIL|ERROR): \S+ \(([^\s()]+)\)", re.M)


def jobs(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def test_ids(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from test_ids(t)
        elif isinstance(t, unittest.loader._FailedTest):
            yield t._testMethodName  # a module that failed to import: its name, so the shard shows the real traceback
        else:
            yield t.id()


def in_module(tid, mod):
    """True when test id `tid` comes from dotted module `mod` (a module that failed to import has its name as id)."""
    return mod is not None and (tid == mod or tid.startswith(mod + "."))


def pick(ids, paths, start):
    """(the ids from the test files at `paths`, in discovery order; the paths no discovered id came from: a file outside
    start, or in a folder discovery skips)."""
    mods = {}
    for path in paths:
        try:
            mods[path] = ".".join(path.resolve().relative_to(start).with_suffix("").parts)
        except ValueError:
            mods[path] = None
    kept = [i for i in ids if any(in_module(i, m) for m in mods.values())]
    return kept, [path for path, m in mods.items() if not any(in_module(i, m) for i in kept)]


def run_shard(ids, env):
    with tempfile.TemporaryFile("w+") as fh:
        start = time.monotonic()
        code = subprocess.run([sys.executable, "-m", "unittest", *ids], cwd=ROOT, env=env, stdout=fh,
                              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
        secs = time.monotonic() - start
        fh.seek(0)
        return code, secs, fh.read()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-j", type=jobs, default=os.cpu_count() or 1, help="worker processes (default: CPU count)")
    p.add_argument("--start", type=Path, default=HERE, help="the test folder to discover (default: tests/)")
    p.add_argument("paths", nargs="*", type=Path, metavar="TEST_FILE", help="run only these files' tests")
    a = p.parse_args(argv)
    for path in a.paths:
        if not path.is_file():
            p.error(f"no such test file: {path}")
    start = a.start.resolve()
    env = dict(os.environ)  # before discovery: the test modules' import-time env writes never reach the shards
    env["PYTHONPATH"] = os.pathsep.join([str(start)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    t0 = time.monotonic()
    ids = list(test_ids(unittest.defaultTestLoader.discover(str(start), top_level_dir=str(start))))
    if a.paths:
        ids, missed = pick(ids, a.paths, start)
        for path in missed:
            print(f"not in the suite: {path}")
    shards = [ids[i::a.j] for i in range(min(a.j, len(ids)))]
    with ThreadPoolExecutor(max_workers=max(1, len(shards))) as pool:
        results = list(pool.map(lambda s: run_shard(s, env), shards))
    for n, (shard, (code, secs, _)) in enumerate(zip(shards, results), 1):
        print(f"shard {n}/{len(shards)}: {len(shard)} tests {'OK' if code == 0 else 'FAILED'} in {secs:.1f}s")
    for n, (code, _, out) in enumerate(results, 1):
        if code != 0:
            print(f"\n===== shard {n} output =====\n{out}")
    ok = all(code == 0 for code, _, _ in results)
    failed = list(dict.fromkeys(i for code, _, out in results if code != 0 for i in FAILED_ID.findall(out)))
    finished = all(code == 0 or re.search(r"^FAILED \(", out, re.M) for code, _, out in results)  # no crashed shard
    if not ok and failed and finished:  # ponytail: one serial re-run each, no known-flaky list
        ok = True
        for tid in failed:
            code, _, out = run_shard([tid], env)
            if code == 0:
                print(f"flaky under load: {tid}")
            else:
                ok = False
                print(f"\n===== re-run {tid} =====\n{out}")
    print(f"Ran {len(ids)} tests in {time.monotonic() - t0:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
