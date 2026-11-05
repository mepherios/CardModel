"""Op x language conformance through real toolchains (CM17), and proof that it can fail (CM07).

Default run: python, javascript, c (fast). CARDMODEL_SLOW=1 runs every codegen language on this host.
"""
import copy
import unittest

from helpers import SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import conformance
from cardmodel.engines.context import Ctx
from cardmodel.engines.ir import op_table


class Conformance(unittest.TestCase):
    def test_conformance_matrix(self):
        ctx = model_ctx()
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        rep = conformance.matrix(ctx, langs=langs, seed=SEED, samples=8)
        for lang, r in rep["languages"].items():
            if not r["available"]:
                continue
            bad = {n: c for n, c in r["cells"].items() if c["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{lang} {seed_note(self)}")
            self.assertGreater(rep["summary"][lang]["pass"], 20, lang)
        good, total = conformance.rate(rep)
        self.assertEqual(good, total)
        self.assertGreater(total, 0)

    def test_fixed_width_cells(self):
        """FOUNDATIONS §7.3: u8 and i8 overflow, u32 multiplication and f32 rounding pass in every language,
        through wrap-on-store (a store of a u8 is WRAPU(v, 8), of an f32 is F32(v)) -- a pass, never a skip."""
        ctx = model_ctx()
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        rep = conformance.matrix(ctx, langs=langs, seed=SEED, samples=8, ops=["ADD", "MUL"])
        want = ("t_add_u8_u8", "t_add_i8_i8", "t_mul_u32_u32", "t_add_f32_f32", "t_mul_f32_f32")
        for lang, r in rep["languages"].items():
            if not r["available"]:
                continue
            for n in want:
                self.assertEqual(r["cells"][n]["status"], "pass", f"{lang} {n} {r['cells'][n]} {seed_note(self)}")
                self.assertGreater(r["cells"][n]["checks"], 0, f"{lang} {n}")

    def test_fixed_width_reference_wraps(self):
        """The reference semantics wraps on store: 200 + 100 at u8 is 44, 100 + 100 at i8 is -56, and an f32
        sum is the float32 rounding of the exact sum."""
        import struct
        from cardmodel.engines.ir import Interpreter
        ops = op_table(model_ctx().store)
        fns = {f["fn"]["name"]: f["fn"] for f in conformance.op_functions(ops)}

        def run(name, *args):
            return Interpreter({"functions": [fns[name]]}, ops).call(name, list(args))
        self.assertEqual(run("t_add_u8_u8", 200, 100), 44)
        self.assertEqual(run("t_add_i8_i8", 100, 100), -56)
        self.assertEqual(run("t_mul_u32_u32", 2 ** 32 - 1, 2 ** 32 - 1), 1)
        x = struct.unpack("f", struct.pack("f", 0.1))[0]
        self.assertEqual(run("t_add_f32_f32", x, x), struct.unpack("f", struct.pack("f", x + x))[0])
        self.assertNotEqual(run("t_mul_f32_f32", 1.0 + 2 ** -20, 1.0 + 2 ** -20), (1.0 + 2 ** -20) ** 2)

    def test_wrong_template_is_caught(self):
        """C's % truncates; a card that used it for MOD must fail the matrix on negative operands."""
        ctx = model_ctx()
        if not ctx.available("c")[0]:
            self.skipTest("no C compiler on this host")
        ops = copy.deepcopy(op_table(ctx.store))
        ops["MOD"].card["emit"] = dict(ops["MOD"].card["emit"], c_like="({0} % {1})")
        bad = Ctx(ctx.store)
        bad.__dict__["ops"] = ops            # cached_property override: same store, mutated op table
        rep = conformance.matrix(bad, langs=["c"], seed=SEED, samples=24, ops=["MOD"])
        cell = rep["languages"]["c"]["cells"]["t_mod_i_i"]
        self.assertEqual(cell["status"], "fail", f"naive % was not caught {seed_note(self)}")
        a, b = cell["args"]
        self.assertTrue((a < 0) != (b < 0), cell)

    def test_unavailable_language_is_reported(self):
        ctx = model_ctx()
        rep = conformance.matrix(ctx, langs=["python"], seed=SEED, samples=2, ops=["ADD"])
        self.assertTrue(rep["languages"]["python"]["available"])
        lean = ctx.store.get("language/lean")
        self.assertTrue(lean["probe"].get("glob_only"), "lean must never be resolved through the elan proxy")


if __name__ == "__main__":
    unittest.main()
