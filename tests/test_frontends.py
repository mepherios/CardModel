"""Any language in: every language card with a frontend lifts into the card IR, and every lift is witnessed.

Default run: round trips through every codegen language (IR interpreter only), the idiomatic sources of all fifteen
text-frontend languages, and the source witness on c, javascript and ruby. CARDMODEL_SLOW=1 witnesses every
language whose toolchain this host has.
"""
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CLI, ROOT, SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import frontend_text as FT
from cardmodel.engines import frontends as F
from cardmodel.engines import values as V
from cardmodel.engines.codegen import EmitGap, emit_module
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter

DATA = ROOT / "tests" / "frontends"
TEXT_LANGS = ["c", "cpp", "csharp", "go", "java", "javascript", "julia", "kotlin", "lua", "php", "ruby", "rust",
              "swift", "typescript", "zig"]

# every function each idiomatic source defines must lift (main and module code are not functions to lift)
EXPECTED = {
    "algos.c": ["gcd", "collatz", "div_sum", "harmonic_skip3", "is_prime", "fib", "bits", "hyp_pow"],
    "algos.cpp": ["gcd", "clamp3", "mean", "tri"],
    "Algos.cs": ["Gcd", "Area"],
    "Algos.java": ["gcd", "collatz", "floorPair", "even", "avg"],
    "algos.kt": ["gcd", "sumTo", "evens", "sign", "half"],
    "algos.go": ["gcd", "collatz", "sumOdd", "norm"],
    "algos.rs": ["gcd", "collatz", "sum_squares", "countdown", "ratio", "classify", "wrap"],
    "algos.swift": ["gcd", "stepped", "scale"],
    "algos.zig": ["gcd", "triangle", "floorMix"],
    "algos.js": ["gcd", "collatz", "hyp", "mixed"],
    "algos.ts": ["gcd", "area"],
    "algos.php": ["gcd", "collatz", "avg"],
    "algos.rb": ["gcd", "collatz", "sum_to", "times_sum", "floor_pair", "harmonic"],
    "algos.lua": ["gcd", "collatz", "sum_down", "avg", "count_until"],
    "algos.jl": ["gcd2", "collatz", "iseven2", "triple_plus_one", "sumsq", "floormix", "half"],
}

# (file, function, args, expected): each language's own semantics for / and % on negative integers
SPOT = [
    ("algos.c", "div_sum", [-7, 2], -4),             # C: -7/2 = -3, -7%2 = -1
    ("algos.c", "gcd", [12, -18], 6),
    ("algos.c", "bits", [255], 8),
    ("algos.c", "is_prime", [97], True),
    ("Algos.java", "floorPair", [-7, 2], -3999),     # floorDiv -4, floorMod 1
    ("algos.rs", "wrap", [-7, 3], 2),                # rem_euclid
    ("algos.rs", "countdown", [4], 34),             # i = 3, 2, 1, 0
    ("algos.rb", "floor_pair", [-7, 2], -3999),      # Ruby floors
    ("algos.rb", "sum_to", [10], 37),
    ("algos.lua", "avg", [3, 4], 3.5),               # Lua: / is float division
    ("algos.lua", "sum_down", [4], 10),
    ("algos.lua", "count_until", [10], 4),
    ("algos.jl", "floormix", [-7, 2], -7),           # fld -4 + mod 1 + div -3 + rem -1
    ("algos.jl", "sumsq", [3], 14),
    ("algos.zig", "floorMix", [-7, 2], -6),          # @divFloor -4 + @mod 1 + @divTrunc -3
    ("algos.kt", "evens", [7], 4),
    ("algos.kt", "sign", [-5], -1),
    ("algos.swift", "stepped", [10], 24),            # 0+3+6+9 + 1+2+3
    ("algos.go", "sumOdd", [10], 25),
    ("algos.php", "avg", [3, 4], 3.5),
    ("algos.js", "mixed", [2.0, 3], 3.666666666666667),
    ("Algos.cs", "Gcd", [-12, 18], 6),
]


def _lift_file(ctx, name):
    path = DATA / name
    lang = F.language_for_path(ctx.store, path)
    src = path.read_text(encoding="utf-8")
    return lang, src, F.lift(ctx, src, lang)


