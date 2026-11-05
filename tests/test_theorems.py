"""Crystallised knowledge (CM23): a theorem's status follows its evidence and nothing else."""
import unittest

from helpers import SEED, TempProject, model_ctx, seed_note

from cardmodel.emit import lean as LE
from cardmodel.engines import equivalence as EQ
from cardmodel.engines import theorems as T
from cardmodel.lang.compile import compile_source


def thm(ctx, src):
    return compile_source(src, ctx.ops, ctx.store, name="t").theorems[0]


class TheoremTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_status_follows_evidence(self):
        ctx = self.ctx
        false = thm(ctx, "theorem bad(a: Int, b: Int): a % (b * b + 1) == a % (b + 1)")
        w = T.witness(false, ctx.ops, seed=SEED)
        self.assertEqual(w["status"], "refuted", seed_note(self))
        self.assertLessEqual(max(abs(v) for v in w["counterexample"].values()), 64)   # the small phase finds it
        settled = T.settle(false, w, {"status": "proved", "tactic": "omega", "lean": "x"}, None)
        self.assertEqual(settled["status"], "refuted")                                  # a proof never overrides
        pinned = thm(ctx, "theorem pin(a: Int) requires a >= 0, a <= 0: a * a == 0")
        self.assertEqual(T.witness(pinned, ctx.ops, seed=SEED)["status"], "vacuous")
        rare = thm(ctx, "theorem rare(a: Int) requires a == 123456789: a > 0")
        self.assertEqual(T.witness(rare, ctx.ops, seed=SEED)["status"], "vacuous")
        good = thm(ctx, "theorem ok(a: Int, b: Int): max(a, b) >= a")
        w = T.witness(good, ctx.ops, seed=SEED)
        self.assertEqual(w["status"], "witnessed")
        self.assertEqual(T.settle(good, w, None, None)["status"], "witnessed")
        undefined = thm(ctx, "theorem div(a: Int, b: Int): (a // b) * b + a % b == a")
        r = T.witness(undefined, ctx.ops, seed=SEED)
        self.assertEqual(r["status"], "refuted")
        self.assertIn("undefined", r["reason"])

    def test_nat_is_rendered_faithfully(self):
        card = thm(self.ctx, "theorem sub(n: Nat, m: Nat): n - m + m >= n")
        text = T.lean_theorem(card, self.ctx.store, self.ctx.ops, "omega")
        self.assertIn("(n m : Int)", text.replace("(n : Int) (m : Int)", "(n m : Int)"))
        self.assertIn("0 ≤ n", text)                     # Nat = an Int >= 0, so `-` keeps integer meaning

    @unittest.skipIf(LE.lean_exe() is None, "no Lean toolchain")
    def test_lean_proves_and_rejects(self):
        good = thm(self.ctx, "theorem g(a: Int, b: Int): a + b == b + a")
        bad = thm(self.ctx, "theorem b(a: Int, b: Int): a - b == b - a")
        res = T.prove([good, bad], self.ctx.store, self.ctx.ops, tactics=("omega", "grind"))["results"]
        self.assertEqual(res[good["name"]]["status"], "proved")
        self.assertEqual(res[bad["name"]]["status"], "unproved")


def _card(name, vars_, hyps, concl, semantics="card", **more):
    return {"name": name, "category": "theorem", "vars": [{"name": n, "type": t} for n, t in vars_], "hyps": hyps,
            "concl": concl, "semantics": semantics, "status": "conjecture", **more}


def _var(n):
    return ["var", n]


