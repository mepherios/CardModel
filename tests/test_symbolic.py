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


    def test_canonical_terms_keep_the_meaning(self):
        # FOUNDATIONS.md D1/D7: registers at their widths (u8, u16) and bus bytes as u8 let the sorted laws simplify
        # the terms; the canonical terms must still agree with the executable semantics on the bench
        import random
        from cardmodel.machine import bench as BN
        from cardmodel.machine import build as Bd
        from cardmodel.machine import native as N
        self.assertEqual(SY.register_sorts(self.ctx, "lr35902")["A"], "u8")
        self.assertEqual(SY.register_sorts(self.ctx, "lr35902")["SP"], "u16")
        add = self.ex.run("LR35902_80")
        canon = SY.distill(self.ctx, "lr35902", add["state"])
        self.assertEqual(canon["state"]["A"], ["BIT_AND", ["ADD", ["var", "A"], ["var", "B"]], ["int", 255]])
        m = N.load(self.ctx, Bd.module(self.ctx, "lr35902_bench"), N.resolve_engine(self.ctx, "host"))
        cards = {c.name: c for c in self.ctx.store.cards("isa")}
        rng = random.Random(SEED)
        names = rng.sample(sorted(n for n in cards if n.startswith("LR35902_") and n != "LR35902_CB"), 40)
        checked = 0
        for name in names:
            try:
                res = self.ex.run(name)
            except SY.Unsupported:
                continue
            d = {**res, "state": SY.distill(self.ctx, "lr35902", res["state"])["state"]}
            for _ in range(3):
                st = BN._case_state(rng, cards[name], None)
                out = BN.run_case(m, cards[name], st, rng.randbytes(0x10000))
                init = {k: st[k] for k in self.ex.globals}
                init["PC"] = (st["PC"] + 1) & 0xFFFF
                got = SY.evaluate(d, init, out["_ram_in"], self.ctx.ops)
                for reg, v in got["regs"].items():
                    self.assertEqual(v, out[reg], (name, reg, seed_note(self)))
                checked += 1
        self.assertGreater(checked, 60)

    def test_distill_certificate_is_reproducible(self):
        # the e-graph's budget cut makes which laws fire depend on set order; the certificate is the whole fired
        # set, sorted, so regenerating the pack under another hash seed gives the same bytes (09 and B0 differed)
        import json, os, subprocess, sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        prog = ("import json, sys; sys.path.insert(0, '.')\n"
                "from cardmodel.engines.context import Ctx\n"
                "from cardmodel.kernel.store import open_store\n"
                "from cardmodel.machine import symbolic as SY\n"
                "ctx = Ctx(open_store(project=False)); ex = SY.Executor(ctx, SY.module(ctx, 'lr35902')[0])\n"
                "print(json.dumps({n: list(SY.distill(ctx, 'lr35902', ex.run(n)['state'])['fired'])\n"
                "                  for n in ('LR35902_09', 'LR35902_B0', 'LR35902_CB_28')}, sort_keys=True))\n")
        outs = [subprocess.run([sys.executable, "-B", "-c", prog], cwd=root, capture_output=True, text=True,
                               env={**os.environ, "PYTHONHASHSEED": str(h)}, check=True).stdout for h in (0, 1)]
        self.assertEqual(json.loads(outs[0]), json.loads(outs[1]))

if __name__ == "__main__":
    unittest.main()
