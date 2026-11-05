"""Op x language conformance through real toolchains (CM17), and proof that it can fail (CM07).

Default run: python, javascript, c (fast). CARDMODEL_SLOW=1 runs every codegen language on this host.
"""
import copy
import math
import random
import struct
import unittest

from helpers import SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import conformance
from cardmodel.engines.codegen import EmitGap, Emitter
from cardmodel.engines.context import Ctx
from cardmodel.engines.ir import op_table
from cardmodel.engines.runners import run_calls, run_program


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


class StdinHarness(unittest.TestCase):
    """Test programs read their arguments from stdin: the values printed are those of baked inputs, bit for bit,
    and a new seed reuses the build (ROADMAP Now, the stdin harness)."""

    def test_stdin_matches_baked_and_reuses_the_build(self):
        ctx = model_ctx()
        langs = [l for l in (ctx.codegen_languages() if SLOW else ("python", "javascript", "c"))
                 if ctx.available(l)[0]]
        fns = {f["fn"]["name"]: f["fn"] for f in conformance.op_functions(ctx.ops)}

        def calls_for(seed):
            rng = random.Random(seed)
            floats = [struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64)))[0] for _ in range(60)]
            floats = [x for x in floats if math.isfinite(x)] + [5e-324, -0.0, 0.1, 1.7976931348623157e308]
            out = []
            for i, x in enumerate(floats):           # interleaved: the harness groups by function, run_calls reorders
                out.append(("t_neg_f", [x]))
                out.append(("t_add_i_i", [rng.randint(-2 ** 62, 2 ** 62), -i]))
            out += [("t_and_b_b", [a, b]) for a in (False, True) for b in (False, True)]
            out += [("t_len_li", [[rng.randint(-9, 9) for _ in range(n)]]) for n in (0, 1, 5)]
            out += [("t_add_i_i", [2 ** 63 - 1, 0]), ("t_add_i_i", [-2 ** 63, 0])]
            return out

        for lang in langs:
            em = Emitter(ctx.store, lang, ctx.ops)
            usable = []
            for n in ("t_neg_f", "t_add_i_i", "t_and_b_b", "t_len_li"):
                try:
                    em.program({"entry": n, "functions": [fns[n]]}, [])
                    usable.append(n)
                except EmitGap:
                    continue
            module = {"entry": usable[0], "functions": [fns[n] for n in usable]}
            card = ctx.language(lang)
            runs = []
            for seed in (SEED, SEED + 1):
                calls = [c for c in calls_for(seed) if c[0] in usable]
                self.assertIsNotNone(em.program_stdin(module, calls, usable), f"{lang} has no read templates")
                got = run_calls(em, card, module, calls, ctx.state_root, entries=usable)
                baked = run_program(card, em.program(module, calls), ctx.state_root)
                self.assertEqual((got.status, len(got.values)), ("ok", len(calls)), f"{lang} {got.stderr[-300:]}")
                key = lambda v: (type(v), repr(v))     # noqa: E731 -- bit-exact for floats, -0.0 included
                ref = [-a[0] if n == "t_neg_f" else a[0] + a[1] if n == "t_add_i_i" else
                       (a[0] and a[1]) if n == "t_and_b_b" else len(a[0]) for n, a in calls]
                # exact, or what baked inputs print too (JavaScript prints -0 as 0); Go's baked literal -0.0 is +0
                bad = [(c, r, g, b) for c, r, g, b in zip(calls, ref, got.values, baked.values)
                       if key(g) != key(r) and key(g) != key(b)]
                self.assertEqual(bad, [], f"{lang} {seed_note(self)}")
                runs.append(got)
            if (card.get("runner") or {}).get("compile"):
                self.assertTrue(runs[1].cached, f"{lang}: a new seed recompiled")

