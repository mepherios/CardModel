"""Logic as cards (CM24, CM27): fixpoint semantics, proofs, Lean certificates, mining, the model's own laws."""

import unittest

from helpers import TempProject, model_ctx, seed_note

from cardmodel.emit import lean as LE
from cardmodel.emit.lean_logic import certify
from cardmodel.engines import logic as L
from cardmodel.engines import mine as M
from cardmodel.engines import selflogic
from cardmodel.lang.compile import compile_source

FAMILY = """
parent(alice, bob). parent(bob, carol). parent(carol, dave). parent(eve, bob).
born(alice, 1931). born(bob, 1958). born(carol, 1984). born(dave, 2011). born(eve, 1933).
ancestor(X, Y) <- parent(X, Y).
ancestor(X, Z) <- parent(X, Y), ancestor(Y, Z).
root(X) <- parent(X, _), not parent(_, X).
gap(P, C, G) <- parent(P, C), born(P, A), born(C, B), G = B - A.
size(X, N) <- root(X), N = count { ancestor(X, _) }.
never: ancestor(X, X).
"""


class LogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.mod = compile_source(FAMILY, cls.ctx.ops, cls.ctx.store, name="fam")
        cls.model = L.evaluate(cls.mod.program, cls.ctx.ops)

    def test_least_model(self):
        m = self.model
        self.assertEqual(len(m.facts("ancestor")), 9)
        self.assertEqual(m.facts("root"), [("alice",), ("eve",)])
        self.assertTrue(m.holds("gap", ["bob", "carol", 26]))
        self.assertTrue(m.holds("size", ["alice", 3]))
        self.assertEqual(m.violations, [])

    def test_proofs_have_minimum_height(self):
        p = self.model.proof("ancestor", ["alice", "dave"])
        self.assertEqual(L.proof_stats(p)["height"], 3)
        chain = L.Program()
        for i in range(30):
            chain.add_fact("e", [i, i + 1])
        X, Y, Z = L.Var("X"), L.Var("Y"), L.Var("Z")
        chain.add_rule(L.Rule("t1", L.Atom("t", (X, Y)), (L.Atom("e", (X, Y)),)))
        chain.add_rule(L.Rule("t2", L.Atom("t", (X, Z)), (L.Atom("t", (X, Y)), L.Atom("t", (Y, Z)))))
        m = L.evaluate(chain, self.ctx.ops)
        self.assertEqual(L.proof_stats(m.proof("t", [0, 16]))["height"], 5)      # doubling: log2(16) + 1

    def test_constraint_violation_carries_a_proof(self):
        mod = compile_source(FAMILY + "parent(dave, alice).", self.ctx.ops, self.ctx.store, name="cyc")
        m = L.evaluate(mod.program, self.ctx.ops)
        self.assertTrue(m.violations)
        self.assertIn("premises", m.violations[0])

    def test_unsafe_and_unstratified_are_reported(self):
        from cardmodel.lang.compile import CompileError
        with self.assertRaises(CompileError) as e:
            compile_source("p(X, Y) <- q(X).", self.ctx.ops, self.ctx.store)
        self.assertIn("not bound", str(e.exception))
        with self.assertRaises(CompileError) as e:
            compile_source("n(1). p(X) <- n(X), not q(X). q(X) <- n(X), not p(X).", self.ctx.ops, self.ctx.store)
        self.assertIn("recursion through negation", str(e.exception))

    def test_budget_stops_unbounded_arithmetic(self):
        mod = compile_source("n(0). n(Y) <- n(X), Y = X + 1.", self.ctx.ops, self.ctx.store)
        with self.assertRaises(L.LogicLimit):
            L.evaluate(mod.program, self.ctx.ops, max_facts=2000)

    def test_rules_call_functions(self):
        mod = compile_source("fn sq(x: Int) -> Int = x * x\nn(3). n(4). big(N) <- n(N), sq(N) > 10.",
                             self.ctx.ops, self.ctx.store)
        from cardmodel.lang.run import _caller
        call, _ = _caller(self.ctx, mod)
        m = L.evaluate(mod.program, self.ctx.ops, call=call)
        self.assertEqual(m.facts("big"), [(4,)])

    @unittest.skipIf(LE.lean_exe() is None, "no Lean toolchain")
    def test_derivations_are_kernel_checked(self):
        targets = [("ancestor", ("alice", "dave")), ("root", ("eve",)), ("gap", ("bob", "carol", 26)),
                   ("size", ("alice", 3))]
        r = certify(self.model, targets)
        st = {t["fact"]: t["status"] for t in r["theorems"]}
        self.assertEqual(st["ancestor(alice, dave)"], "checked", r.get("detail"))
        self.assertEqual(st["root(eve)"], "checked")
        self.assertEqual(st["gap(bob, carol, 26)"], "checked")
        self.assertEqual(st["size(alice, 3)"], "not_exportable")          # aggregates: honest gap
        # anti-vacuity (CM07): a forged derivation must be rejected by the kernel
        forged = L.evaluate(self.mod.program, self.ctx.ops)
        key = ("ancestor", ("alice", "dave"))
        rule, env, premises = forged.why[key][1:]
        forged.why[("ancestor", ("dave", "alice"))] = ("rule", rule, {**env, "X": "dave", "Z": "alice"}, premises)
        forged.db.add("ancestor", ("dave", "alice"))
        r2 = certify(forged, [("ancestor", ("dave", "alice"))])
        self.assertEqual(r2["theorems"][0]["status"], "rejected", r2)

    def test_mining_deciphers_rules(self):
        prog = L.Program()
        pairs = [("a", "b"), ("a", "c"), ("b", "d"), ("b", "e"), ("c", "f"), ("d", "g"), ("e", "h")]
        for x, y in pairs:
            prog.add_fact("parent", [x, y])
        for x, y in pairs:
            for y2, z in pairs:
                if y == y2:
                    prog.add_fact("grandparent", [x, z])
        res = M.mine(M.relations(L.evaluate(prog, self.ctx.ops)))
        laws = {f["text"] for f in res["laws"]}
        self.assertIn("grandparent(X, Z) <- parent(X, Y), parent(Y, Z).", laws)
        self.assertNotIn("parent(Y, X) <- parent(X, Y).", laws)

    def test_programs_as_facts(self):
        from cardmodel.engines import codefacts
        from cardmodel.kernel import paths
        from cardmodel.lang.compile import compile_file
        prog = codefacts.facts_for(paths.home() / "arena" / "slowframework")
        rules = compile_file(paths.home() / "stdlib" / "program.card", self.ctx.ops, self.ctx.store)
        prog.rules.extend(rules.program.rules)
        m = L.evaluate(prog, self.ctx.ops)
        self.assertEqual(m.violations, [])                       # lifter and effect analysis agree (CM21)
        effectful = {t[0] for t in m.db.rel.get("effectful", ())}
        pure = {t[0] for t in m.db.rel.get("pure", ())}
        self.assertIn("online.login", effectful)
        self.assertTrue(any(f.startswith("mathx.") for f in pure))

    def test_self_theory_holds_and_catches_breaks(self):
        r = selflogic.evaluate_self(self.ctx)
        self.assertEqual(r["violation_count"], 0, r["violations"][:3])
        self.assertGreater(r["stats"]["given"], 1000)
        proj = TempProject()
        try:
            ctx = proj.ctx()
            ctx.store.save({"name": "broken_ref", "category": "suggestion", "statement": "planted",
                            "depends_on": ["op/NO_SUCH_OP"]})
            r2 = selflogic.evaluate_self(ctx)
            bad = [v for v in r2["violations"] if v["bindings"].get("D") == "op/NO_SUCH_OP"]
            self.assertTrue(bad, f"planted dangling reference not caught {seed_note(self)}")
        finally:
            proj.cleanup()


if __name__ == "__main__":
    unittest.main()

