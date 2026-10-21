"""Self-containment (CM13): the CLI and the test suite run with the original card-model folders unreadable."""
import shutil
import sys
import unittest
from pathlib import Path

from helpers import CLI, ROOT, SEED, TempProject

from cardmodel.engines import selfcheck

# computed at run time from the user's home: the program itself never names these folders
SOURCES = [Path.home() / "Documents" / "Claude_Hub", Path.home() / "Documents" / "Pheros_Studio",
           Path.home() / "Documents" / "rea-main", Path.home() / "Programmering" / "ting",
           Path.home() / "Programmering" / "rea-cards"]


class SelfContained(unittest.TestCase):
    def test_static_no_source_references(self):
        self.assertEqual(selfcheck.static_check(ROOT), [])

    @unittest.skipIf(shutil.which("sandbox-exec") is None, "macOS sandbox-exec not available")
    def test_sources_unreachable(self):
        p = TempProject({"src/m.py": "def tri(n: int) -> int:\n    t = 0\n    for i in range(n):\n        t += i\n"
                                     "    return t\n\ndef twice(cfg):\n    return cfg.get(1) or cfg.get(2)\n",
                         "src/n.py": "def again(cfg):\n    return cfg.get(3)\n"})
        try:
            py = [sys.executable, "-B"]
            cmds = [
                [*CLI, "status"],
                [*CLI, "verify", "--only", "kernel,forms,vectors,rules", "--seed", str(SEED), "--samples", "8"],
                [*CLI, "observe", "src", "--save"],
                [*CLI, "learn", "src", "--promote", "--langs", "python,javascript,c", "--seed", str(SEED)],
                [*CLI, "emit", "--lang", "rust", "src/m.py"],
                [*CLI, "rewrite", "--prove", "(a + b) ** 2", "a ** 2 + 2 * (a * b) + b ** 2"],
                [*py, "-m", "unittest", "-q", "test_kernel", "test_rewrite", "test_probes"],
            ]
            # the unittest run needs tests/ as cwd; the others run in the project
            res = selfcheck.sandbox_check(SOURCES, p.dir, cmds[:-1])
            self.assertTrue(res["effective"], "sandbox did not deny reads: the check would be vacuous")
            self.assertTrue(res["ok"], res)
            res2 = selfcheck.sandbox_check(SOURCES, ROOT / "tests", cmds[-1:])
            self.assertTrue(res2["ok"], res2)
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
