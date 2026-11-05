"""Strings in the IR (str): op semantics, lifting from Python, unsupported constructs, codegen, and the examples."""
import copy
import unittest

from helpers import ROOT, SEED, SLOW, model_ctx, seed_note

from cardmodel.engines import conformance, translate
from cardmodel.engines.codegen import EmitGap, Emitter
from cardmodel.engines.context import Ctx
from cardmodel.engines.frontend_python import lift_source, module_for
from cardmodel.engines.ir import Interpreter, IRError, op_table
from cardmodel.engines.runners import parse_values

EXAMPLE = ROOT / "examples" / "strings" / "strings.py"
TRICKY = ["", "a", "\u00e9", "e\u0301", "\U0001f600", "\uff5e\U0001f600", "\x00\"\\#{$}\n\t", "\u4e2d\u6587 ok",
          "\U0001f1f8\U0001f1ea", "\r\n"]

UNSUPPORTED = '''
def fstring(s: str) -> str:
    return f"{s}!"

def repeat(s: str) -> str:
    return s * 3

def method(s: str) -> str:
    return s.upper()

def float_text(x: float) -> str:
    return str(x)

def last(s: str) -> str:
    return s[-1]

def hex_int(s: str) -> int:
    return int(s, 16)

def percent(n: int) -> str:
    return "%d" % n

def truthy(s: str) -> bool:
    if s:
        return True
    return False

def stepped(s: str) -> str:
    return s[::2]

def mixed(s: str, n: int) -> bool:
    return s == n

def surrogate(s: str) -> str:
    return "\\ud800"
'''


class Ops(unittest.TestCase):
    """The reference semantics (ir.eval) of the str op cards."""

    @classmethod
    def setUpClass(cls):
        cls.ops = model_ctx().ops

    def ev(self, op, *args):
        return self.ops[op].fn(*args)

    def test_code_points_not_bytes_or_utf16_units(self):
        self.assertEqual(self.ev("STR_LEN", "\U0001f600\u00e9"), 2)
        self.assertEqual(self.ev("STR_LEN", "e\u0301"), 2)          # a grapheme of two code points
        self.assertEqual(self.ev("STR_AT", "a\U0001f600b", 1), 0x1F600)
        self.assertEqual(self.ev("STR_AT", "a\U0001f600b", 2), ord("b"))
        self.assertEqual(self.ev("STR_CMP", "\uff5e", "\U0001f600"), -1)   # UTF-16 units would say 1

    def test_slice_and_find_are_pythons(self):
        for s in TRICKY:
            for a in range(-12, 13, 3):
                for b in range(-12, 13, 4):
                    self.assertEqual(self.ev("STR_SLICE", s, a, b), s[a:b], (s, a, b))
            for sub in ("", "a", "\U0001f600", "ok"):
                for start in (-20, -2, 0, 1, len(s), len(s) + 1, 30):
                    self.assertEqual(self.ev("STR_FIND", s, sub, start), s.find(sub, start), (s, sub, start))

    def test_errors_outside_the_domain(self):
        for op, args in [("STR_AT", ("ab", 2)), ("STR_AT", ("ab", -1)), ("STR_AT", ("", 0)),
                         ("STR_FROM_CODE", (0xD800,)), ("STR_FROM_CODE", (0x110000,)), ("STR_FROM_CODE", (-1,)),
                         ("STR_ORD", ("",)), ("STR_ORD", ("ab",)),
                         ("STR_TO_INT", ("",)), ("STR_TO_INT", ("1_000",)), ("STR_TO_INT", ("--1",)),
                         ("STR_TO_INT", ("\u0663",)), ("STR_TO_INT", ("1 2",)), ("STR_TO_INT", ("+",))]:
            with self.assertRaises(IRError, msg=(op, args)):
                self.ev(op, *args)

    def test_to_int_and_from_int(self):
        for text, v in [("0", 0), ("-0", 0), ("+7", 7), (" \t12\n", 12), ("007", 7),
                        ("-9223372036854775808", -2**63), ("123456789012345678901234567890", 123456789012345678901234567890)]:
            self.assertEqual(self.ev("STR_TO_INT", text), v)
            self.assertEqual(self.ev("STR_TO_INT", text), int(text))
        for v in (0, -1, 2**63 - 1, -2**63, 10**30):
            self.assertEqual(self.ev("STR_FROM_INT", v), str(v))

    def test_runner_reads_code_points(self):
        self.assertEqual(parse_values(["s:", "s:97 128512", "i:3", "l:1", "s:0"]), ["", "a\U0001f600", 3, ["\x00"]])