class Identity(unittest.TestCase):
    """One identity per statement (docs/GODEL_AUDIT.md step 2): the same theorem up to the names of its
    variables, whatever the names, the order of its hypotheses or the card that states it."""

    def test_identity_is_the_statement_up_to_names(self):
        a = _card("p", [("a", "int"), ("b", "int")], [["le", _var("a"), _var("b")], ["ge", _var("a"), ["int", 0]]],
                  ["eq", ["ADD", _var("a"), _var("b")], ["ADD", _var("b"), _var("a")]])
        b = _card("q", [("y", "int"), ("x", "int")], [["ge", _var("x"), ["int", 0]], ["le", _var("x"), _var("y")]],
                  ["eq", ["ADD", _var("x"), _var("y")], ["ADD", _var("y"), _var("x")]])
        self.assertEqual(T.identity(a), T.identity(b))            # names and hypothesis order are not structure
        self.assertEqual(T.alpha_statement(a), T.alpha_statement(b))
        self.assertTrue(T.identity(a).startswith("sha256:"))
        swapped = dict(a, concl=["eq", ["ADD", _var("b"), _var("a")], ["ADD", _var("a"), _var("b")]])
        nat = _card("p", [("a", "nat"), ("b", "int")], a["hyps"], a["concl"])
        lean = dict(a, semantics="lean")
        fewer = dict(a, hyps=a["hyps"][:1])
        ids = {T.identity(c) for c in (a, swapped, nat, lean, fewer)}
        self.assertEqual(len(ids), 5, "a side, a sort, the semantics and a hypothesis are structure")
        rec = T.identity_record(a)
        self.assertEqual((rec["hash"], rec["of"]), (T.identity(a), "theorem statement"))
        self.assertIn(rec["under"], EQ.RELATIONS)

    def test_the_store_groups_its_theorems_by_identity(self):
        groups = T.by_identity(model_ctx().store)
        cards = sum(len(v) for v in groups.values())
        more = {k: [c.qualified for c in v] for k, v in groups.items() if len(v) > 1}
        print(f"\n  theorem cards: {cards}, distinct statements: {len(groups)}, stated more than once: {len(more)}")
        self.assertGreater(len(groups), 0)
        for key, cards_ in groups.items():                         # one statement per group, by its α-form
            self.assertEqual({repr(T.alpha_statement(c)) for c in cards_} | {key for c in cards_ if False},
                             {repr(T.alpha_statement(cards_[0]))}, [c.qualified for c in cards_])

    def test_a_proof_is_kept_by_identity_and_not_repeated(self):
        calls = []

        def fake_check(exe, items, header=None, timeout_s=600):
            calls.append([n for n, _ in items])
            return {n: ("ok" if n != "anti" else "error: unsolved goals") for n, _ in items}
        comm = _card("comm", [("a", "int"), ("b", "int")], [],
                     ["eq", ["ADD", _var("a"), _var("b")], ["ADD", _var("b"), _var("a")]])
        same = _card("comm_again", [("x", "int"), ("y", "int")], [],
                     ["eq", ["ADD", _var("x"), _var("y")], ["ADD", _var("y"), _var("x")]])
        other = _card("anti", [("a", "int"), ("b", "int")], [],
                      ["eq", ["SUB", _var("a"), _var("b")], ["SUB", _var("b"), _var("a")]])
        proj = TempProject()
        exe, check = LE.lean_exe, LE.check_batch
        try:
            ctx = proj.ctx()
            LE.lean_exe = lambda: "/toolchains/leanprover--lean4---v4.35.0/bin/lean"
            LE.check_batch = fake_check
            r1 = T.prove([comm, other], ctx.store, ctx.ops, tactics=("omega",), ctx=ctx)["results"]
            self.assertEqual((r1["comm"]["status"], r1["anti"]["status"]), ("proved", "unproved"))
            self.assertEqual(len(calls), 1)
            kept = ctx.load_state(T.PROOF_CACHE)
            self.assertEqual(len(kept), 1, "only a proof is kept")
            r2 = T.prove([same, other], ctx.store, ctx.ops, tactics=("omega",), ctx=ctx)["results"]
            self.assertEqual(r2["comm_again"]["status"], "proved")                # the same theorem up to names
            self.assertEqual(r2["comm_again"]["cached"]["from"], "comm")
            self.assertIn("theorem cm_comm_again", r2["comm_again"]["lean"])       # rendered for this card
            self.assertEqual(calls[1], ["anti"], "the unproved one is tried again; the proved one is not")
            r3 = T.prove([same], ctx.store, ctx.ops, tactics=("grind",), ctx=ctx)["results"]
            self.assertEqual(len(calls), 3, "other tactics are another key")
            self.assertNotIn("cached", r3["comm_again"])
            T.prove([same], ctx.store, ctx.ops, tactics=("omega",))                # no ctx: no cache
            self.assertEqual(len(calls), 4)
        finally:
            LE.lean_exe, LE.check_batch = exe, check
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()
