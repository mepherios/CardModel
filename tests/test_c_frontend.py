"""C in: fixed-width integers, arrays as lists, C trees observed and learned from, every lift witnessed by gcc/clang.

The C frontend is the text frontend's C dialect (engines/frontend_text.py). These tests pin what HANDOVER §8 item 3
asks of it: C functions lift into the same IR as Python's (so C -> Python/Rust/Go/... with the same witness), C's
own integer semantics are kept (u8..u32 wrap modulo 2^w through WRAPU/WRAPS, the usual arithmetic conversions,
octal literals), arrays passed with their length read as lists, and `learn` learns from a C tree: every promoted
function's lift has run against the original C.
"""
import random
import unittest
import zlib

from helpers import ROOT, SEED, TempProject, model_ctx, seed_note

from cardmodel.engines import frontends as F
from cardmodel.engines import translate as T
from cardmodel.engines import values as V
from cardmodel.engines.frontend_python import module_for
from cardmodel.engines.ir import Interpreter
from cardmodel.engines.learn import learn
from cardmodel.engines.observe import observe

EX = ROOT / "examples" / "c"


def _lift(ctx, name):
    src = (EX / name).read_text(encoding="utf-8")
    return src, {lf.name: lf for lf in F.lift(ctx, src, "c")}


def _call(ctx, lifted, fn, *args):
    module = module_for(fn, list(lifted.values()))
    return Interpreter(module, ctx.ops, step_limit=2_000_000).call(fn, list(args))


def _xorshift32(x):
    x &= 0xFFFFFFFF
    x ^= (x << 13) & 0xFFFFFFFF
    x ^= x >> 17
    x ^= (x << 5) & 0xFFFFFFFF
    return x


