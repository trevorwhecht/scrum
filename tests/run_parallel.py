"""Run the unittest suite in parallel: deal the test ids round-robin into N shards, one `python -m unittest` each.

  python3 tests/run_parallel.py [-j N] [--start DIR]

Ids are the ones `python3 -m unittest discover -s tests` uses (test_board.BoardTest.test_x), so sibling imports such as
`import test_serve` keep working. Exits 0 only when every shard passes.
"""
import argparse, os, subprocess, sys, tempfile, time, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


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
    a = p.parse_args(argv)
    start = a.start.resolve()
    env = dict(os.environ)  # before discovery: the test modules' import-time env writes never reach the shards
    env["PYTHONPATH"] = os.pathsep.join([str(start)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    t0 = time.monotonic()
    ids = list(test_ids(unittest.defaultTestLoader.discover(str(start), top_level_dir=str(start))))
    shards = [ids[i::a.j] for i in range(min(a.j, len(ids)))]
    with ThreadPoolExecutor(max_workers=max(1, len(shards))) as pool:
        results = list(pool.map(lambda s: run_shard(s, env), shards))
    for n, (shard, (code, secs, _)) in enumerate(zip(shards, results), 1):
        print(f"shard {n}/{len(shards)}: {len(shard)} tests {'OK' if code == 0 else 'FAILED'} in {secs:.1f}s")
    for n, (code, _, out) in enumerate(results, 1):
        if code != 0:
            print(f"\n===== shard {n} output =====\n{out}")
    print(f"Ran {len(ids)} tests in {time.monotonic() - t0:.1f}s")
    return 0 if all(code == 0 for code, _, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
