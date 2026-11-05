"""The four sources (CM44): every artifact traces back to truth, transformation, action or method."""
import json
import os
import subprocess
import sys
import unittest

from helpers import ROOT, SEED, model_ctx, seed_note

from cardmodel.engines import sources as SO


# builds the packs in a child and prints them; the child's hash seed is the only thing that differs between runs
_BUILD = ("import json, sys; from cardmodel.engines import sources as SO; from cardmodel.engines.context import Ctx; "
          "from cardmodel.kernel.store import open_store; "
          "print(json.dumps(SO.build(Ctx(open_store(project=False)), seed=int(sys.argv[1])), sort_keys=True))")


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
        # the closed form and the linear recursion are proved by witnesses their classes size (CM46); factorial's
        # recursion multiplies by n, a class with no finite witness here, so it is only sampled
        for f in ("closed_form", "recursive"):
            self.assertEqual((links[f"algorithm/triangular#{f}"]["status"], links[f"algorithm/triangular#{f}"]["tier"]),
                             ("proved", "proof"), f)
        fac = next(d for d in built["definitions"] if d["subject"] == "algorithm/factorial")
        flinks = {a["code"]: a["link"] for a in built["actions"] if a["truth"] == f"definition/{fac['name']}"}
        self.assertEqual((flinks["algorithm/factorial#recursive"]["status"], flinks["algorithm/factorial#recursive"]["tier"]),
                         ("witnessed", "sample"))
        self.assertIn("vector", tri["godel"])
        self.assertNotIn("number", tri["godel"])
        self.assertTrue(tri["identity"]["hash"].startswith("sha256:"))
        self.assertIn(tri["canonical"]["status"], ("canonical", "recurrence"))
        # FOUNDATIONS.md D11/A4: content is read from the canonical term when there is one, so it follows meaning
        from cardmodel.engines import godel as G
        from cardmodel.engines.equivalence import RELATIONS
        self.assertTrue(all(d["identity"]["under"] in RELATIONS for d in built["definitions"]))
        self.assertEqual({d["identity"]["under"] for d in built["definitions"] if d["canonical"].get("status") == "canonical"},
                         {"laws"})
        canonical = [d for d in built["definitions"] if d["godel"]["read_from"].startswith("its canonical term")]
        self.assertTrue(canonical)
        for d in canonical:
            self.assertEqual(d["canonical"]["status"], "canonical")
            self.assertEqual(d["godel"]["content"], dict(G.term_content(d["canonical"]["term"], self.ctx.ops)))
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

    def test_build_does_not_depend_on_the_hash_seed(self):
        """The generated packs are the same under any PYTHONHASHSEED. Saturation explores in set order, so rules
        tie in fire count in a different order from run to run; the certificate records every fired equality,
        sorted by name, not the first few by count. Hash seeds 0 and 5 gave different packs before."""
        procs = [subprocess.Popen([sys.executable, "-B", "-c", _BUILD, str(SEED)], cwd=str(ROOT),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONHASHSEED=h))
                 for h in ("0", "5")]
        outs = [p.communicate(timeout=120) for p in procs]
        for p, (_, err) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, err[-2000:])
        a, b = (json.loads(o) for o, _ in outs)
        for kind in ("definitions", "actions", "transformations"):
            self.assertEqual(a[kind], b[kind], f"{kind} differ between hash seeds 0 and 5 {seed_note(self)}")


if __name__ == "__main__":
    unittest.main()
