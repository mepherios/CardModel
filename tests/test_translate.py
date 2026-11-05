"""Observe -> card IR -> native code in other languages -> verified against the original Python."""
import unittest
from collections import Counter

from helpers import SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import translate
from cardmodel.engines.codegen import EmitGap, emit_module
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter

SRC = '''
import math

def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return abs(a)

def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True

def count_primes(limit: int) -> int:
    c = 0
    for k in range(2, limit):
        if is_prime(k):
            c += 1
    return c

def tri(n: int) -> int:
    total = 0
    for i in range(n, 0, -1):
        if i % 3 == 0:
            continue
        total += i
    return total

def mean3(a: float, b: float, c: float) -> float:
    return (a + b + c) / 3

def uses_list(xs: dict) -> int:
    return len(xs)

def calls_bad(n: int) -> int:
    return uses_list(n)
'''


class Lift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = {lf.name: lf for lf in lift_source(SRC, cls.ctx.ops)}

    def test_supported_subset_lifts(self):
        for n in ("gcd", "fib", "is_prime", "count_primes", "tri", "mean3"):
            self.assertTrue(self.lifted[n].ok, (n, self.lifted[n].reasons))

    def test_unsupported_is_reported_precisely(self):
        lf = self.lifted["uses_list"]
        self.assertFalse(lf.ok)
        self.assertIn("type annotation 'dict'", lf.reasons[0])
        self.assertIn("line", lf.reasons[0])
        self.assertFalse(self.lifted["calls_bad"].ok)       # closure: calls a function that did not lift

    def test_interpreter_matches_python(self):
        ns = {}
        exec(SRC, ns)
        lifted = list(self.lifted.values())
        for name, args in [("gcd", (84, -36)), ("fib", (30,)), ("count_primes", (50,)), ("tri", (17,))]:
            mod = module_for(name, lifted)
            self.assertEqual(Interpreter(mod, self.ctx.ops).call(name, list(args)), ns[name](*args))

    def test_lean_gap_for_floats(self):
        mod = module_for("mean3", list(self.lifted.values()))
        with self.assertRaises(EmitGap):
            emit_module(self.ctx.store, self.ctx.ops, "lean", mod)


