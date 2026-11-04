"""Lists in the IR (list[int], list[float]): lift, interpret, value semantics, codegen, and the transformer kernels."""
import unittest
from pathlib import Path

from helpers import ROOT, SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import translate
from cardmodel.engines import values as V
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter, IRError, check_lists
from cardmodel.engines.runners import parse_values

SRC = '''
def total(xs: list[int]) -> int:
    s = 0
    for x in xs:
        s += x
    return s

def scaled(xs: list[float], k: float) -> list[float]:
    return [xs[i] * k for i in range(len(xs))]

def prefix(xs: list[int]) -> list[int]:
    out = [0] * len(xs)
    run = 0
    for i in range(len(xs)):
        run += xs[i]
        out[i] = run
    return out

def rebuilt(xs: list[int]) -> list[int]:
    ys = [xs[i] for i in range(len(xs))]
    ys = [ys[i] + 1 for i in range(len(ys))]
    return ys

def at(xs: list[int], i: int) -> int:
    return xs[i]

def writes_param(xs: list[int]) -> int:
    xs[0] = 1
    return 0

def aliases(xs: list[int]) -> list[int]:
    ys = xs
    return ys

def returns_param(xs: list[int]) -> list[int]:
    return xs

def sums(xs: list[float]) -> float:
    return sum(xs)
'''


class Lift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.lifted = {lf.name: lf for lf in lift_source(SRC, cls.ctx.ops)}

    def run_ir(self, name, *args):
        return Interpreter(module_for(name, list(self.lifted.values())), self.ctx.ops).call(name, list(args))

    def test_list_functions_lift_and_match_python(self):
        ns = {}
        exec(SRC, ns)
        for name, args in [("total", ([3, -1, 4],)), ("scaled", ([1.5, -2.0], 3.0)), ("prefix", ([1, 2, 3, 4],)),
                           ("rebuilt", ([5, 6],)), ("total", ([],)), ("prefix", ([],))]:
            self.assertTrue(self.lifted[name].ok, (name, self.lifted[name].reasons))
            self.assertEqual(self.run_ir(name, *args), ns[name](*args), name)

    def test_out_of_range_index_is_an_error(self):
        with self.assertRaises(IRError):
            self.run_ir("at", [1, 2], 2)
        with self.assertRaises(IRError):
            self.run_ir("at", [1, 2], -1)

    def test_value_semantics_are_enforced(self):
        for name in ("writes_param", "aliases", "returns_param"):
            self.assertFalse(self.lifted[name].ok, name)
        self.assertIn("compensated", " ".join(self.lifted["sums"].reasons))

    def test_check_lists_accepts_lifted_functions(self):
        for name in ("total", "scaled", "prefix", "rebuilt"):
            for fn in module_for(name, list(self.lifted.values()))["functions"]:
                self.assertEqual(check_lists(fn), [], name)


class Values(unittest.TestCase):
    def test_parse_values_reads_lists(self):
        self.assertEqual(parse_values(["i:3", "l:2", "f:1.5", "f:-2", "b:true", "l:0"]),
                         [3, [1.5, -2.0], True, []])

    def test_matrix_generator_ties_length_to_dimensions(self):
        import random
        gens = [{"list": {"float": [-1.0, 1.0]}, "len_of": [1, 2]}, {"int": [0, 4]}, {"int": [0, 4]},
                {"list": {"int": [0, 3]}, "len_like": 0}]
        for m, r, c, v in V.inputs(gens, 20, random.Random(SEED)):
            self.assertEqual(len(m), r * c)
            self.assertEqual(len(v), len(m))


class Transformer(unittest.TestCase):
    """The transformer kernels (matmul, softmax, layernorm, attention, a block) agree with Python in other languages."""

    def test_kernels_agree_across_languages(self):
        ctx = model_ctx()
        src = (ROOT / "examples" / "transformer" / "transformer.py").read_text(encoding="utf-8")
        lifted = lift_source(src, ctx.ops)
        self.assertEqual([lf.name for lf in lifted if not lf.ok], [])
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        names = [lf.name for lf in lifted] if SLOW else ["matmul", "softmax", "layernorm", "attention"]
        for name in names:
            card = translate.function_card(ctx, name, lifted, "transformer.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            self.assertGreaterEqual(len(card["vectors"]), 6, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