class Registry(unittest.TestCase):
    def test_every_text_language_has_a_frontend(self):
        ctx = model_ctx()
        langs = F.frontend_languages(ctx.store)
        for lang in TEXT_LANGS + ["python", "cardlang"]:
            self.assertIn(lang, langs)
        for lang in TEXT_LANGS:
            self.assertIn(lang, FT.DIALECTS)

    def test_every_codegen_language_is_also_a_source(self):
        ctx = model_ctx()
        missing = [l for l in ctx.codegen_languages() if l not in F.frontend_languages(ctx.store) and l != "lean"]
        self.assertEqual(missing, [], "a codegen language with no frontend cannot be translated from")

    def test_language_for_path(self):
        ctx = model_ctx()
        self.assertEqual(F.language_for_path(ctx.store, "x/y.rs"), "rust")
        self.assertEqual(F.language_for_path(ctx.store, "Main.java"), "java")
        self.assertEqual(F.language_for_path(ctx.store, "a.py"), "python")
        self.assertIsNone(F.language_for_path(ctx.store, "README"))


class RoundTrip(unittest.TestCase):
    """lift(emit_L(f)) agrees with f for every codegen language L: codegen's output is always readable again."""

    def test_round_trip_every_codegen_language(self):
        ctx = model_ctx()
        src = (DATA / "corpus.py").read_text(encoding="utf-8")
        lifted = lift_source(src, ctx.ops)
        self.assertTrue(all(lf.ok for lf in lifted), [(lf.name, lf.reasons) for lf in lifted if not lf.ok])
        langs = [l for l in ctx.codegen_languages() if l in FT.DIALECTS]
        self.assertGreaterEqual(len(langs), 10)
        rng = random.Random(SEED)
        checked = 0
        for lf in lifted:
            module = module_for(lf.name, lifted)
            entry = next(f for f in module["functions"] if f["name"] == lf.name)
            gens = [{"bool": True} if p["type"] == "bool" else {"float": [-50.0, 50.0]} if p["type"] == "float"
                    else {"int": [-40, 40]} for p in entry["params"]]
            inputs = [list(a) for a in V.inputs(gens, 16, rng)]
            ref = Interpreter(module, ctx.ops, step_limit=200_000)
            for lang in langs:
                try:
                    code = emit_module(ctx.store, ctx.ops, lang, module)
                except EmitGap:
                    continue
                back = {b.name: b for b in FT.lift_source(code, ctx.ops, lang)}
                got = back.get(lf.name)
                self.assertTrue(got is not None and got.ok,
                                f"{lang} {lf.name}: {got.reasons if got else 'missing'}\n{code}")
                again = Interpreter(module_for(lf.name, list(back.values())), ctx.ops, step_limit=200_000)
                for args in inputs:
                    try:
                        want = ref.call(lf.name, list(args))
                    except Exception:  # noqa: BLE001 -- outside the domain
                        continue
                    have = again.call(lf.name, list(args))
                    self.assertTrue(V.same(want, have), f"{lang} {lf.name}{tuple(args)}: {want} != {have} "
                                                        f"{seed_note(self)}")
                    checked += 1
        self.assertGreater(checked, 500)


class Idiomatic(unittest.TestCase):
    """Hand-written code in each language (not codegen's output) lifts, with the language's own semantics."""

    def test_every_function_lifts(self):
        ctx = model_ctx()
        for name, want in EXPECTED.items():
            _, _, lifted = _lift_file(ctx, name)
            by = {lf.name: lf for lf in lifted}
            for fn in want:
                self.assertIn(fn, by, f"{name}: {fn} not found (found {sorted(by)})")
                self.assertTrue(by[fn].ok, f"{name}: {fn}: {by[fn].reasons}")

    def test_semantics_spot_values(self):
        ctx = model_ctx()
        cache = {}
        for name, fn, args, want in SPOT:
            if name not in cache:
                cache[name] = _lift_file(ctx, name)[2]
            module = module_for(fn, cache[name])
            got = Interpreter(module, ctx.ops, step_limit=200_000).call(fn, list(args))
            self.assertTrue(V.same(got, want), f"{name} {fn}{tuple(args)} = {got}, expected {want}")

    def test_unsupported_is_reported_not_guessed(self):
        ctx = model_ctx()
        cases = {
            "c": ("unsigned long h(unsigned long x) { return x * 31; }", "unsigned"),
            "rust": ("fn s(v: &Vec<i64>) -> i64 { v[0] }", "reference"),
            "go": ("func f(xs []int64) int64 { return xs[0] }", "type"),
            "java": ("class A { static float f(float x) { return x; } }", "binary32"),
            "ruby": ("def f(s)\n  puts s\nend\n", "I/O"),
            "javascript": ("function f(a) { return a.length; }", ".length"),
        }
        for lang, (src, why) in cases.items():
            lifted = F.lift(ctx, src, lang)
            self.assertEqual(len(lifted), 1, f"{lang}: {lifted}")
            self.assertFalse(lifted[0].ok, lang)
            self.assertIn(why, " ".join(lifted[0].reasons), f"{lang}: {lifted[0].reasons}")

    def test_emitted_helpers_lift_to_their_op_cards(self):
        """`cm_floormod(a, b)` in C, `Math.floorMod` in Java: the op cards' templates read backwards."""
        ctx = model_ctx()
        src = "static int64_t cm_floormod(int64_t a, int64_t b) { return a; }\n" \
              "int64_t f(int64_t a, int64_t b) { return cm_floormod(a, b) + Math.floorMod(a, b); }\n"
        lifted = {lf.name: lf for lf in F.lift(ctx, src, "c")}
        self.assertNotIn("cm_floormod", lifted)
        self.assertFalse(lifted["f"].ok)              # Math.floorMod is Java, not C
        java = "class A { static long f(long a, long b) { return Math.floorMod(a, b) + Math.floorDiv(a, b); } }"
        ir = F.lift(ctx, java, "java")[0].ir
        self.assertEqual(ir["body"][0]["value"][0], "ADD")
        self.assertEqual([e[0] for e in ir["body"][0]["value"][1:]], ["MOD", "FLOORDIV"])


