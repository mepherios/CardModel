"""The formal core (formal/GodelCore): it builds in Lean with no sorry, and every theorem card names real theorems."""
import unittest

from helpers import model_ctx

from cardmodel.engines import formal as F


class FormalCore(unittest.TestCase):
    def test_comments_do_not_count(self):
        src = "/- a sorry in a comment -/\ntheorem t : True := trivial -- sorry\n/- nested /- sorry -/ -/\n"
        self.assertNotIn("sorry", F.strip_comments(src))
        self.assertIn("theorem t", F.strip_comments(src))

    @unittest.skipIf(F.toolchain() is None, "no Lean toolchain for formal/lean-toolchain")
    def test_the_core_builds_without_sorry(self):
        self.assertEqual(F.scan(), [])
        r = F.check(model_ctx())
        self.assertEqual(r["status"], "pass", r.get("problems"))
        self.assertEqual(r["proved"], r["theorems"])
        self.assertGreaterEqual(r["theorems"], 6)


if __name__ == "__main__":
    unittest.main()