class CarryMap(unittest.TestCase):
    """A language is a carry map on the atoms (FOUNDATIONS D13, D14): its gap is known from a term's content before
    anything is emitted, and the prediction never refuses what the emitter would write."""

    def test_the_gap_is_predicted_from_content_without_false_positives(self):
        import random
        from cardmodel.engines import godel as G
        from cardmodel.engines.codegen import carry_map, language_gap, predicted_gap, ranked_content, supported_ops
        ctx = model_ctx()
        cards = [c for c in ctx.store.cards("function") if isinstance(c.get("ir"), dict)]
        self.assertTrue(cards)
        rng = random.Random(SEED)
        sample = rng.sample(cards, min(120, len(cards)))
        hits = rank_hits = misses = emitted = 0
        for lang in ctx.codegen_languages():
            gap = ctx.language_gap(lang)
            self.assertEqual(gap, language_gap(ctx.store, ctx.ops, lang))
            self.assertEqual({a for a in gap if G.RANK not in a},
                             {f"op/{o}" for o, ok in supported_ops(ctx.store, ctx.ops, lang).items() if not ok})
            self.assertEqual(set(carry_map(ctx.store, ctx.ops, lang)), set(ctx.ops))
            for card in sample:
                blind = predicted_gap(G.module_content(card["ir"], ctx.ops), gap)     # rank-blind: an op at no rank
                predicted = predicted_gap(ranked_content(ctx.ops, card["ir"]), gap)   # at the ranks the term uses
                self.assertTrue(set(blind) <= {G.base_atom(a) for a in predicted}, (lang, card.name, blind, predicted))
                try:
                    emit_module(ctx.store, ctx.ops, lang, card["ir"])
                    failed = None
                except EmitGap as exc:
                    failed = str(exc)
                if predicted:
                    self.assertIsNotNone(failed, (lang, card.name, predicted, seed_note(self)))
                    hits += 1
                    rank_hits += not blind
                elif failed:
                    misses += 1
                else:
                    emitted += 1
        self.assertGreater(hits, 0, seed_note(self))
        self.assertGreater(emitted, 0, seed_note(self))
        print(f"\n  gaps predicted from content: {hits}, of them at one rank only: {rank_hits}; found only by "
              f"emitting: {misses}; emitted: {emitted}", end=" ")

    def test_translation_is_the_same_with_and_without_the_prediction(self):
        from collections import Counter
        from cardmodel.engines import godel as G
        from cardmodel.engines.codegen import ranked_content
        ctx = model_ctx()
        lifted = lift_source(SRC, ctx.ops)
        cards = {}
        for name in ("mean3", "gcd"):
            translate.PREDICT_GAPS = False
            try:
                without = translate.function_card(ctx, name, lifted, "test_translate.py", seed=SEED)
            finally:
                translate.PREDICT_GAPS = True
            with_ = cards[name] = translate.function_card(ctx, name, lifted, "test_translate.py", seed=SEED)
            self.assertEqual(set(with_["emit_gaps"]), set(without["emit_gaps"]), name)
            self.assertEqual([f["code"] for f in with_["forms"]], [f["code"] for f in without["forms"]], name)
            self.assertEqual(with_["depends_on"], without["depends_on"], name)
            self.assertEqual(with_["godel"]["content"], dict(G.module_content(with_["ir"], ctx.ops)), name)
            self.assertEqual(with_["godel"]["ranks"], dict(ranked_content(ctx.ops, with_["ir"])), name)
            self.assertEqual(G.forget_ranks(Counter(with_["godel"]["ranks"])), G.module_content(with_["ir"], ctx.ops))
            self.assertEqual(without["predicted_gaps"], {}, name)
        # mean3 computes with floats, which Lean has no type for: ADD is a gap at its float rank only (Lean adds
        # ints), which the rank-blind content cannot see and the ranked content predicts before anything is emitted
        self.assertIn("lean", cards["mean3"]["emit_gaps"])
        self.assertIn("op/ADD@float,float->float", cards["mean3"]["predicted_gaps"].get("lean", []))
        self.assertNotIn("op/ADD", ctx.language_gap("lean"))
        self.assertNotIn("lean", cards["gcd"]["emit_gaps"])

    def test_the_support_of_content_is_the_ops_used(self):
        from cardmodel.engines import godel as G
        from cardmodel.engines.ir import ops_used
        ctx = model_ctx()
        for lf in lift_source(SRC, ctx.ops):
            if lf.ok:
                self.assertEqual(G.support(G.term_content(lf.ir["body"], ctx.ops)),
                                 {f"op/{o}" for o in ops_used(lf.ir) if o in ctx.ops}, lf.name)


class Ranks(unittest.TestCase):
    """Content at rank level (FOUNDATIONS D1: an op card's ``ir.types`` are its ranks): every application counted at
    the rank it instantiates, typed as the emitter types it. Forgetting the ranks is a carry map back to γ."""

    def _sample(self, ctx, n=120):
        import random
        cards = [c for c in ctx.store.cards("function") if isinstance(c.get("ir"), dict)]
        self.assertTrue(cards)
        return random.Random(SEED).sample(cards, min(n, len(cards)))

    def test_forgetting_the_ranks_is_the_content(self):
        from cardmodel.engines import godel as G
        from cardmodel.engines.codegen import ranked_content
        ctx = model_ctx()
        for card in self._sample(ctx):
            ranked = ranked_content(ctx.ops, card["ir"])
            self.assertEqual(G.forget_ranks(ranked), G.module_content(card["ir"], ctx.ops), (card.name, seed_note(self)))
            self.assertTrue(all(G.RANK in a and "->" in a for a in ranked), card.name)
        t = ["ADD", ["var", "x"], ["MUL", ["float", 2.0], ["TO_FLOAT", ["var", "n"]]]]
        module = {"functions": [{"name": "f", "params": [{"name": "x", "type": "float"}, {"name": "n", "type": "int"}],
                                 "returns": "float", "body": [{"k": "return", "value": t}]}]}
        self.assertEqual(ranked_content(ctx.ops, module),
                         Counter({"op/ADD@float,float->float": 1, "op/MUL@float,float->float": 1,
                                  "op/TO_FLOAT@int->float": 1}))
        self.assertEqual(G.forget_ranks(ranked_content(ctx.ops, module)), G.term_content(t, ctx.ops))

    def test_the_ranks_are_the_ones_emission_resolves(self):
        """What the emitter resolves while writing Python (which names every sort) is the ranked content, with the
        comparisons it adds itself for a lowered switch (Python has no switch template) on top."""
        from cardmodel.engines import codegen as CG
        from cardmodel.engines import godel as G
        ctx = model_ctx()
        seen: Counter = Counter()

        class Recording(CG.Emitter):
            def op_template(self, op, arg_types, rtype=None):
                seen[G.ranked_atom(f"op/{op}", CG.rank_key(arg_types, rtype))] += 1
                return super().op_template(op, arg_types, rtype)
        checked = 0
        for card in self._sample(ctx):
            seen.clear()
            try:
                Recording(ctx.store, "python", ctx.ops).module_source(card["ir"], None)
            except CG.EmitGap:
                continue
            ranked = CG.ranked_content(ctx.ops, card["ir"])
            lowered = any(s["k"] == "switch" for f in card["ir"]["functions"] for s in CG._stmts(f["body"]))
            if lowered:
                self.assertTrue(all(seen[a] >= e for a, e in ranked.items()), (card.name, seed_note(self)))
            else:
                self.assertEqual(seen, ranked, (card.name, seed_note(self)))
            checked += 1
        self.assertGreater(checked, 0, seed_note(self))


