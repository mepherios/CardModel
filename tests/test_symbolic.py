"""Instruction cards as terms (MATH_CORE phase 0, F5): symbolic execution against the executable semantics."""
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.machine import symbolic as SY


class Symbolic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.mod, _ = SY.module(cls.ctx, "lr35902")
        cls.ex = SY.Executor(cls.ctx, cls.mod)

    def test_terms_agree_with_the_semantics(self):
        r = SY.check(self.ctx, "lr35902", seed=SEED, samples=2)
        bad = {k: v.get("problems") or v.get("reason") for k, v in r["cards"].items()
               if v["status"] not in ("pass", "dispatch")}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertGreaterEqual(r["counts"]["pass"], 511)
        self.assertEqual(r["cards"]["LR35902_CB"]["status"], "dispatch")
        add = self.ex.run("LR35902_80")                        # ADD A,B: A and F as terms, no bus effect
        self.assertEqual(sorted(add["state"]), ["A", "F"])
        self.assertEqual(add["effects"], [])
        got = SY.evaluate(add, {"A": 0xF0, "B": 0x20, "F": 0}, bytes(0x10000))
        self.assertEqual((got["regs"]["A"], got["regs"]["F"]), (0x10, 0x10))      # carry, no half carry
        ret = self.ex.run("LR35902_D8")                        # RET C: the stack reads only when C is set
        self.assertTrue(all(e["guard"] is not None for e in ret["effects"] if e["op"] in SY.READS))

    def test_a_wrong_term_is_caught(self):
        r = SY.check(self.ctx, "lr35902", seed=SEED, samples=2, only=["LR35902_80"])
        res = r["results"]["LR35902_80"]
        wrong = {**res, "state": {**res["state"], "A": ["BIT_AND", ["ADD", res["state"]["A"], ["int", 1]],
                                                        ["int", 255]]}}
        right = SY.evaluate(res, {"A": 1, "B": 2, "F": 0}, bytes(0x10000))
        bad = SY.evaluate(wrong, {"A": 1, "B": 2, "F": 0}, bytes(0x10000))
        self.assertNotEqual(right["regs"]["A"], bad["regs"]["A"])
        import random
        from cardmodel.machine import bench as BN
        from cardmodel.machine import build as Bd
        from cardmodel.machine import native as N
        m = N.load(self.ctx, Bd.module(self.ctx, "lr35902_bench"), N.resolve_engine(self.ctx, "host"))
        card = next(c for c in self.ctx.store.cards("isa") if c.name == "LR35902_80")
        rng = random.Random(SEED)
        st = BN._case_state(rng, card, None)
        out = BN.run_case(m, card, st, rng.randbytes(0x10000))
        init = {k: st[k] for k in self.ex.globals}
        init["PC"] = (st["PC"] + 1) & 0xFFFF
        self.assertEqual(SY.evaluate(res, init, out["_ram_in"])["regs"]["A"], out["A"])
        self.assertNotEqual(SY.evaluate(wrong, init, out["_ram_in"])["regs"]["A"], out["A"])


if __name__ == "__main__":
    unittest.main()
