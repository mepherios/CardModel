"""A game engine's math as cards (CM49): lifted through clang, canonical over the reals, witnessed, a wrong term caught.

The pipeline tests run on examples/engine_math/mini_math.h (written for these tests, not engine code), so they need
only clang; the engine's own cards are checked when a scan of Unreal Engine has been saved.
"""
import copy
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from helpers import ROOT, SEED, model_ctx, seed_note

from cardmodel.engines import realnorm as RN
from cardmodel.unreal import distill as D
from cardmodel.unreal import engine as E
from cardmodel.unreal import scan as S
from cardmodel.unreal import witness as W

FIXTURE = ROOT / "examples" / "engine_math" / "mini_math.h"
V = lambda n: ["var", n]  # noqa: E731


class EngineMath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clang = E.clang()[0]
        cls.work = Path(tempfile.mkdtemp(prefix="cardmodel_unreal_"))
        if cls.clang is None:
            return
        flags = ["-std=c++20", "-ffp-contract=off", "-x", "c++", f"-I{FIXTURE.parent}"]
        cls.fns = {f["qual"]: f for f in S.lift_source(FIXTURE, flags, cls.work)}
        cls.target = W.Target([f'#include "{FIXTURE.name}"'], ["-std=c++20", "-ffp-contract=off",
                                                               f"-I{FIXTURE.parent}"], [], cls.work)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def setUp(self):
        if self.clang is None:
            self.skipTest("no clang++ on this host")

    def test_engine_math_is_distilled_and_witnessed(self):
        f = self.fns
        cross = f["Mini::TVec<double>::Cross"]
        self.assertEqual(cross["status"], "lifted")
        terms = {o["name"]: o["term"] for o in cross["outputs"]}
        self.assertEqual(terms["return.X"], ["SUB", ["MUL", V("A.Y"), V("B.Z")], ["MUL", V("A.Z"), V("B.Y")]])
        # one canonical form for three spellings of the dot product; another for |v|^2
        h = {q: D.distill_function(f[f"Mini::TVec<double>::{q}"], {})["hash"]
             for q in ("Dot", "DotSwapped", "operator|", "SizeSquared")}
        self.assertEqual(h["Dot"], h["DotSwapped"])
        self.assertEqual(h["Dot"], h["operator|"])
        self.assertNotEqual(h["Dot"], h["SizeSquared"])
        # a write through an index the inputs choose is a gap with its cause, not a guess
        comp = f["Mini::TVec<double>::SetComponent"]
        self.assertEqual((comp["status"], comp["cause"]), ("gap", "array index"))
        # a read through one is lifted (through a union's array too); an index outside the array is undefined in
        # C++, and the term says so: the witness never runs the engine's code there, and emitted code may read any
        # element there
        self.assertEqual(f["Mini::TVec<double>::Component"]["status"], "lifted")
        pick = f["Mini::MathLite::Pick3"]
        self.assertEqual(pick["status"], "lifted", pick.get("cause"))
        t = pick["outputs"][0]["term"]
        env = {"A": 1.5, "B": 2.5, "C": 3.5}
        self.assertEqual([W.evaluate(t, {**env, "I": i}) for i in (0, 1, 2)], [1.5, 2.5, 3.5])
        for i in (-1, 3):
            with self.assertRaises(W.Undefined):
                W.evaluate(t, {**env, "I": i})
        # a shift by a count on the inputs is undefined past the operand's width (32 bits here), and the term says so;
        # a constant shift of a 64-bit operand past 31 is ordinary
        bit = f["Mini::MathLite::Bit"]["outputs"][0]["term"]
        self.assertEqual(W.evaluate(bit, {"N": 31}), 1 << 31)
        with self.assertRaises(W.Undefined):
            W.evaluate(bit, {"N": 32})
        self.assertEqual(W.evaluate(f["Mini::MathLite::High"]["outputs"][0]["term"], {"X": 0xAB << 56}), 0xAB)
        # a compound assignment returns the object itself: its fields are the outputs, and the witness checks the
        # returned reference by address
        plus = f["Mini::TVec<double>::operator+="]
        self.assertIn(("return", "&this"), [(o["name"], o["kind"]) for o in plus["outputs"]])
        from cardmodel.unreal import cli as UC
        body = UC.module_of(pick)["functions"][0]["body"][0]["value"]
        self.assertNotIn("<undefined", repr(body))
        # the compiled header agrees with every lifted term, bit for bit
        lifted = [x for x in f.values() if x["status"] == "lifted" and x["outputs"]]
        v = W.run(self.target, lifted, SEED, log=lambda m: None, cases=12)
        bad = {k: r for k, r in v.items() if r["status"] != "witnessed"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertTrue(all(r["max_ulp"] == 0 for r in v.values()))
        # a planted wrong term is refuted at a counterexample (CM07)
        wrong = copy.deepcopy(cross)
        o = next(o for o in wrong["outputs"] if o["name"] == "return.Y")
        o["term"] = ["SUB", o["term"][2], o["term"][1]]
        v2 = W.run(self.target, [wrong], SEED, log=lambda m: None, cases=12)
        self.assertEqual(v2[wrong["key"]]["status"], "refuted", seed_note(self))
        # a same-width unsigned -> signed conversion read as value-preserving (a lifter bug the engine's witness
        # found in FFloat16::IsNegative) is refuted on every seed: the first cases are the unsigned edges
        sign = copy.deepcopy(f["Mini::MathLite::SignBitSet"])
        self.assertNotEqual(sign["outputs"][0]["term"], ["CMP_LT", V("Encoded"), ["int", 0]])
        sign["outputs"][0]["term"] = ["CMP_LT", V("Encoded"), ["int", 0]]
        v3 = W.run(self.target, [sign], SEED, log=lambda m: None, cases=4)
        self.assertEqual(v3[sign["key"]]["status"], "refuted", seed_note(self))

    def test_branches_floats_and_wrapping_lift_exactly(self):
        f = self.fns
        self.assertEqual(f["Mini::MathLite::Hash"]["outputs"][0]["term"][0], "BIT_AND")    # uint32 wraps
        lerp = f["Mini::MathLite::Lerp"]["outputs"][0]["term"]
        self.assertEqual(lerp[0], "F32")                                                 # float arithmetic rounds
        smooth = f["Mini::MathLite::SmoothStep"]["outputs"][0]["term"]
        self.assertIn("IF_EXPR", str(smooth))                                            # early returns merge
        out = {o["name"] for o in f["Mini::TVec<double>::ToDirectionAndLength"]["outputs"]}
        self.assertEqual(out, {"OutDir.X", "OutDir.Y", "OutDir.Z", "OutLength"})          # out parameters
        gsn = f["Mini::TVec<double>::GetSafeNormal"]
        self.assertEqual(gsn["status"], "lifted")                                        # a default argument
        self.assertIn(["var", "Tolerance"], [x for x in _walk(gsn["outputs"][0]["term"])])

    def test_canonical_forms_over_the_reals(self):
        c = RN.canonical
        self.assertEqual(c(["MUL", ["ADD", V("a"), V("b")], ["ADD", V("a"), V("b")]]),
                         c(["ADD", ["ADD", ["MUL", V("a"), V("a")], ["MUL", ["int", 2], ["MUL", V("a"), V("b")]]],
                                ["MUL", V("b"), V("b")]]))
        self.assertEqual(c(["CMP_LT", V("a"), V("b")]), c(["CMP_GT", V("b"), V("a")]))
        self.assertEqual(c(["CMP_LT", V("a"), V("b")]), c(["NOT", ["CMP_GE", V("a"), V("b")]]))
        self.assertEqual(c(["F32", ["ADD", ["F32", V("x")], ["float", 0.5]]]), c(["ADD", V("x"), ["float", 0.5]]))
        self.assertEqual(c(["SIN", ["NEG", V("x")]]), c(["NEG", ["SIN", V("x")]]))
        self.assertEqual(c(["COS", ["NEG", V("x")]]), c(["COS", V("x")]))
        self.assertNotEqual(c(["SUB", V("a"), V("b")]), c(["SUB", V("b"), V("a")]))
        self.assertEqual(c(["DIV", ["MUL", V("x"), V("y")], V("y")]), c(V("x")))       # as rational functions
        # a shared subterm (a DAG) is read once
        t = V("x")
        for _ in range(60):
            t = ["ADD", t, t]
        self.assertEqual(c(t), ["MUL", ["int", 2 ** 60], V("x")])


def _walk(t):
    stack = [t]
    while stack:
        x = stack.pop()
        yield x
        if isinstance(x, list) and x and isinstance(x[0], str) and x[0] not in ("var", "int", "float", "bool"):
            stack.extend(a for a in x[1:] if isinstance(a, list))



class EngineSets(unittest.TestCase):
    """The engine's Gödel sets state admissible numberings (GM-4): analysis and bits over their op cards, unreal over
    the engine's functions with the arities their cards state."""

    def test_the_sets_are_admissible(self):
        from cardmodel.engines import numbering as N
        ctx = model_ctx()
        for name in ("analysis", "bits", "unreal"):
            r = N.check_set(ctx, name, seed=SEED)
            bad = {k: v for k, v in r["conditions"].items() if v["status"] != "pass"}
            self.assertEqual(bad, {}, f"{name}: {seed_note(self)}")
            self.assertEqual(ctx.store.get(f"godel_set/{name}")["numbering"]["conditions"],
                             [c[0] for c in N.CONDITIONS])


class LocalData(unittest.TestCase):
    """UE-derived data stays local (docs/INTEGRATION.md rule 8): the engine's cards go to the untracked local layer,
    every store reads it, nothing writes it by default, and the tracked tree holds no pack of them."""

    def test_engine_cards_stay_on_this_machine(self):
        import inspect

        from cardmodel.kernel import paths
        from cardmodel.kernel.store import open_store
        from cardmodel.unreal import cards as K
        self.assertEqual(inspect.signature(K.write).parameters["layer"].default, "local")
        self.assertEqual(sorted((ROOT / "cards").glob("*/_pack_unreal.jsonl")), [])
        st = open_store(project=False)
        self.assertIn(("local", paths.local_cards()), st.layers)
        self.assertNotEqual(st.writable_layer(), "local")
        self.assertTrue(paths.local_cards().is_relative_to(paths.home() / "state"))
        self.assertIn("state/", (ROOT / ".gitignore").read_text(encoding="utf-8").split())

class EngineCards(unittest.TestCase):
    def test_engine_cards_trace_to_truth(self):
        ctx = model_ctx()
        subjects = ctx.store.cards("unreal_math")
        if not subjects:
            self.skipTest("no scan of an engine saved (cardmodel unreal scan --save)")
        from cardmodel.engines import godel, sources
        from cardmodel.unreal import metrics
        r = sources.check(ctx)
        self.assertEqual(r["problems"], [])
        idx = godel.index_of(ctx.store)
        st = Counter(s.get("status") for s in subjects)
        self.assertEqual(st["refuted"], 0)
        self.assertGreater(st["lifted"], st["gap"])
        for s in subjects:
            if s.get("atom"):
                self.assertEqual(s.get("prime"), idx[s["atom"]]["prime"], s.name)
        res = metrics.check(ctx, SEED, rewitness=0)
        self.assertEqual(res["problems"], [], seed_note(self))
        self.assertGreater(res["rederived"], 100)


if __name__ == "__main__":
    unittest.main()


class TargetModel(unittest.TestCase):
    def test_ieee_evaluator_is_the_model_on_its_domain(self):
        # FOUNDATIONS.md D14 and rule A2: the witness's IEEE/C evaluator is a target model. On every op card's own
        # domain it must give the op card's value; it may only extend the model where the model is undefined
        # (a float divided by zero is ±inf there, an error in the model).
        import math
        import random
        ctx = model_ctx()
        rng = random.Random(SEED)
        compared = 0
        for name, spec in sorted(ctx.ops.items()):
            if spec.fn is None:
                continue
            for dom in ((spec.card.get("ir") or {}).get("domain") or {}).values():
                if not all("int" in g or "float" in g for g in dom):
                    continue
                for _ in range(30):
                    args = [rng.randint(*g["int"]) if "int" in g else rng.uniform(*g["float"]) for g in dom]
                    try:
                        want = spec.fn(*args)
                    except (ArithmeticError, ValueError):
                        continue
                    try:
                        got = W.evaluate([name, *[["int", a] if isinstance(a, int) else ["float", a] for a in args]], {})
                    except W.Undefined:
                        continue
                    except ValueError as exc:
                        if str(exc).startswith("no evaluation for"):
                            break                   # an op the engine's terms never use: not a disagreement
                        raise
                    nan = isinstance(got, float) and isinstance(want, float) and math.isnan(got) and math.isnan(want)
                    self.assertTrue(got == want or nan, (name, args, got, want, seed_note(self)))
                    compared += 1
        self.assertGreater(compared, 1000)
        self.assertEqual(W.evaluate(["DIV", ["float", 1.0], ["float", 0.0]], {}), math.inf)