class Translate(unittest.TestCase):
    def test_functions_agree_across_languages(self):
        ctx = model_ctx()
        lifted = lift_source(SRC, ctx.ops)
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        for name in ("gcd", "fib", "count_primes", "tri", "mean3"):
            card = translate.function_card(ctx, name, lifted, "test_translate.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            self.assertGreaterEqual(len(card["vectors"]), 8, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")
            self.assertGreaterEqual(len(rep["agreeing_languages"]), 3, (name, rep["languages"]))


# Constructs found in real programs (firstlaw, rea-cards' pheros configs): module constants, numeric defaults,
# keyword calls, math.*, a memoizing decorator, pow with a negative exponent, capitalized parameter names.
REAL = '''
import math
from functools import lru_cache

P = 2**31 - 1
SCALE = 2.5

def addmod(a: int, b: int, m: int = P) -> int:
    return (a + b) % m

def hyp(x: float, y: float) -> float:
    return math.sqrt(x * x + y * y) + math.pi

def floors(x: float) -> int:
    return math.floor(x) + math.ceil(x * SCALE)

@lru_cache(maxsize=None)
def fibm(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, addmod(a, b)
    return a

def damp(x: float, k: float = 0.5) -> float:
    return math.exp(-k * x) * math.cos(x)

def caller(x: float) -> float:
    return damp(x) + damp(x, k=2.0) + damp(k=1.0, x=x)

def inv_pow(a: int, b: int, m: int) -> int:
    return pow(a, b, m)

def attack_rate(R_final: float, N: float) -> float:
    return R_final / N if N > 0 else 0.0

def lifetime(M: float) -> float:
    return 1e10 * (1.0 / M) ** 2.5

BIG = 2**255 - 19

def red(a: int) -> int:
    return a % BIG
'''


class RealPrograms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = lift_source(REAL, cls.ctx.ops)

    def test_everything_lifts(self):
        bad = {lf.name: lf.reasons for lf in self.lifted if not lf.ok}
        self.assertEqual(bad, {})

    def test_defaults_and_keywords_bind_by_name(self):
        ns = {}
        exec(REAL, ns)
        mod = module_for("caller", self.lifted)
        self.assertAlmostEqual(Interpreter(mod, self.ctx.ops).call("caller", [1.5]), ns["caller"](1.5))

    def test_reassigned_or_global_names_are_not_constants(self):
        src = "K = 1\nK = 2\nJ = 3\ndef f(x: int) -> int:\n    return x + K\n" \
              "def g(x: int) -> int:\n    return x + J\ndef h() -> int:\n    global J\n    J = 4\n    return J\n"
        by = {lf.name: lf for lf in lift_source(src, self.ctx.ops)}
        self.assertFalse(by["f"].ok)
        self.assertFalse(by["g"].ok)

    def test_too_wide_constant_is_a_gap_not_a_compile_error(self):
        with self.assertRaises(EmitGap):
            emit_module(self.ctx.store, self.ctx.ops, "c", module_for("red", self.lifted))

    def test_agree_across_languages(self):
        ctx = self.ctx
        langs = None if SLOW else [l for l in ("python", "javascript", "c", "ruby") if ctx.available(l)[0]]
        for name in ("addmod", "hyp", "floors", "fibm", "caller", "inv_pow", "attack_rate", "lifetime"):
            card = translate.function_card(ctx, name, self.lifted, "real.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
