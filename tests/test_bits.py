"""The smallest piece, mastered (engines/bits.py, level L01 of cards/understanding): every function of at most two
bits derived from the op cards, with proven-smallest circuits, completeness of every gate set, and laws found by
enumeration. Every check here is exhaustive, and the minimality and law checks use oracles independent of the
engine's own search (a breadth-first search over sets of reachable tables; the IR interpreter on every row)."""
import itertools
import json
import unittest

from helpers import ROOT, model_ctx

from cardmodel.engines import bits as B
from cardmodel.engines import understanding as U
from cardmodel.engines.ir import Interpreter

CTX = model_ctx()
RES = B.master(CTX.ops)
FN = {f["name"]: f for f in RES["functions"]}


def nand_reachable(max_gates: int) -> dict:
    """Independent oracle: the fewest NAND gates for each two-input table, by breadth-first search over the *set*
    of tables a circuit has computed (a different algorithm from the engine's deepening over programs)."""
    nand = lambda a, b: ~(a & b) & 0xF     # noqa: E731 -- tables as 4-bit masks, bitwise
    start = frozenset({0b1100, 0b1010})
    best = {t: 0 for t in start}
    frontier = {start}
    for k in range(1, max_gates + 1):
        nxt = set()
        for nodes in frontier:
            for a, b in itertools.combinations_with_replacement(sorted(nodes), 2):
                t = nand(a, b)
                if t not in nodes:
                    nxt.add(nodes | {t})
                    best.setdefault(t, k)
        frontier = nxt
    return best


def eval_ir(term, row) -> bool:
    fn = {"name": "f", "params": [{"name": v, "type": "bool"} for v in B.VARS], "returns": "bool", "locals": {},
          "body": [{"k": "return", "value": term}]}
    return Interpreter({"functions": [fn]}, CTX.ops).call("f", list(row))


class TestBits(unittest.TestCase):
    def test_op_cards_are_observed_not_stated(self):
        obs = {o["op"]: o["table"] for o in RES["observed"]}
        # the tables come from running the cards; the expectations here are written from the definitions
        self.assertEqual(obs["AND"], B.table_of(lambda a, b: a and b, 2))
        self.assertEqual(obs["OR"], B.table_of(lambda a, b: a or b, 2))
        self.assertEqual(obs["CMP_EQ"], B.table_of(lambda a, b: a == b, 2))
        self.assertEqual(obs["CMP_NE"], B.table_of(lambda a, b: a != b, 2))
        self.assertEqual(obs["NOT"], B.table_of(lambda a: not a, 1))
        self.assertEqual(obs["IF_EXPR"], B.table_of(lambda c, a, b: a if c else b, 3))

    def test_the_space(self):
        self.assertEqual(sorted(f["table"] for f in RES["functions"]), list(range(16)))
        deps = sorted(len(f["depends_on"]) for f in RES["functions"])
        self.assertEqual(deps, [0, 0, 1, 1, 1, 1] + [2] * 10)     # constants and one-bit functions found inside

    def test_every_function_runs_in_the_interpreter(self):
        for f in RES["functions"]:
            term = f["over_op_cards"]["term"]
            self.assertTrue(f["over_op_cards"]["ir_checked"], f["name"])
            for r, (x, y) in enumerate(B.rows(2)):
                self.assertEqual(eval_ir(term, (x, y, False)), bool(f["table"] >> r & 1), f["name"])

    def test_smallest_nand_circuits_against_an_independent_search(self):
        oracle = nand_reachable(B.MAX_GATES)
        self.assertEqual(len(oracle), 16)
        for f in RES["functions"]:
            self.assertEqual(f["over_sole_gate"]["NAND"]["gates"], oracle[f["table"]], f["name"])
        # the textbook counts, for a reader: NOT 1, AND 2, OR 3, NOR 4, XOR 4, XNOR 5
        self.assertEqual([FN[n]["over_sole_gate"]["NAND"]["gates"] for n in ("NOT_X", "AND", "OR", "NOR", "XOR",
                                                                             "XNOR")], [1, 2, 3, 4, 4, 5])

    def test_nor_is_the_dual_of_nand(self):
        dual = {f["table"]: (~f["table"]) & 0xF for f in RES["functions"]}
        by_table = {f["table"]: f for f in RES["functions"]}
        for f in RES["functions"]:
            # NOR(x', y')' = NAND: complementing inputs and output swaps the two gates, so sizes swap too
            mirror = B.table_of(lambda x, y, t=f["table"]: not (t >> (2 * (not x) + (not y)) & 1), 2)
            self.assertEqual(f["over_sole_gate"]["NOR"]["gates"], by_table[mirror]["over_sole_gate"]["NAND"]["gates"])
        self.assertEqual(len(dual), 16)

    def test_smallest_over_the_op_cards(self):
        self.assertEqual({n: FN[n]["over_op_cards"]["gates"] for n in ("AND", "XOR", "NAND", "X_IMPLIES_Y", "X")},
                         {"AND": 1, "XOR": 1, "NAND": 2, "X_IMPLIES_Y": 2, "X": 0})
        self.assertEqual(B.show_term(FN["NAND"]["over_op_cards"]["term"]), "NOT(AND(x, y))")   # tie to the cheaper

    def test_sufficiency(self):
        s = RES["sufficiency"]
        self.assertEqual(sorted(s["sole"]), ["NAND", "NOR"])
        self.assertEqual(s["post_disagreements"], 0)
        self.assertFalse(s["unary_complete"])
        self.assertEqual(len(s["obstructions"]), 4)
        self.assertEqual(s["post_inside"], {"self_dual": ["affine"]})
        cl = B.closure_masks()
        mask = lambda *names: sum(1 << B.LABELS_INV[n] for n in names)   # noqa: E731
        full = (1 << 16) - 1
        self.assertEqual(cl[mask("NOT_X", "AND")], full)
        self.assertEqual(cl[mask("XOR", "AND", "TRUE")], full)
        self.assertNotEqual(cl[mask("AND", "OR")], full)                  # monotone
        self.assertNotEqual(cl[mask("XOR", "XNOR")], full)                # affine
        self.assertNotEqual(cl[mask("NOT_X", "NOT_Y", "TRUE", "FALSE")], full)

    def test_every_law_holds_on_every_row_in_the_interpreter(self):
        laws = RES["laws"]["laws"]
        self.assertGreater(len(laws), 0)
        for law in laws:
            for row in B.rows(3):
                self.assertEqual(eval_ir(law["lhs"], row), eval_ir(law["rhs"], row), B.law_text(law))

    def test_classic_laws_rediscovered(self):
        self.assertEqual({k for k, v in B.rediscovered(RES).items() if not v}, set())

    def test_level_two_starts(self):
        l2 = RES["level2"]
        self.assertEqual((l2["found"], l2["functions"]), (256, 256))
        self.assertEqual(l2["full_adder"]["sum"]["size"], 2)

    def test_mastery(self):
        for level in ("L00_bit", "L01_two_bit_functions"):
            self.assertTrue(all(m["ok"] for m in B.mastery(RES, level)), level)


