"""witness_runner — run test ids (or the whole suite) and report every test's outcome as one JSON line.

    python3 -B -m cardmodel.cycle.witness_runner [--discover] [ID ...]      (run from the tests folder)

The cycle runs it in a child process (through the resource governor) for two stages: ``laws`` passes the witness
test of every law card, ``tests`` discovers the whole suite. The last line of stdout is ``MARK`` followed by
{test id: {"status": pass|fail|error|skip, "seconds", "detail"}}; a failure in setUpClass is reported under the
class's id ("setUpClass (module.Class)") so the caller can charge it to every test of that class.

Honest limits (L1): a test that kills the interpreter (a segfault, os._exit) loses every outcome after it, and
the caller sees those ids as not reported.
"""
from __future__ import annotations

import json
import sys
import time
import unittest

MARK = "CARDMODEL_WITNESS_RESULT "


class Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows: dict = {}
        self._t0: dict = {}

    def startTest(self, test):
        super().startTest(test)
        self._t0[test.id()] = time.perf_counter()

    def _put(self, test, status: str, detail: str = "") -> None:
        tid = test.id()
        t0 = self._t0.get(tid)
        self.rows[tid] = {"status": status, "seconds": round(time.perf_counter() - t0, 2) if t0 else 0.0,
                          "detail": detail[-1500:]}

    def addSuccess(self, test):
        super().addSuccess(test)
        self._put(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._put(test, "fail", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._put(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._put(test, "skip", str(reason))

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._put(test, "pass", "expected failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._put(test, "fail", "unexpected success")


def main(argv: list[str]) -> int:
    loader = unittest.TestLoader()
    unloadable = {}
    if not argv or argv[0] == "--discover":
        suite = loader.discover(".", pattern="test_*.py")
    else:
        suite = unittest.TestSuite()
        for tid in argv:
            try:
                suite.addTests(loader.loadTestsFromName(tid))
            except Exception as exc:  # noqa: BLE001 -- a missing witness is an outcome, not a crash
                unloadable[tid] = {"status": "error", "seconds": 0.0, "detail": f"cannot load {tid}: {exc}"}
    res = Result()
    t0 = time.perf_counter()
    suite.run(res)
    for err_test, text in res.errors:   # class/module fixtures: not a TestCase, so _put never saw them
        tid = err_test.id() if hasattr(err_test, "id") else str(err_test)
        res.rows.setdefault(tid, {"status": "error", "seconds": 0.0, "detail": text[-1500:]})
    res.rows.update(unloadable)
    out = {"tests": res.rows, "ran": res.testsRun, "seconds": round(time.perf_counter() - t0, 2)}
    print("\n" + MARK + json.dumps(out), flush=True)
    return 0 if res.wasSuccessful() and not unloadable else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
