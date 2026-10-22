"""The four sources (CM44): every artifact traces back to truth, transformation, action or method."""
import unittest

from helpers import SEED, model_ctx

from cardmodel.engines import sources as SO


class Sources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_every_artifact_traces_back(self):
        r = SO.check(self.ctx)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["coverage"], 1.0)
        self.assertEqual(r["actions_without_truth"], 0)
        built = SO.build(self.ctx, seed=SEED)
        subjects = {d["subject"] for d in built["definitions"]}
        for reg in ("algorithm", "function"):
            for c in self.ctx.store.cards(reg):
                self.assertIn(c.qualified, subjects)
        tri = next(d for d in built["definitions"] if d["subject"] == "algorithm/triangular")
        self.assertEqual(tri["godel"]["content"], {"op/ADD": 1})
        links = {a["code"]: a["link"] for a in built["actions"] if a["truth"] == f"definition/{tri['name']}"}
        self.assertEqual(links["algorithm/triangular#loop"]["kind"], "source")
        # the closed form is proved by a witness its class sizes (CM46); the recursive form is only sampled
        self.assertEqual((links["algorithm/triangular#closed_form"]["status"],
                          links["algorithm/triangular#closed_form"]["tier"]), ("proved", "proof"))
        self.assertEqual((links["algorithm/triangular#recursive"]["status"],
                          links["algorithm/triangular#recursive"]["tier"]), ("witnessed", "sample"))
        self.assertIn("vector", tri["godel"])
        self.assertNotIn("number", tri["godel"])
        self.assertTrue(tri["identity"]["hash"].startswith("sha256:"))
        self.assertIn(tri["canonical"]["status"], ("canonical", "recurrence"))
        # an action that names no definition, or whose witness refutes it, breaks the law
        from cardmodel.kernel.store import Store
        import shutil
        import tempfile
        from pathlib import Path
        from cardmodel.engines.context import Ctx
        from cardmodel.kernel import paths
        d = Path(tempfile.mkdtemp(prefix="cardmodel_sources_"))
        try:
            st = Store([("model", paths.model_cards()), ("scratch", d)], readonly={"model"})
            st.save({"name": "stray", "category": "action", "truth": "definition/nothing", "lang": "c", "code": "x",
                     "method": "method/emit", "link": {"kind": "witness", "status": "refuted", "at": [1]}},
                    layer="scratch")
            problems = "\n".join(SO.check(Ctx(st))["problems"])
            self.assertIn("action/stray: its truth definition/nothing is not a definition", problems)
            self.assertIn("action/stray: its witness refutes it", problems)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
