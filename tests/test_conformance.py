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

    def test_fixed_width_more_ops(self):
        """SUB underflow at u8/u16, i16/i32 overflow, a u32 shift and f32 SUB/DIV rounding pass (wrap-on-store)."""
        ctx = model_ctx()
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        rep = conformance.matrix(ctx, langs=langs, seed=SEED, samples=8,
                                 ops=["ADD", "SUB", "DIV", "SHIFT_LEFT", "SHIFT_RIGHT", "NEG", "BIT_NOT", "CMP_LT"])
        want = ("t_sub_u8_u8", "t_sub_u16_u16", "t_sub_i16_i16", "t_sub_i32_i32", "t_neg_i32", "t_bit_not_u32",
                "t_shift_left_u32_i", "t_shift_right_u32_i", "t_cmp_lt_u8_u8", "t_sub_f32_f32", "t_div_f32_f32",
                "t_add_i16_i16", "t_add_i32_i32")
        for lang, r in rep["languages"].items():
            if not r["available"]:
                continue
            for n in want:
                self.assertEqual(r["cells"][n]["status"], "pass", f"{lang} {n} {r['cells'][n]} {seed_note(self)}")
                self.assertGreater(r["cells"][n]["checks"], 0, f"{lang} {n}")

    def test_fixed_width_more_reference(self):
        import struct
        from cardmodel.engines.ir import Interpreter
        ops = op_table(model_ctx().store)
        fns = {f["fn"]["name"]: f["fn"] for f in conformance.op_functions(ops)}

        def run(name, *args):
            return Interpreter({"functions": [fns[name]]}, ops).call(name, list(args))

        def f32(v):
            return struct.unpack("f", struct.pack("f", v))[0]
        self.assertEqual(run("t_sub_u8_u8", 3, 5), 254)
        self.assertEqual(run("t_sub_u16_u16", 0, 1), 65535)
        self.assertEqual(run("t_sub_i16_i16", -32768, 1), 32767)
        self.assertEqual(run("t_add_i16_i16", 32767, 1), -32768)
        self.assertEqual(run("t_add_i32_i32", 2 ** 31 - 1, 1), -2 ** 31)
        self.assertEqual(run("t_sub_i32_i32", 2 ** 31 - 1, -1), -2 ** 31)
        self.assertEqual(run("t_neg_i32", -2 ** 31), -2 ** 31)
        self.assertEqual(run("t_shift_left_u32_i", 0xFFFFFFFF, 4), 0xFFFFFFF0)
        self.assertEqual(run("t_bit_not_u8", 0), 255)
        x, y = f32(0.1), f32(0.3)
        self.assertEqual(run("t_sub_f32_f32", y, x), f32(y - x))
        self.assertEqual(run("t_div_f32_f32", f32(1.0), f32(3.0)), f32(1.0 / 3.0))
        self.assertNotEqual(run("t_div_f32_f32", f32(1.0), f32(3.0)), 1.0 / 3.0)

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


