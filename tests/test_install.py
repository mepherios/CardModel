"""`cardmodel install`: a symlink on PATH that runs this checkout, idempotent, never replaces a foreign file."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CLI, ROOT


def cli(*args, env=None):
    return subprocess.run(CLI + list(args), cwd=ROOT, capture_output=True, text=True, env=env)


class Install(unittest.TestCase):
    def test_install_run_uninstall(self):
        with tempfile.TemporaryDirectory() as d:
            r = cli("install", "--dir", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            link = Path(d) / "cardmodel"
            self.assertEqual(link.resolve(), (ROOT / "bin" / "cardmodel").resolve())
            self.assertEqual(cli("install", "--dir", d).returncode, 0)           # idempotent
            env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"])
            r = subprocess.run(["cardmodel", "--help"], capture_output=True, text=True, env=env, cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("translate", r.stdout)
            self.assertEqual(cli("install", "--dir", d, "--uninstall").returncode, 0)
            self.assertFalse(link.exists() or link.is_symlink())

    def test_refuses_foreign_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cardmodel").write_text("not ours")
            self.assertEqual(cli("install", "--dir", d).returncode, 1)
            self.assertEqual((Path(d) / "cardmodel").read_text(), "not ours")
            self.assertEqual(cli("install", "--dir", d, "--uninstall").returncode, 1)


if __name__ == "__main__":
    unittest.main()
