"""The resource governor: a runaway child is killed at its memory cap, timeouts still raise, parallel work is
bounded, and this process stops itself cleanly before it can exhaust the machine."""
import os
import subprocess
import sys
import unittest

from helpers import ROOT

from cardmodel.engines.ir import Interpreter, IRError
from cardmodel.kernel import resources as R


class ResourcesTest(unittest.TestCase):
    def test_child_over_its_cap_is_killed(self):
        r = R.run([sys.executable, "-c", "x = b'1' * (500 << 20); import time; time.sleep(5)"], timeout=60,
                  mem_cap_mb=150)
        self.assertEqual(r.returncode, -9)
        self.assertIn("killed", r.stderr)
        self.assertIn("MB cap", r.stderr)

    def test_normal_child_and_timeout(self):
        r = R.run([sys.executable, "-c", "print(6 * 7)"], timeout=60)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "42"))
        with self.assertRaises(subprocess.TimeoutExpired):
            R.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)

    def test_parallelism_is_bounded(self):
        p = R.policy()
        self.assertGreaterEqual(p["max_parallel"], 1)
        self.assertLessEqual(p["max_parallel"], max(1, (os.cpu_count() or 2) // 2))
        env = dict(os.environ, CARDMODEL_MAX_PARALLEL="2", PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-B", "-c", "from cardmodel.kernel import resources as R; "
                              "print(R.max_parallel())"], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.stdout.strip(), "2")

    def test_self_cap_stops_cleanly(self):
        env = dict(os.environ, CARDMODEL_SELF_MB="64", PYTHONPATH=str(ROOT))
        code = ("from cardmodel.kernel import resources as R\nx = b'1' * (200 << 20)\n"
                "try:\n    R.guard('test')\nexcept R.MemoryBudget as e:\n    print('stopped:', e)\n")
        out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("stopped:", out.stdout)

    def test_huge_integers_stop_the_interpreter(self):
        fn = {"name": "tower", "params": [{"name": "n", "type": "int"}], "returns": "int", "locals": {"x": "int"},
              "body": [{"k": "assign", "target": "x", "value": ["int", 3]},
               {"k": "while", "cond": ["CMP_GT", ["var", "n"], ["int", 0]],
                "body": [{"k": "assign", "target": "x", "value": ["MUL", ["var", "x"], ["var", "x"]]},
                         {"k": "assign", "target": "n", "value": ["SUB", ["var", "n"], ["int", 1]]}]},
               {"k": "return", "value": ["var", "x"]}]}
        from cardmodel.engines.ir import op_table
        from helpers import model_ctx
        interp = Interpreter({"entry": "tower", "functions": [fn]}, op_table(model_ctx().store))
        self.assertEqual(interp.call("tower", [3]), 3 ** 8)
        with self.assertRaises(IRError):
            interp.call("tower", [40])                      # 3 ** (2 ** 40): stopped at the bit cap


if __name__ == "__main__":
    unittest.main()