class Lift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.src = EXAMPLE.read_text(encoding="utf-8")
        cls.lifted = {lf.name: lf for lf in lift_source(cls.src, cls.ctx.ops)}
        cls.ns = {}
        exec(cls.src, cls.ns)

    def run_ir(self, name, *args):
        return Interpreter(module_for(name, list(self.lifted.values())), self.ctx.ops).call(name, list(args))

    def test_every_example_lifts(self):
        self.assertEqual({n: lf.reasons for n, lf in self.lifted.items() if not lf.ok}, {})

    def test_lifted_functions_match_python_on_tricky_text(self):
        for name, lf in self.lifted.items():
            params = [p["type"] for p in lf.ir["params"]]
            for i, s in enumerate(TRICKY):
                args = [s if t == "str" else (i - 3 if t == "int" else s) for t in params]
                if name == "contains_both":
                    args = [s, s[:1], TRICKY[-1 - i]]
                try:
                    want = self.ns[name](*args)
                except Exception:  # noqa: BLE001 -- outside Python's domain (int("x")): the IR must fail too
                    with self.assertRaises(IRError, msg=(name, args)):
                        self.run_ir(name, *args)
                    continue
                self.assertEqual(self.run_ir(name, *args), want, (name, args))

    def test_scanning_primitives(self):
        self.assertEqual(self.run_ir("scan_int", "x = -42;", 3), -42)
        self.assertEqual(self.run_ir("scan_int", "  +7\u00e9", 0), 7)
        self.assertEqual(self.run_ir("sum_fields", "12, -3,4"), 13)
        self.assertEqual(self.run_ir("count_occurrences", "\U0001f600a\U0001f600a\U0001f600", "\U0001f600a"), 2)
        self.assertEqual(self.run_ir("utf8_size", "a\u00e9\u4e2d\U0001f600"), 10)

    def test_unsupported_constructs_are_reported_with_lines(self):
        lifted = {lf.name: lf for lf in lift_source(UNSUPPORTED, self.ctx.ops)}
        lines = {"fstring": 3, "repeat": 6, "method": 9, "float_text": 12, "last": 15, "hex_int": 18, "percent": 21,
                 "truthy": 24, "stepped": 29, "mixed": 32, "surrogate": 35}
        for name, line in lines.items():
            self.assertFalse(lifted[name].ok, name)
            self.assertTrue(lifted[name].reasons[0].startswith(f"line {line}:"), (name, lifted[name].reasons))


class Codegen(unittest.TestCase):
    def test_lean_states_a_gap(self):
        ctx = model_ctx()
        fn = {"name": "f", "params": [{"name": "s", "type": "str"}], "returns": "int", "locals": {},
              "body": [{"k": "return", "value": ["STR_LEN", ["var", "s"]]}]}
        with self.assertRaises(EmitGap):
            Emitter(ctx.store, "lean", ctx.ops).program({"entry": "f", "functions": [fn]}, [["x"]])

    def test_literals_escape_every_code_point(self):
        """A literal is the same string in every target: no quote, backslash, interpolation or control survives."""
        ctx = model_ctx()
        text = "\x00\"\\#{$}\n\t'\u00e9\U0001f600"
        for lang in ("python", "javascript", "java", "ruby", "rust", "go", "lua", "swift"):
            lit = Emitter(ctx.store, lang, ctx.ops).lit("str", text)
            body = lit[lit.index('"') + 1:lit.rindex('"')]
            self.assertTrue(all(0x20 <= ord(c) < 0x7F for c in body), (lang, lit))
            if lang == "ruby":                   # "#{" interpolates in Ruby: every # is escaped
                self.assertNotIn("#", body)

    def test_wrong_templates_are_caught(self):
        """UTF-16 length in JavaScript and UTF-16 order in Java are what a naive card would use; both must fail."""
        ctx = model_ctx()
        ops = copy.deepcopy(op_table(ctx.store))
        ops["STR_LEN"].card["emit"]["javascript"] = "BigInt(({0}).length)"
        ops["STR_CMP"].card["emit"]["java"] = "((long) Integer.signum(({0}).compareTo({1})))"
        bad = Ctx(ctx.store)
        bad.__dict__["ops"] = ops
        for lang, op, cell in (("javascript", "STR_LEN", "t_str_len_s"), ("java", "STR_CMP", "t_str_cmp_s_s")):
            if not ctx.available(lang)[0]:
                continue
            rep = conformance.matrix(bad, langs=[lang], seed=SEED, samples=16, ops=[op])
            self.assertEqual(rep["languages"][lang]["cells"][cell]["status"], "fail", f"{lang} {seed_note(self)}")


class Examples(unittest.TestCase):
    """examples/strings agree with the Python original in other languages."""

    def test_examples_agree_across_languages(self):
        ctx = model_ctx()
        lifted = lift_source(EXAMPLE.read_text(encoding="utf-8"), ctx.ops)
        langs = None if SLOW else [l for l in ("python", "javascript", "c") if ctx.available(l)[0]]
        names = [lf.name for lf in lifted] if SLOW else ["reverse", "caesar", "order", "scan_int", "sum_fields",
                                                          "label"]
        for name in names:
            card = translate.function_card(ctx, name, lifted, "strings.py", seed=SEED)
            self.assertEqual(card["verification"]["lift_fidelity"]["mismatched"], 0, name)
            self.assertGreaterEqual(len(card["vectors"]), 6, name)
            rep = translate.verify_function(ctx, card, langs=langs, seed=SEED)
            bad = {l: r for l, r in rep["languages"].items() if r["status"] in ("fail", "error")}
            self.assertEqual(bad, {}, f"{name} {seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
