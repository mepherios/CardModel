"""emit on a multi-function file: one module header per file, so the result compiles."""
import shutil
import subprocess
import unittest

from helpers import TempProject

SRC = '''def add(a: int, b: int) -> int:
    return a + b


def twice(a: int) -> int:
    return add(a, a)


def sq(x: int) -> int:
    return x * x
'''


class EmitFile(unittest.TestCase):
    def _emit(self, lang: str, out: str):
        proj = TempProject({"f.py": SRC})
        self.addCleanup(proj.cleanup)
        r = proj.cli("emit", "--lang", lang, "f.py", "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        return proj, (proj.dir / out).read_text(encoding="utf-8")

    def test_rust_one_inner_attribute_and_compiles(self):
        proj, text = self._emit("rust", "M.rs")
        self.assertEqual(text.count("#![allow"), 1, text)
        for name in ("fn add(", "fn twice(", "fn sq("):
            self.assertIn(name, text)
        if shutil.which("rustc") is None:
            self.skipTest("rustc not installed")
        r = subprocess.run(["rustc", "--crate-type", "lib", "M.rs", "-o", "libm.rlib"], cwd=proj.dir,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_go_one_package_clause_and_vets(self):
        proj, text = self._emit("go", "m.go")
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("package ")), 1, text)
        if shutil.which("go") is None:
            self.skipTest("go not installed")
        pkg = proj.dir / "gopkg"
        pkg.mkdir()
        (pkg / "m.go").write_text(text, encoding="utf-8")
        (pkg / "go.mod").write_text("module example.com/m\n\ngo 1.18\n", encoding="utf-8")
        env = {"GOFLAGS": "-mod=mod", "GOCACHE": str(proj.dir / "gocache"), "GOPATH": str(proj.dir / "gopath")}
        r = subprocess.run(["go", "vet", "./..."], cwd=pkg, capture_output=True, text=True, timeout=300,
                           env={**__import__("os").environ, **env})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_java_one_class_wrapper(self):
        _, text = self._emit("java", "CardModule.java")
        self.assertEqual(text.count("class CardModule"), 1, text)


if __name__ == "__main__":
    unittest.main()
