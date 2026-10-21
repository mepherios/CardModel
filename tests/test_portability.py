"""Runs on anything: every Python 3.9+ interpreter on this machine runs the program (G_A2)."""
import unittest

from helpers import SEED

from cardmodel.engines import selfcheck


class Portability(unittest.TestCase):
    def test_every_python_runs_the_kernel(self):
        res = selfcheck.portability(SEED)
        self.assertTrue(res["runs"], "no Python interpreter found")
        self.assertEqual(res["failures"], [], res)
        self.assertTrue(any(r["status"] == "pass" for r in res["runs"]))


if __name__ == "__main__":
    unittest.main()
