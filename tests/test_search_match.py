"""search.match / search.instantiate are godel.match / godel.substitute (GODEL_PURITY rule 1: one core).

Same answer with and without: the matcher search used to carry (kept here only as the oracle) and the core-backed
one give the same bindings, and the same instantiation, over every rule card against instances of every rule and
random terms."""
import random
import unittest

from helpers import model_ctx

from cardmodel.engines import search


def old_match(pattern, expr, b=None):
    b = {} if b is None else b
    if isinstance(pattern, str) and pattern.startswith("?"):
        if pattern in b:
            return b if b[pattern] == expr else None
        b[pattern] = expr
        return b
    if isinstance(pattern, list) and isinstance(expr, list):
        if len(pattern) != len(expr) or pattern[0] != expr[0]:
            return None
        for p, e in zip(pattern[1:], expr[1:]):
            if old_match(p, e, b) is None:
                return None
        return b
    return b if pattern == expr else None


def old_instantiate(pattern, b):
    if isinstance(pattern, str) and pattern.startswith("?"):
        return b.get(pattern, pattern)
    if isinstance(pattern, list):
        return [old_instantiate(p, b) for p in pattern]
    return pattern


def subterms(t):
    yield t
    if isinstance(t, list) and t and t[0] not in ("var", "int", "float", "bool", "str", "const"):
        for x in t[1:]:
            yield from subterms(x)


class SameAnswer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = search.load_rules(model_ctx().store)

    def _terms(self, rng):
        leaves = [["var", "x"], ["var", "y"], ["var", "a"], ["int", 0], ["int", 1], ["int", 2]]
        pool = list(leaves)
        for r in self.rules:                     # instances of every rule side, and every subterm of them
            for side in (r.lhs, r.rhs):
                for _ in range(2):
                    vals = {v: rng.choice(pool) for v in search._pattern_vars(side)}
                    inst = old_instantiate(side, vals)
                    pool.extend(subterms(inst))
        out = list(pool)
        for _ in range(400):                     # random recombinations of those pieces
            t = rng.choice(pool)
            if isinstance(t, list) and len(t) > 1 and t[0] not in ("var", "int", "float", "bool", "str", "const"):
                t = list(t)
                t[rng.randrange(1, len(t))] = rng.choice(pool)
            out.append(t)
        return out

    def test_rules_and_random_terms(self):
        rng = random.Random(20261105)
        terms = self._terms(rng)
        n = hits = 0
        for r in self.rules:
            for t in terms:
                n += 1
                want, got = old_match(r.lhs, t), search.match(r.lhs, t)
                self.assertEqual(want, got, (r.name, t))
                if want is not None:
                    hits += 1
                    self.assertEqual(old_instantiate(r.rhs, want), search.instantiate(r.rhs, got), (r.name, t))
        self.assertGreater(hits, len(self.rules))   # the comparison exercised real matches, not only failures

    def test_term_variable_in_pattern_is_a_constant(self):
        pat = ["+", "?a", ["var", "x"]]
        for t in (["+", ["int", 1], ["var", "x"]], ["+", ["int", 1], ["var", "y"]], ["+", ["var", "x"], ["int", 1]]):
            self.assertEqual(old_match(pat, t), search.match(pat, t))

    def test_unbound_variable_stays(self):
        self.assertEqual(search.instantiate(["*", "?a", "?b"], {"?a": ["int", 2]}), ["*", ["int", 2], "?b"])


if __name__ == "__main__":
    unittest.main()
