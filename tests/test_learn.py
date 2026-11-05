"""Observe and the learning loop: proposals carry evidence; promotion needs it (CM04, CM15)."""
import unittest

from helpers import SEED, TempProject, seed_note

from cardmodel.engines.learn import MIN_EVIDENCE, learn
from cardmodel.engines.observe import observe

APP = {
    "app/core.py": '''
import json

def score(a: int, b: int) -> int:
    total = 0
    for i in range(a):
        total += (i * b) % 7
    return total

def area(w: float, h: float) -> float:
    return w * h / 2

def load(path):
    with open(path) as f:
        return json.loads(f.read())

def shout(cfg):
    return cfg.get("x") + cfg.get("y")
''',
    "app/util.py": '''
def double(x: int) -> int:
    return x * 2 + 0

def pick(cfg):
    return cfg.get("z")

def once(v):
    return frobnicate(v)
''',
    "web/app.js": "function f(a) { return Math.max(a, 1) + parseInt('3'); }\n// comment(not_a_call)\n",
}


class Observe(unittest.TestCase):
    def test_observation_counts_and_functions(self):
        p = TempProject(APP)
        try:
            obs = observe(p.ctx(), p.dir)
            t = obs["totals"]
            self.assertEqual(t["by_language"], {"python": 2, "javascript": 1})
            self.assertGreater(t["cards_fired"], 10)
            self.assertTrue(0 < t["named_fraction"] < 1)
            lifted = {f["name"]: f["liftable"] for f in obs["functions"]}
            self.assertEqual(lifted["score"], True)
            self.assertEqual(lifted["load"], False)
            self.assertNotIn("not_a_call", obs["fallback_calls_by_language"].get("javascript", {}))
            self.assertTrue(all(not f["path"].startswith("/") for f in obs["files"]))   # no user paths (L50)
        finally:
            p.cleanup()


class Learn(unittest.TestCase):
    def test_promotion_needs_evidence(self):
        p = TempProject(APP)
        try:
            ctx = p.ctx()
            rep = learn(ctx, p.dir, promote=True, seed=SEED, langs=["python", "javascript"])
            st = ctx.store
            st.invalidate()
            get = st.get("call/CALL_METHOD_GET")            # .get used 3 times in 2 files -> promoted
            self.assertIsNotNone(get, rep)
            self.assertGreaterEqual(get["metadata"]["evidence_count"], MIN_EVIDENCE)
            self.assertIsNone(st.get("call/CALL_FROBNICATE"))  # used once -> stays a proposal
            prop = st.get("proposal/prop_call_CALL_FROBNICATE")
            self.assertIsNotNone(prop)
            self.assertFalse(prop["ready"])
            self.assertIn("needs", prop["reason"])
        finally:
            p.cleanup()

    def test_learned_cards_cite_evidence(self):
        p = TempProject(APP)
        try:
            ctx = p.ctx()
            rep = learn(ctx, p.dir, promote=True, seed=SEED, langs=["python", "javascript", "c"])
            st = ctx.store
            st.invalidate()
            fns = [c for c in st.cards("function") if c.layer == "project"]   # the model has its own learned ones
            self.assertTrue(any(c["ir"]["entry"] == "score" for c in fns), rep)
            for c in fns:
                self.assertEqual(c["status"], "healthy")
                self.assertIn(f"observation/{rep['observation']}", c["provenance"]["learning_loop_refs"])
                self.assertIn(c["metadata"]["confidence"], ("established", "tentative"))
                self.assertGreaterEqual(len(c["metadata"]["agreeing_languages"]), 3)
            xs = [x for x in st.cards("xleq") if x.layer == "project"]
            self.assertTrue(xs and all(x["evidence_count"] >= 3 for x in xs))
            obs = st.get(f"observation/{rep['observation']}")
            self.assertIsNotNone(obs)                         # ground truth written once
            sugg = [x for x in st.cards("suggestion") if x.layer == "project"]
            self.assertTrue(any(s["to"] == "(x << 1)" for s in sugg), [s["statement"] for s in sugg])
            again = learn(ctx, p.dir, promote=True, seed=SEED, langs=["python"])
            self.assertEqual(again["observation"], rep["observation"])   # same content -> same observation
        finally:
            p.cleanup()


