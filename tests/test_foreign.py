"""Foreign programs on the card model: a program built for another CPU and OS (32-bit MIPS, Linux o32; the PSP's
CPU is the same ISA card's Allegrex core) runs on the instruction cards and the os card, in every engine, and
translated ahead of time into native blocks. The witness is the program itself: the same self-written source built
for this computer must print the same thing and exit the same way. No foreign firmware or game is used."""
import random
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import probes
from cardmodel.machine import bench
from cardmodel.machine import isa as I
from cardmodel.machine import process as P
from cardmodel.machine import symbolic as SY

HERE = Path(__file__).resolve().parent / "foreign"
_CTX = model_ctx()
_TC = _CTX.store.get("os/linux_mips_o32")["toolchain"]
HAVE_CROSS = probes.probe(_TC["probe"])[0]
HAVE_CC = probes.probe({"kind": "executable", "name": "cc"})[0]
_BUILT: dict = {}


def mips(name: str) -> Path:
    """A sample built for MIPS Linux by the os card's toolchain (once per run)."""
    key = ("mips", name)
    if key not in _BUILT:
        out = Path(tempfile.mkdtemp(prefix="cardmodel_foreign_")) / f"{name}.mips"
        cmd = []
        for part in _TC["c"]:
            if part == "{exe}":
                cmd.append("clang")
            elif part == "{out}":
                cmd.append(str(out))
            elif part == "{srcs}":
                cmd += [str(HERE / "start.c"), str(HERE / f"{name}.c")]
            else:
                cmd.append(part)
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        _BUILT[key] = out
    return _BUILT[key]


def host(name: str) -> Path:
    key = ("host", name)
    if key not in _BUILT:
        out = Path(tempfile.mkdtemp(prefix="cardmodel_foreign_")) / name
        subprocess.run(["cc", "-O2", "-fno-builtin", "-o", str(out), str(HERE / "start.c"), str(HERE / f"{name}.c")],
                       check=True, capture_output=True, timeout=300)
        _BUILT[key] = out
    return _BUILT[key]


class MipsCards(unittest.TestCase):
    def test_cards_conform_in_every_engine(self):
        r = bench.conformance(_CTX, "mips32", samples=3, seed=SEED)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertGreaterEqual(len(r["engines"]), 2)
        self.assertEqual(I.in_sync(_CTX, "mips32")["status"], "pass")

    def test_terms_agree_with_the_semantics(self):
        r = SY.check(_CTX, "mips32", seed=SEED, samples=3)
        bad = {k: v for k, v in r["cards"].items() if v["status"] == "fail"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertGreater(r["counts"].get("pass", 0), 100)

    def test_dispatch_index_comes_from_the_card(self):
        src = I.dispatch_source(_CTX.store, "mips32")
        self.assertIn("mips_exec_dec: Int[4096]", src)
        self.assertIn("((op >> 26) & 0x3f) << 6", src)

    def test_a_wrong_vector_is_caught(self):
        card = dict(_CTX.store.get("isa/MIPS_ADDU"))
        card["vectors"] = [{"name": "planted", "op": 0x00851021, "in": {"r4": 1, "r5": 2}, "out": {"r2": 4}}]
        from cardmodel.machine import build as Bd
        from cardmodel.machine import native as N
        m = N.load(_CTX, Bd.module(_CTX, "mips32_bench"), "ir")
        self.assertTrue(bench.check_mips_vectors(m, card))

    def test_the_other_core_reserves_its_encodings(self):
        from cardmodel.machine import build as Bd
        from cardmodel.machine import native as N
        m = N.load(_CTX, Bd.module(_CTX, "mips32_bench"), "ir")
        rng = random.Random(SEED)
        for name, variant in (("ALLEGREX_MAX", 0), ("MIPS_MUL", 1)):
            card = _CTX.store.get(f"isa/{name}")
            st = bench._mips_state(rng, card, _CTX.store.get("isa/mips32")["variants"])
            st["variant"] = variant
            out = bench.run_mips_case(m, st, card["match"] | (5 << 21) | (6 << 16) | (7 << 11), bytes(0x10000))
            self.assertEqual(out["undef_calls"], 1, name)
            self.assertEqual(out["regs"], st["regs"], name)


@unittest.skipUnless(HAVE_CROSS, "no clang with the MIPS target and ld.lld on this machine")
class ForeignPrograms(unittest.TestCase):
    def test_same_output_as_the_program_built_for_this_computer(self):
        if not HAVE_CC:
            self.skipTest("no C compiler for this computer")
        want = subprocess.run([str(host("algos")), "x"], input=b"hello\n", capture_output=True, timeout=60)
        for lifted in (False, True):
            r = P.run(_CTX, mips("algos"), argv=["algos", "x"], stdin=b"hello\n", lifted=lifted)
            self.assertEqual(r["state"], "exited", r)
            self.assertEqual(r["stdout"].encode(), want.stdout, lifted)
            self.assertEqual(r["exit_code"], want.returncode)
            self.assertEqual(r["unknown_syscalls"], 0)

    def test_lifted_code_runs_exactly_as_the_interpreter(self):
        a = P.Process(_CTX, mips("work"), argv=["work", "2"])
        b = P.Process(_CTX, mips("work"), argv=["work", "2"], lifted=True)
        ra, rb = a.run(), b.run()
        self.assertEqual((ra["stdout"], ra["steps"], ra["exit_code"]), (rb["stdout"], rb["steps"], rb["exit_code"]))
        self.assertEqual(list(a.m.array("regs")[:32]), list(b.m.array("regs")[:32]))
        self.assertEqual(rb["lifted"]["interpreted"], 0)
        self.assertGreater(rb["lifted"]["blocks"], 10)

    def test_engines_agree(self):
        """The reference interpreter, Python and C run the same instructions to the same state."""
        outs = []
        for engine in ("ir", "host", "native"):
            p = P.Process(_CTX, mips("unknown"), engine=engine)
            r = p.run(max_steps=100_000)
            outs.append((r["state"], r["stdout"], r["steps"], list(p.m.array("regs")[:32]), r["unknown_syscalls"]))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])

    def test_unmodelled_system_call_is_visible(self):
        r = P.run(_CTX, mips("unknown"))
        self.assertEqual(r["stdout"], "result -89\n")
        self.assertEqual((r["unknown_syscalls"], r["last_unknown_syscall"]), (1, 4999))

    def test_a_bad_address_stops_the_process(self):
        for lifted in (False, True):
            r = P.run(_CTX, mips("fault"), lifted=lifted)
            self.assertEqual(r["state"], "faulted")
            self.assertEqual(r["stdout"], "before\n")
            self.assertEqual((r["fault"]["code"], r["fault"]["addr"]), (5, 0x7FFFFFF0))

    def test_mips32r2_code_is_not_allegrex_code(self):
        """MUL is SPECIAL2, which the PSP's core does not have: the program stops with a reserved instruction."""
        r = P.run(_CTX, mips("work"), argv=["work", "1"], variant="allegrex")
        self.assertEqual((r["state"], r["fault"]["code"]), ("faulted", 10))

    def test_refusals_say_why(self):
        with self.assertRaisesRegex(P.LoadError, "not an ELF"):
            P.Process(_CTX, b"\x00" * 64)
        if HAVE_CC:
            with self.assertRaisesRegex(P.LoadError, "64-bit"):
                P.Process(_CTX, host("unknown"))


if __name__ == "__main__":
    unittest.main()