class FixedWidth(unittest.TestCase):
    """C's integer conversions, as the IR's WRAPU/WRAPS (FOUNDATIONS.md D1)."""

    def test_every_function_lifts(self):
        ctx = model_ctx()
        for name in ("bits.c", "stats.c"):
            _, lifted = _lift(ctx, name)
            bad = {n: lf.reasons for n, lf in lifted.items() if not lf.ok}
            self.assertEqual(bad, {}, name)

    def test_values_are_c_values(self):
        ctx = model_ctx()
        _, L = _lift(ctx, "bits.c")
        data = list(b"123456789")
        self.assertEqual(_call(ctx, L, "crc32", data, len(data)), zlib.crc32(bytes(data)))
        wiki = list(b"Wikipedia")
        self.assertEqual(_call(ctx, L, "adler32", wiki, len(wiki)), zlib.adler32(bytes(wiki)))
        # a byte array read from C converts each element: -1 is 255
        self.assertEqual(_call(ctx, L, "crc32", [-1, 0], 2), zlib.crc32(bytes([255, 0])))
        rng = random.Random(SEED)
        for _ in range(20):
            x = rng.randrange(-(2 ** 40), 2 ** 40)
            self.assertEqual(_call(ctx, L, "xorshift32", x), _xorshift32(x), seed_note(self))
        self.assertEqual(_call(ctx, L, "add_u8", 200, 100), 44)
        self.assertEqual(_call(ctx, L, "to_i8", 200), -56)
        self.assertEqual(_call(ctx, L, "sum_i16", 30000, 30000), 60000 - 65536)
        self.assertEqual(_call(ctx, L, "rotl16", 0x8001, 1), 0x0003)
        self.assertIs(_call(ctx, L, "lt_mixed", -1, 1), False)          # -1 converts to 4294967295
        self.assertIs(_call(ctx, L, "lt_mixed", 1, 2), True)
        self.assertEqual(_call(ctx, L, "div_mixed", -7, 2), (2 ** 32 - 7) // 2)

    def test_literals_and_steps(self):
        ctx = model_ctx()
        src = ("#include <stdint.h>\n"
               "int64_t oct(void) { return 017 + 0x10; }\n"
               "uint8_t up(int n) { uint8_t c = 250; for (int i = 0; i < n; i++) c++; return c; }\n"
               "uint32_t neg(uint32_t x) { return -x; }\n"
               "int32_t narrow(int64_t x) { int32_t y = x; return y; }\n")
        L = {lf.name: lf for lf in F.lift(ctx, src, "c")}
        self.assertTrue(all(lf.ok for lf in L.values()), {n: lf.reasons for n, lf in L.items()})
        self.assertEqual(_call(ctx, L, "oct"), 15 + 16)
        self.assertEqual(_call(ctx, L, "up", 10), 4)
        self.assertEqual(_call(ctx, L, "neg", 1), 2 ** 32 - 1)
        self.assertEqual(_call(ctx, L, "narrow", 2 ** 31), -(2 ** 31))


class Arrays(unittest.TestCase):
    def test_arrays_are_lists(self):
        ctx = model_ctx()
        _, L = _lift(ctx, "stats.c")
        self.assertEqual(L["sum"].ir["params"][0]["type"], "list[int]")
        self.assertEqual(L["mean"].ir["params"][0]["type"], "list[float]")
        self.assertEqual(_call(ctx, L, "sum", [1, 2, 3], 3), 6)
        self.assertEqual(_call(ctx, L, "dot", [1, 2], [3, 4], 2), 11)
        self.assertEqual(_call(ctx, L, "best_prefix", [2, -5, 4, 3], 4), 2 - 5 + 4 + 3)
        self.assertEqual(_call(ctx, L, "distinct_small", [3, -3, 7, 500, 101], 5), 3)
        self.assertEqual(_call(ctx, L, "horner", 2), 3 - 4 + 0 + 40)
        self.assertAlmostEqual(_call(ctx, L, "mean", [1.0, 2.0], 2), 1.5)


class Unsupported(unittest.TestCase):
    def test_reported_with_its_line_never_guessed(self):
        ctx = model_ctx()
        cases = {
            "void scale(int64_t *xs, int64_t n) { xs[0] = n; }": "void",
            "int64_t w(int64_t *xs, int64_t n) {\n  xs[0] = n;\n  return n; }": "writes an element of the parameter",
            "int64_t d(const int64_t *xs) { return *xs; }": "line",
            "int64_t g(int64_t m[4][4]) { return m[0][0]; }": "multi-dimensional",
            "int64_t pp(int64_t **m) { return 0; }": "pointer to pointer",
            "uint64_t h(uint64_t x) { return x * 31; }": "unsigned 64-bit",
            "size_t z(size_t n) { return n; }": "unsigned 64-bit",
            "int c(char ch) { return ch; }": "char",
            "struct P { int x; };\nint px(struct P p) { return p.x; }": "line",
            "int64_t di(int64_t n) {\n  int64_t a[4] = {[1] = 2};\n  return a[1]; }": "designated",
        }
        for src, why in cases.items():
            lifted = [lf for lf in F.lift(ctx, "#include <stdint.h>\n#include <stddef.h>\n" + src, "c")]
            self.assertTrue(lifted, src)
            for lf in lifted:
                self.assertFalse(lf.ok, src)
                text = " ".join(lf.reasons)
                self.assertIn(why, text, src)
                self.assertRegex(text, r"line \d+", src)


class Witness(unittest.TestCase):
    """Every lift of examples/c agrees with the C compiler's own build of the original, and a wrong lift fails."""

    def setUp(self):
        self.ctx = model_ctx()
        if not self.ctx.available("c")[0]:
            self.skipTest("no C compiler on this host")

    def _inputs(self, module):
        interp = Interpreter(module, self.ctx.ops, step_limit=200_000)
        _, ok = T.infer_domain(self.ctx, module, lambda *a: interp.call(module["entry"], list(a)), want=24,
                               seed=SEED)
        return ok + F.sample_inputs(module, 12, SEED)

    def test_examples_agree_with_gcc(self):
        for name in ("bits.c", "stats.c"):
            src, L = _lift(self.ctx, name)
            for fn, lf in L.items():
                module = module_for(fn, list(L.values()))
                res = F.witness_source(self.ctx, "c", src, module, self._inputs(module), lf.src_types)
                self.assertEqual(res["status"], "pass", f"{name} {fn}: {res} {seed_note(self)}")
                self.assertGreaterEqual(res["checks"], 10, f"{name} {fn}: {res}")

    def test_wrong_lift_is_caught(self):
        """The same IR with C's wraps or conversions left out disagrees with the compiled C."""
        src, L = _lift(self.ctx, "bits.c")
        for fn, args in (("add_u8", [[200, 100], [255, 1]]), ("lt_mixed", [[-1, 1], [-5, 3]]),
                         ("crc32", [[[200, 13, 7], 3]])):
            module = module_for(fn, list(L.values()))
            bad = _unwrap(module)
            self.assertNotEqual(bad, module, fn)
            res = F.witness_source(self.ctx, "c", src, bad, args, L[fn].src_types)
            self.assertEqual(res["status"], "fail", f"{fn}: {res}")


def _unwrap(x):
    """The IR with every WRAPU/WRAPS replaced by its operand (a lift that ignored C's conversions)."""
    if isinstance(x, list):
        if x and x[0] in ("WRAPU", "WRAPS"):
            return _unwrap(x[1])
        return [_unwrap(v) for v in x]
    if isinstance(x, dict):
        return {k: _unwrap(v) for k, v in x.items()}
    return x


class LearnFromC(unittest.TestCase):
    """observe lifts a C tree as one project; learn promotes C functions only with their source witness."""

    def test_observe_and_learn_a_c_tree(self):
        files = {f"src/{p.name}": p.read_text(encoding="utf-8") for p in EX.glob("*.c")}
        files["src/gaps.c"] = "#include <stdint.h>\nint64_t first(const int64_t *xs) { return *xs; }\n"
        p = TempProject(files)
        try:
            ctx = p.ctx()
            obs = observe(ctx, p.dir)
            fns = {f["name"]: f for f in obs["functions"]}
            self.assertEqual(fns["crc32"]["language"], "c")
            self.assertTrue(fns["centred_sum"]["liftable"], fns["centred_sum"])     # calls sum() in stats.c
            self.assertFalse(fns["first"]["liftable"])
            self.assertRegex(" ".join(fns["first"]["reasons"]), r"line 2")
            if not ctx.available("c")[0]:
                self.skipTest("no C compiler on this host")
            rep = learn(ctx, p.dir, promote=True, seed=SEED, max_functions=4, langs=["python", "c"],
                        kinds={"function"})
            self.assertGreaterEqual(len(rep["promoted"]), 1, rep)
            for ref in rep["promoted"]:
                card = ctx.store.get(ref)
                self.assertEqual(card["provenance"]["source_lang"], "c")
                self.assertEqual(card["verification"]["source_witness"]["status"], "pass", ref)
        finally:
            p.cleanup()

    def test_cross_file_function_is_witnessed(self):
        if not model_ctx().available("c")[0]:
            self.skipTest("no C compiler on this host")
        from cardmodel.engines.learn import _module_lifted
        from cardmodel.engines.lift_project import lift_files
        files = {f"src/{p.name}": p.read_text(encoding="utf-8") for p in EX.glob("*.c")}
        p = TempProject(files)
        try:
            ctx = p.ctx()
            proj = lift_files(ctx, [(p.dir / k, "c") for k in files], methods=False, root=p.dir)
            for qual in ("src/use.c::centred_sum", "src/use.c::xorshift_n"):
                lifted, text = _module_lifted(proj, qual, p.dir)
                module = module_for(lifted[0].name, lifted)
                self.assertGreater(len(module["functions"]), 1, qual)
                interp = Interpreter(module, ctx.ops, step_limit=200_000)
                _, ok = T.infer_domain(ctx, module, lambda *a: interp.call(module["entry"], list(a)), want=24,
                                       seed=SEED)
                res = F.witness_source(ctx, "c", text, module, ok, proj.functions[qual].src_types)
                self.assertEqual(res["status"], "pass", f"{qual}: {res} {seed_note(self)}")
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()