class CarryImage(unittest.TestCase):
    """The cells are the carry map's verified image (docs/GODEL_AUDIT.md §4.1, step 3): a gap cell is read from the
    map with nothing emitted, and the map refuses exactly what the emitter refuses, at every op, rank and language."""

    def test_the_map_refuses_exactly_what_the_emitter_refuses(self):
        from cardmodel.engines.codegen import emission_content, predicted_gap
        ctx = model_ctx()
        fns = conformance.op_functions(ctx.ops)
        self.assertTrue(fns)
        self.assertTrue(all(f["atom"] == f"op/{f['op']}@{f['rank']}" for f in fns))
        cells = gaps = 0
        for lang in ctx.codegen_languages():
            gap = ctx.language_gap(lang)
            for item in fns:
                predicted = predicted_gap(emission_content(ctx.ops, {"functions": [item["fn"]]}), gap)
                try:
                    Emitter(ctx.store, lang, ctx.ops).program({"entry": item["fn"]["name"], "functions": [item["fn"]]}, [])
                    refused = None
                except EmitGap as exc:
                    refused = str(exc)
                self.assertEqual(bool(predicted), refused is not None, (lang, item["atom"], predicted, refused))
                cells += 1
                gaps += bool(predicted)
        self.assertGreater(gaps, 0)
        print(f"\n  {cells} cells over {len(ctx.codegen_languages())} languages: the map and the emitter agree on every "
              f"one; {gaps} gaps known with nothing emitted", end=" ")

    def test_a_fixed_width_cell_needs_the_wrap_of_its_store(self):
        """FOUNDATIONS §7.3: a u8 result is stored wrapped, so the cell at a fixed-width rank needs WRAPU's template
        too. The content of the term (ranked_content) does not see the wrap; the emission content does, and the
        rank-blind content is still what forgetting the ranks gives."""
        from cardmodel.engines import godel as G
        from cardmodel.engines.codegen import emission_content, predicted_gap, ranked_content
        ctx = model_ctx()
        item = next(i for i in conformance.op_functions(ctx.ops) if i["fn"]["name"] == "t_add_u8_u8")
        module = {"functions": [item["fn"]]}
        self.assertEqual(set(ranked_content(ctx.ops, module)), {"op/ADD@u8,u8->u8"})
        self.assertEqual(set(emission_content(ctx.ops, module)), {"op/ADD@u8,u8->u8", "op/WRAPU@u8,int->int"})
        self.assertEqual(G.forget_ranks(ranked_content(ctx.ops, module)), G.module_content(module, ctx.ops))
        lean = ctx.language_gap("lean")
        self.assertIn("op/WRAPU", lean)                                  # Lean has no wrap-on-store template
        self.assertNotIn("op/ADD@u8,u8->u8", lean)                       # but it adds a u8 (held in its Int)
        self.assertEqual(predicted_gap(ranked_content(ctx.ops, module), lean), [])
        self.assertEqual(predicted_gap(emission_content(ctx.ops, module), lean), ["op/WRAPU@u8,int->int"])
        self.assertEqual(predicted_gap(emission_content(ctx.ops, module), ctx.language_gap("c")), [])

    def test_cells_are_atoms_and_the_readers_read_them(self):
        from collections import Counter
        ctx = model_ctx()
        rep = conformance.matrix(ctx, langs=["python", "lean"], seed=SEED, samples=2, ops=["ADD", "REM"])
        self.assertEqual(rep["tier"], "sample")
        self.assertEqual(rep["atoms"]["t_rem_i_i"], "op/REM@int,int->int")
        py, lean = rep["languages"]["python"], rep["languages"]["lean"]
        self.assertTrue(all(c["atom"] == rep["atoms"][n] for r in (py, lean) for n, c in r["cells"].items()))
        self.assertEqual(py["cells"]["t_rem_i_i"]["status"], "pass", seed_note(self))
        self.assertEqual(py["cells"]["t_add_u8_u8"]["status"], "pass", seed_note(self))
        # Lean's gaps are known with no toolchain: REM has no Lean template, nor ADD on floats (no float type),
        # nor a u8 store (no WRAPU); the cells Lean could run are unavailable here, or pass where it is installed
        self.assertEqual(lean["cells"]["t_rem_i_i"]["status"], "gap")
        self.assertEqual(lean["cells"]["t_rem_i_i"]["missing"], ["op/REM@int,int->int"])
        self.assertEqual(lean["cells"]["t_add_f_f"]["status"], "gap")
        self.assertEqual(lean["cells"]["t_add_u8_u8"]["missing"], ["op/WRAPU@u8,int->int"])
        self.assertIn(lean["cells"]["t_add_i_i"]["status"], ("unavailable", "pass"))
        # ADD on floats and f32, on the six fixed-width ints (their stores wrap), and REM: all from the map
        self.assertEqual(rep["summary"]["lean"]["gap"], 9)
        im = conformance.image(rep)
        self.assertEqual(im["lean"]["op/REM@int,int->int"], "gap")
        self.assertEqual(im["python"]["op/ADD@int,int->int"], "pass")
        risk = conformance.risk(rep, Counter({"op/ADD@int,int->int": 2, "op/REM@int,int->int": 1}))
        self.assertEqual(risk["python"], {})
        self.assertEqual(risk["lean"].get("op/REM@int,int->int"), "gap")
        blind = conformance.risk(rep, Counter({"op/REM": 1, "op/MUL": 1}))
        self.assertEqual(blind["python"], {"op/MUL": "unchecked"})
        self.assertEqual(blind["lean"], {"op/MUL": "unchecked", "op/REM@int,int->int": "gap"})
        self.assertEqual(conformance.semantic_gap(rep), {"python": [], "lean": []})

    def test_the_semantic_gap_is_the_failing_atoms(self):
        from collections import Counter
        rep = {"languages": {"c": {"available": True, "cells": {
            "t_mod_i_i": {"status": "fail", "atom": "op/MOD@int,int->int", "args": [-7, 3], "expected": 2, "got": -1},
            "t_add_i_i": {"status": "pass", "atom": "op/ADD@int,int->int", "checks": 8},
            "t_rem_i_i": {"status": "error", "atom": "op/REM@int,int->int"}}}}}
        self.assertEqual(conformance.semantic_gap(rep), {"c": ["op/MOD@int,int->int", "op/REM@int,int->int"]})
        self.assertEqual(conformance.risk(rep, Counter({"op/MOD@int,int->int": 1, "op/ADD@int,int->int": 3}))["c"],
                         {"op/MOD@int,int->int": "fail"})
        self.assertEqual(conformance.risk(rep, Counter({"op/ADD": 3}))["c"], {})