class Witness(unittest.TestCase):
    """The original source, run by its own toolchain, agrees with the IR it was lifted to."""

    def test_sources_agree_with_their_lift(self):
        ctx = model_ctx()
        files = sorted(EXPECTED)
        wanted = None if SLOW else {"c", "javascript", "ruby"}
        ran = 0
        for name in files:
            lang, src, lifted = _lift_file(ctx, name)
            if wanted is not None and lang not in wanted:
                continue
            if not ctx.available(lang)[0]:
                continue
            for lf in lifted:
                if not lf.ok:
                    continue
                module = module_for(lf.name, lifted)
                res = F.witness_source(ctx, lang, src, module, F.sample_inputs(module, 12, SEED), lf.src_types)
                self.assertEqual(res["status"], "pass", f"{name} {lf.name}: {res} {seed_note(self)}")
                ran += 1
        if ran == 0:
            self.skipTest("no source toolchain on this host")

    def test_wrong_lift_is_caught(self):
        """A lift that read C's `/` as floor division must fail the witness on negative operands (CM07)."""
        ctx = model_ctx()
        if not ctx.available("c")[0]:
            self.skipTest("no C compiler on this host")
        lang, src, lifted = _lift_file(ctx, "algos.c")
        module = module_for("div_sum", lifted)
        bad = repr(module).replace("TRUNCDIV", "FLOORDIV").replace("'REM'", "'MOD'")
        module = eval(bad)  # noqa: S307 -- our own repr of a dict of lists
        res = F.witness_source(ctx, lang, src, module, [[-7, 2], [7, -2], [9, 4]])
        self.assertEqual(res["status"], "fail", res)

    def test_unavailable_toolchain_is_reported(self):
        ctx = model_ctx()
        lang, src, lifted = _lift_file(ctx, "algos.kt")
        module = module_for("gcd", lifted)
        res = F.witness_source(ctx, lang, src, module, [[12, 18]])
        self.assertIn(res["status"], ("no_harness", "unavailable"))


class Cli(unittest.TestCase):
    def test_translate_from_rust(self):
        ctx = model_ctx()
        if not ctx.available("rust")[0] or not ctx.available("c")[0]:
            self.skipTest("needs rustc and a C compiler")
        src = "\n".join((DATA / "algos.rs").read_text(encoding="utf-8").split("fn ratio")[0:1])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "part.rs"
            path.write_text(src, encoding="utf-8")
            p = subprocess.run(CLI + ["translate", str(path), "--to", "c,python", "--seed", str(SEED)],
                               capture_output=True, text=True, cwd=ROOT, timeout=900)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("rust source: pass", p.stdout)
        self.assertIn("collatz", p.stdout)

    def test_emit_from_ruby(self):
        p = subprocess.run(CLI + ["emit", "--lang", "c", str(DATA / "algos.rb"), "--function", "gcd"],
                           capture_output=True, text=True, cwd=ROOT, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("gcd(int64_t a, int64_t b)", p.stdout)


if __name__ == "__main__":
    unittest.main()