class TestRoadmap(unittest.TestCase):
    def test_map_is_consistent_and_status_computed(self):
        a = U.assess(CTX.store, CTX.ops, {"engines/bits.py": RES})
        self.assertEqual(a["problems"], [])
        self.assertEqual(a["status"]["L00_bit"], "mastered")
        self.assertEqual(a["status"]["L01_two_bit_functions"], "mastered")
        self.assertEqual(a["status"]["L02_n_bit_functions"], "next")
        for c in a["levels"]:       # every mastered level's card lists exactly its engine's criteria
            if a["status"][c["name"]] == "mastered":
                self.assertEqual(len(c["mastery"]), len(a["criteria"][c["name"]]))

    def test_a_broken_map_is_caught(self):
        cards = [{"name": "L00_bit", "level": 0, "builds_on": []},
                 {"name": "L01_x", "level": 1, "builds_on": ["L02_y"]},
                 {"name": "L02_y", "level": 2, "builds_on": []}]
        self.assertEqual(len(U.problems(cards)), 2)

    def test_doc_is_generated(self):
        doc = (ROOT / "docs" / "UNDERSTANDING.md").read_text(encoding="utf-8")
        self.assertEqual(doc, U.render(CTX.store, CTX.ops, {"engines/bits.py": RES}),
                         "regenerate: cardmodel --no-project basics roadmap --write docs/UNDERSTANDING.md")

    def test_saved_cards_are_derived(self):
        """The boolfn cards are what the engine derives now (cardmodel basics bits --save), never edited by hand."""
        def pack(name):
            path = ROOT / "cards" / "boolfn" / f"_pack_{name}.jsonl"
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        norm = lambda cards: [json.loads(json.dumps({**c, "category": "boolfn"}, sort_keys=True))  # noqa: E731
                              for c in cards]
        key = lambda c: c["name"]    # noqa: E731
        self.assertEqual(sorted(pack("two_bits"), key=key), sorted(norm(B.function_cards(RES)), key=key))
        self.assertEqual(sorted(pack("laws"), key=key), sorted(norm(B.law_cards(RES)), key=key))


if __name__ == "__main__":
    unittest.main()
