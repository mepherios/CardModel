"""Capability probes (CM12): data-driven, cached, and honest about what is missing."""
import os
import tempfile
import unittest

from helpers import model_ctx

from cardmodel.engines import probes, rewrite


class Probes(unittest.TestCase):
    def setUp(self):
        probes.clear_cache()

    def test_unavailable_is_reported(self):
        ok, why = probes.probe({"kind": "executable", "name": "definitely-not-a-tool-cm"})
        self.assertFalse(ok)
        self.assertIn("not found", why)
        ok, why = probes.probe({"kind": "python_module", "module": "no_such_module_cm"})
        self.assertEqual((ok, why), (False, "python module no_such_module_cm not installed"))
        st = model_ctx().store
        rows = {r["form"]: r for r in rewrite.enumerate_forms(st, st.get("crypto_atom/aes256gcm_seal"))}
        self.assertIn("reason", rows["ting_noble"])
        self.assertFalse(rows["ting_noble"]["available"])

    def test_glob_env_all_any(self):
        with tempfile.TemporaryDirectory() as d:
            for v in ("1.0", "2.0"):
                p = os.path.join(d, f"tool-{v}", "bin")
                os.makedirs(p)
                exe = os.path.join(p, "tool")
                with open(exe, "w") as f:
                    f.write("#!/bin/sh\necho tool " + v + "\n")
                os.chmod(exe, 0o755)
            ok, path = probes.probe({"kind": "executable", "name": "tool", "glob": [d + "/tool-*/bin/tool"],
                                     "glob_only": True, "version_args": [], "min_version": "1.5"})
            self.assertTrue(ok, path)
            self.assertIn("tool-2.0", path)
            os.environ["CM_TEST_DIR"] = d
            try:
                self.assertTrue(probes.probe({"kind": "env", "var": "CM_TEST_DIR", "is_dir": True})[0])
            finally:
                del os.environ["CM_TEST_DIR"]
        self.assertFalse(probes.probe({"kind": "all", "of": [{"kind": "always"}, {"kind": "never"}]})[0])
        self.assertTrue(probes.probe({"kind": "any", "of": [{"kind": "never"}, {"kind": "always"}]})[0])


if __name__ == "__main__":
    unittest.main()
