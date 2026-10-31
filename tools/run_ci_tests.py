#!/usr/bin/env python3
"""Run the Python tests that need no game copy, generated code, Metal device or window server.

tests/ci_skip.txt lists the test ids to leave out, one per line, with the reason in a
comment. An id that no longer exists fails the run, so the list cannot go stale. The
tests themselves are unchanged; locally the full suite still runs as before.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def skipped(path=ROOT / 'tests/ci_skip.txt'):
    ids = []
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            ids.append(line)
    return ids


def main():
    sys.path.insert(0, str(ROOT))
    # tests/ is a namespace package, which unittest discovery no longer imports on new Pythons.
    names = sorted('tests.' + path.stem for path in (ROOT / 'tests').glob('test_*.py'))
    tests = list(flatten(unittest.defaultTestLoader.loadTestsFromNames(names)))
    failed = [test for test in tests if isinstance(test, unittest.loader._FailedTest)]
    if failed:
        print('could not import: ' + ', '.join(test.id() for test in failed), file=sys.stderr)
        return 1
    known = {test.id() for test in tests}
    leave_out = skipped()
    unknown = [ident for ident in leave_out if ident not in known]
    if unknown:
        print('unknown test id in tests/ci_skip.txt: ' + ', '.join(unknown), file=sys.stderr)
        return 1
    selected = unittest.TestSuite(test for test in tests if test.id() not in set(leave_out))
    print(f'Running {selected.countTestCases()} of {len(tests)} tests ({len(leave_out)} need local inputs)',
          flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(selected)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