if __name__ == "__main__":
    unittest.main()


class RewriteSuggestions(unittest.TestCase):
    """A rewrite suggestion is ready only when it keeps the source's behaviour on every input checked, errors
    included: a rule that holds under a side condition (a != 0, 0 <= a) must not become an established
    suggestion for code that can reach the excluded inputs."""

    SRC = {"m.py": "def f(x):\n    return x // x\n\n"
                   "def g(x):\n    return x >> x\n\n"
                   "def h(x):\n    return (x * 2) + (x * 2)\n"}

    def test_domain_changing_rewrites_are_not_ready(self):
        from pathlib import Path
        from cardmodel.engines.learn import propose_rewrites
        p = TempProject(self.SRC)
        try:
            out = {s["candidate"]["from"]: s for s in propose_rewrites(p.ctx(), Path(p.dir), SEED)}
        finally:
            p.cleanup()
        for src in ("(x // x)", "(x >> x)"):
            self.assertIn(src, out, seed_note(self))
            self.assertFalse(out[src]["ready"], f"{src} -> {out[src]['candidate']['to']}: {out[src]['reason']}")
            self.assertIn("MISMATCH", out[src]["reason"])
            self.assertTrue(out[src]["candidate"]["valid_when"], "the rule's side condition travels with it")
        sound = out["((x * 2) + (x * 2))"]
        self.assertTrue(sound["ready"], sound["reason"])
        self.assertEqual(sound["candidate"]["valid_when"], [])

    def test_one_proposal_per_expression_up_to_names(self):
        from pathlib import Path
        from cardmodel.engines.learn import propose_rewrites, rewrite_identity
        a = {"a.py": "def f(x):\n    return (x * 2) + (x * 2)\n"}
        both = {**a, "b.py": "def g(y):\n    return (y * 2) + (y * 2)\n"}
        alone, together = TempProject(a), TempProject(both)
        try:
            one = propose_rewrites(alone.ctx(), Path(alone.dir), SEED)
            two = propose_rewrites(together.ctx(), Path(together.dir), SEED)
        finally:
            alone.cleanup()
            together.cleanup()
        self.assertTrue(one, seed_note(self))
        self.assertEqual([s["candidate"]["name"] for s in two], [s["candidate"]["name"] for s in one],
                         "the same expression under other names, in another file, is proposed once")
        for s in one:
            ident = s["candidate"]["identity"]
            self.assertEqual((ident["under"], s["candidate"]["name"]),
                             ("alpha", "sugg_" + ident["hash"].rsplit(":", 1)[-1][:12]))
            self.assertEqual(ident["hash"], rewrite_identity(["ADD", ["MUL", ["var", "q"], ["int", 2]],
                                                              ["MUL", ["var", "q"], ["int", 2]]])
                             if s["candidate"]["from"] == "((x * 2) + (x * 2))" else ident["hash"])

    def test_check_rewrite_counts_one_sided_errors(self):
        import random
        from cardmodel.engines.exprs import parse
        from cardmodel.engines.learn import check_rewrite
        rng = random.Random(SEED)
        checks, bad = check_rewrite(parse("x // x"), parse("1"), rng)
        self.assertEqual(bad["env"], {"x": 0})
        checks, bad = check_rewrite(parse("x * 2"), parse("x << 1"), rng)
        self.assertIsNone(bad)
        self.assertGreaterEqual(checks, MIN_EVIDENCE)
        # both sides raise on x = 0: not a check, not a counterexample
        checks, bad = check_rewrite(parse("1 // x"), parse("1 // x"), rng)
        self.assertIsNone(bad)
