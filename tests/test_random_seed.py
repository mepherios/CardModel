"""Randomised property tests (L28): a fresh seed per run, printed on failure, reproducible with CARDMODEL_TEST_SEED.

1. canonical JSON: the Python and JavaScript forms of crypto_atom/canon_json give identical bytes (or both reject)
   on random JSON values, including surrogates and integer limits (Ting's cross-language test, ported).
2. codegen fuzz: random IR expression programs run identically in the interpreter, Python, JavaScript and C.
"""
import random
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import translate, witness
from cardmodel.engines.runners import call_node, call_python


def random_json(rng, depth=0):
    kind = rng.choice(["int", "str", "bool", "null", "list", "dict"] if depth < 4 else ["int", "str", "bool", "null"])
    if kind == "int":
        return rng.choice([0, -1, 1, rng.randrange(-2**53 + 1, 2**53), rng.randrange(-1000, 1000)])
    if kind == "str":
        alphabet = ["a", "Z", "é", "ß", " ", "\n", '"', "\\", "\x00", "\x1f", "\x7f", "\U0001f600",
                    "", "￿", "中", " "]
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 8)))
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "null":
        return None
    if kind == "list":
        return [random_json(rng, depth + 1) for _ in range(rng.randrange(0, 4))]
    keys = ["a", "b", "é", "\U0001f600", "", "Z", "_"]
    return {"".join(rng.choice(keys) for _ in range(rng.randrange(0, 4))): random_json(rng, depth + 1)
            for _ in range(rng.randrange(0, 5))}


INT_OPS = ["ADD", "SUB", "MUL", "MIN", "MAX", "BIT_AND", "BIT_OR", "BIT_XOR"]


def random_expr(rng, depth):
    if depth == 0 or rng.random() < 0.25:
        return rng.choice([["var", "a"], ["var", "b"], ["int", rng.randint(-9, 9)]])
    r = rng.random()
    if r < 0.6:
        return [rng.choice(INT_OPS), random_expr(rng, depth - 1), random_expr(rng, depth - 1)]
    if r < 0.7:
        return [rng.choice(["NEG", "ABS"]), random_expr(rng, depth - 1)]
    if r < 0.85:
        d = random_expr(rng, depth - 1)
        return [rng.choice(["FLOORDIV", "MOD"]), random_expr(rng, depth - 1), ["ADD", ["MUL", d, d], ["int", 1]]]
    return ["IF_EXPR", [rng.choice(["CMP_LT", "CMP_EQ", "CMP_GE"]), random_expr(rng, depth - 1),
                        random_expr(rng, depth - 1)], random_expr(rng, depth - 1), random_expr(rng, depth - 1)]


class RandomSeed(unittest.TestCase):
    def test_canonical_json_python_equals_javascript(self):
        ctx = model_ctx()
        if not ctx.available("javascript")[0]:
            self.skipTest("node not available")
        card = ctx.store.get("crypto_atom/canon_json")
        rng = random.Random(SEED)
        values = [random_json(rng) for _ in range(300)] + [[2**53], [-(2**53)], ["\ud800"], {"\udfff": 1}]
        py = call_python(card.read_variant("python.py"), "canon_str", [[v] for v in values])
        js = call_node(card.read_variant("javascript.mjs"), "canon_str", [[v] for v in values])
        for v, a, b in zip(values, py, js):
            self.assertEqual(a.ok, b.ok, (v, a, b, seed_note(self)))
            if a.ok:
                self.assertEqual(a.value, b.value, (v, seed_note(self)))

    def test_codegen_fuzz(self):
        ctx = model_ctx()
        rng = random.Random(SEED)
        langs = [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        for i in range(6):
            body = random_expr(rng, 4)
            fn = {"name": f"fz{i}", "params": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
                  "returns": "int", "locals": {}, "body": [{"k": "return", "value": body}]}
            module = {"entry": fn["name"], "functions": [fn]}
            src = f"def {fn['name']}(a: int, b: int) -> int:\n    return {_py(body)}\n"
            card = {"name": f"fn_fuzz{i}", "ir": module, "generators": [{"int": [-30, 30]}, {"int": [-30, 30]}],
                    "vectors": [], "forms": [{"name": "python_source", "lang": "python", "code": src, "entry": fn["name"]}]
                    + [{"name": l, "lang": l, "generated": True} for l in langs]}
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED + i, samples=24)
            self.assertEqual(rep["lift_mismatches"], 0, (src, seed_note(self)))
            for lang, r in rep["languages"].items():
                self.assertIn(r["status"], ("pass", "no_inputs"), (lang, src, r, seed_note(self)))


def _py(e):
    head = e[0]
    if head == "var":
        return e[1]
    if head == "int":
        return f"({e[1]})"
    sym = {"ADD": "+", "SUB": "-", "MUL": "*", "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^", "FLOORDIV": "//",
           "MOD": "%", "CMP_LT": "<", "CMP_EQ": "==", "CMP_GE": ">="}
    if head in sym:
        return f"({_py(e[1])} {sym[head]} {_py(e[2])})"
    if head in ("MIN", "MAX"):
        return f"{head.lower()}({_py(e[1])}, {_py(e[2])})"
    if head == "NEG":
        return f"(-{_py(e[1])})"
    if head == "ABS":
        return f"abs({_py(e[1])})"
    if head == "IF_EXPR":
        return f"({_py(e[2])} if {_py(e[1])} else {_py(e[3])})"
    raise ValueError(head)


if __name__ == "__main__":
    unittest.main()
