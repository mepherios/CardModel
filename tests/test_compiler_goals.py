"""The general compiler's goals are computed from the IR and the store (docs/GENERAL_COMPILER.md §6)."""
import re
import unittest

from helpers import ROOT, model_ctx

from cardmodel.engines import compiler_goals as CG
from cardmodel.engines import ir


class CoreForms(unittest.TestCase):
    def test_statements_are_the_interpreters(self):
        """ir.STATEMENTS is exactly the statement kinds Interpreter._block executes, so G_C6 reads the real IR."""
        src = (ROOT / "cardmodel" / "engines" / "ir.py").read_text(encoding="utf-8")
        body = src[src.index("    def _block(self, body, env, depth):"):]
        body = body[:body.index("\n    def ", 10)]
        self.assertEqual(set(re.findall(r'k == "(\w+)"', body)), set(ir.STATEMENTS))

    def test_ten_forms_each_checked_against_the_ir(self):
        st = CG.core_form_status(model_ctx())
        self.assertEqual(len(st), 10)
        for name in ("values", "binding", "functions", "control"):
            self.assertEqual(st[name], [], name)
        self.assertEqual(CG.core_forms_in_ir(model_ctx()), sum(1 for m in st.values() if not m))

    def test_a_missing_requirement_is_named(self):
        st = CG.core_form_status(model_ctx())
        if "record" not in ir.TYPES:
            self.assertIn("type record", st["records"])


class Doors(unittest.TestCase):
    def test_doors_count_fully_witnessed_instruction_sets(self):
        secs = {"machine": {"isas": {"a": {"cards": 3, "passed": 3}, "b": {"cards": 4, "passed": 3}}}}
        self.assertEqual(CG.doors_witnessed(secs), 1)
        self.assertIsNone(CG.doors_witnessed({}))


if __name__ == "__main__":
    unittest.main()
