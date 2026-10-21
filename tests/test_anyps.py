"""AnyPS5 as cards (CM32): the badge's rule reproduced, every gap given a cause, unknowns left to observation,
and AnyPS5's own code witnessed against derived semantics. A synthetic checkout stands in for AnyPS5, so the
suite needs no folder outside the repository; CARDMODEL_ANYPS5=<checkout> adds the check on a real one."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, SEED, model_ctx, seed_note

from cardmodel.anyps5 import cards as C
from cardmodel.anyps5 import classify as K
from cardmodel.anyps5 import cover as V
from cardmodel.anyps5 import scan as S
from cardmodel.anyps5 import witness as W
from cardmodel.engines import probes
from cardmodel.engines.context import Ctx
from cardmodel.kernel.store import open_store

GENERAL = """#pragma once
#include <cstdint>
#define APS5_VABI
#define APS5_EXPORT(nid, fn)
extern "C" [[noreturn]] void NotImplemented_nid_no_patch(const char* funcName);
"""
RTC = r'''#include "prx/libc/include/General.hpp"
#include <stdexcept>
namespace {
int Helper(int x) { return x + 1; }
void Unsupported() { NotImplemented_nid_no_patch(__func__); }
}
int FarHelper(int a);
extern "C" {
int APS5_VABI sceRtcAdd(int a, int b) { return Helper(a) + b - 1; }
int APS5_VABI sceRtcStub() {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
int APS5_VABI sceRtcWrapped(int a) {
    if (a > 3) Unsupported();
    return a;
}
int APS5_VABI sceRtcInit() { return 0; }
int APS5_VABI sceRtcPick(int mode) {
    if (mode != 0) throw std::runtime_error("sceRtcPick: unsupported mode");
    return 7;
}
int APS5_VABI sceRtcCallsStub() { return sceRtcStub(); }
int APS5_VABI sceRtcUsesFar(int a) { return FarHelper(a); }
APS5_EXPORT("AbCdEfGhIjK", sceRtcUnknown_AbCdEfGhIjK);
int APS5_VABI sceRtcUnknown_AbCdEfGhIjK() { NotImplemented_nid_no_patch(__func__); return 0; }
int APS5_VABI sceRtcPartial(int a) {
    if (a < 0) NotImplemented_nid_no_patch("sceRtcPartial (negative input)");
    return a * 2;
}
// int APS5_VABI sceRtcCommentedOut() { NotImplemented_nid_no_patch(__func__); }
}
'''
FAR = '#include "prx/libc/include/General.hpp"\nint FarHelper(int a) {\n    NotImplemented_nid_no_patch(__func__);\n    return a;\n}\n'
AGC = r'''#include "prx/libc/include/General.hpp"
struct CommandBuffer;
namespace Agc::Command { std::uint32_t* Emit(CommandBuffer* b, std::uint32_t op, std::initializer_list<std::uint32_t> p, const char* f); }
extern "C" {
std::uint32_t* APS5_VABI sceAgcDcbFoo(CommandBuffer* buf, std::uint32_t v) { return Agc::Command::Emit(buf, 0x10u, {v, v}, __func__); }
std::uint32_t APS5_VABI sceAgcDcbFooGetSize() { return 12; }
std::uint32_t* APS5_VABI sceAgcDcbBaz(CommandBuffer* buf) { return Agc::Command::Emit(buf, 0x11u, {1u}, __func__); }
std::uint32_t APS5_VABI sceAgcDcbBazGetSize() {
    NotImplemented_nid_no_patch(__func__);
    return 0;
}
}
'''
NP = '#include "prx/libc/include/General.hpp"\nextern "C" {\nint APS5_VABI sceNpTusConnect() {\n    NotImplemented_nid_no_patch(__func__);\n    return 0;\n}\n}\n'
NET = r'''#include "prx/libc/include/General.hpp"
namespace {
std::uint32_t swap32(std::uint32_t v) {
    return (v << 24) | ((v & 0xFF00u) << 8) | ((v >> 8) & 0xFF00u) | (v >> 24);
}
}
extern "C" {
uint32_t APS5_VABI sceNetHtonl_nid_postfix(uint32_t host32) { return swap32(host32); }
}
'''
DEBT = """# libSceRtc technical debt

### Unknown function info

- [sceRtcAdd](../../../core/libs/prx/libSceRtc/Export.cpp) (libSceRtc) - the result is not measured on a PS5
- [sceRtcPick](../../../core/libs/prx/libSceRtc/Export.cpp) (libSceRtc) - slow: a copy per frame
  continued on the next line

### Functional

- [libSceRtc](../../../core/libs/prx/libSceRtc/Export.cpp) as a whole: nothing specific
"""
FIXTURE = {"core/libs/SceTypes.hpp": "#pragma once\n#include <cstdint>\n",
           "core/libs/prx/libc/include/General.hpp": GENERAL,
           "core/libs/prx/libSceRtc/Export.cpp": RTC, "core/libs/prx/libSceRtc/src/Far.cpp": FAR,
           "core/libs/prx/libSceRtc/tests/Ignored.cpp": "int APS5_VABI sceRtcTestOnly() { return 1; }\n",
           "core/libs/prx/libSceAgc/Export.cpp": AGC, "core/libs/prx/libSceNpTus/Export.cpp": NP,
           "core/libs/prx/libSceNet/Export.cpp": NET,
           "core/libs/prx/libSceAbstractLocal/Export.cpp": '#include "prx/libc/include/General.hpp"\n',
           "docs/dev/debt/libSceRtc.md": DEBT, "core/libs/tests/Rtc.cpp": "int main() { return sceRtcAdd(1, 2); }\n"}
KNOWLEDGE = ["anyps5_cause", "anyps5_domain", "anyps5_standard", "op", "language", "domain", "card_type"]


def fixture_tree() -> Path:
    root = Path(tempfile.mkdtemp(prefix="anyps5_fixture_"))
    for rel, text in FIXTURE.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def fixture_store(root: Path) -> tuple[Ctx, Path]:
    """The model's knowledge cards and nothing of the real AnyPS5 scan: the fixture's cards are its only exports."""
    cards = Path(tempfile.mkdtemp(prefix="anyps5_cards_"))
    for reg in KNOWLEDGE:
        shutil.copytree(ROOT / "cards" / reg, cards / reg)
    return Ctx(open_store(project=False, home_cards=cards)), cards


class Scanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = fixture_tree()
        cls.scan = S.Scan(cls.root)
        cls.libs = {lib.name: lib for lib in cls.scan.libraries}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_badge_rule(self):
        rtc = self.libs["libSceRtc"]
        self.assertEqual(rtc.todo, {"sceRtcStub", "sceRtcWrapped", "sceRtcUnknown_AbCdEfGhIjK", "sceRtcPartial"})
        self.assertIn("sceRtcAdd", rtc.done)
        self.assertNotIn("sceRtcTestOnly", rtc.done | rtc.todo)          # tests/ never counts
        self.assertNotIn("sceRtcCommentedOut", rtc.done | rtc.todo)      # comments are blank
        self.assertEqual(rtc.inert, {"sceRtcInit"})
        self.assertEqual(self.scan.badge(), {"done": 9, "total": 15, "percent": 60.0})
        self.assertTrue(self.libs["libSceAbstractLocal"].done == self.libs["libSceAbstractLocal"].todo == set())

    def test_parity_detects_a_difference(self):
        groups = [{"name": lib.name, "done_names": sorted(lib.done), "todo_names": sorted(lib.todo),
                   "inert_names": sorted(lib.inert)} for lib in self.scan.libraries]
        b = self.scan.badge()
        progress = {"libraries": {"done": b["done"], "total": b["total"], "groups": groups}, "shaders": {}}
        self.assertTrue(S.parity(self.scan, progress)["agree"] or not self.scan.shader.get("available"))
        self.assertEqual(S.parity(self.scan, progress)["mismatches"], [])
        rtc = next(g for g in groups if g["name"] == "libSceRtc")
        rtc["done_names"] = rtc["done_names"][1:]
        self.assertNotEqual(S.parity(self.scan, progress)["mismatches"], [])

    def test_cards_point_at_their_lines(self):
        built = C.build(self.scan)
        for c in built["anyps5_export"]:
            p = c["provenance"]
            line = (self.root / p["file"]).read_text(encoding="utf-8").splitlines()[p["line"] - 1]
            want = c["nid"] if c["kind"] == "nid_alias" else C.definition_of(c)
            self.assertIn(want, line, c["name"])
        for d in built["anyps5_debt"]:
            line = (self.root / d["provenance"]["file"]).read_text(encoding="utf-8").splitlines()[d["provenance"]["line"] - 1]
            self.assertTrue(line.startswith("- "), d["name"])
        names = {c["name"]: c for c in built["anyps5_export"]}
        self.assertEqual(names["libSceRtc.sceRtcUsesFar"]["helper_stub"], ["FarHelper"])
        self.assertEqual(names["libSceRtc.sceRtcCallsStub"]["uses"], ["libSceRtc.sceRtcStub"])
        self.assertTrue(names["libSceRtc.sceRtcPartial"]["partial_pending"])
        self.assertEqual(names["libSceAgc.sceAgcDcbFoo"]["packet"], {"opcode": 0x10, "payload": 2})
        self.assertEqual(names["libSceRtc.sceRtcAdd"]["tests"], ["core/libs/tests/Rtc.cpp"])
        pick = next(d for d in built["anyps5_debt"] if "slow" in d["text"])
        self.assertIn("continued on the next line", pick["text"])


class Classifying(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = fixture_tree()
        cls.ctx, cls.cards = fixture_store(cls.root)
        C.save(cls.ctx.store, C.build(S.Scan(cls.root)), layer="model")
        cls.cls = K.classify(cls.ctx, run_programs=False)
        cls.cause = {(e, k): c for e, k, c in cls.cls.rel("cause")}

    @classmethod
    def tearDownClass(cls):
        for d in (cls.root, cls.cards):
            shutil.rmtree(d, ignore_errors=True)

    def test_every_gap_has_a_cause(self):
        self.assertEqual(self.cls.model.violations, [])
        gaps = self.cls.rel("gap")
        self.assertTrue(gaps)
        self.assertEqual({(e, k) for e, k in gaps}, set(self.cause))

    def test_causes(self):
        c = self.cause
        self.assertEqual(c[("libSceRtc.sceRtcUnknown_AbCdEfGhIjK", "pending")], "observation_unknown_name")
        self.assertEqual(c[("libSceNpTus.sceNpTusConnect", "pending")], "boundary_psn")
        self.assertEqual(c[("libSceAgc.sceAgcDcbBazGetSize", "pending")], "derivable_packet")
        self.assertEqual(c[("libSceRtc.sceRtcUsesFar", "reaches_stub")], "derivable_blocked")
        self.assertEqual(c[("libSceRtc.sceRtcCallsStub", "reaches_stub")], "derivable_blocked")
        self.assertEqual(c[("libSceRtc.sceRtcInit", "inert")], "observation_silent")
        self.assertIn(("libSceRtc.sceRtcPick", "partial"), c)
        self.assertEqual(c[("libSceRtc.sceRtcAdd", "debt")], "observation_unmeasured")
        self.assertEqual(c[("libSceRtc.sceRtcPick", "debt")], "performance")
        self.assertIn(("libSceAbstractLocal", "observation_unknown_exports"), self.cls.rel("module_cause"))
        self.assertIn(("libSceAgc.sceAgcDcbFooGetSize",), self.cls.rel("size_law_holds"))
        self.assertIn(("libSceRtc.sceRtcStub", 1), self.cls.rel("blocks"))

    def test_unknown_gaps_are_observation_obligations(self):
        causes = {c.name: c["class"] for c in self.ctx.store.cards("anyps5_cause")}
        for (e, k), c in self.cause.items():
            if self.cls.exports[e].get("unknown_name"):
                self.assertEqual(causes[c], "observation", (e, k, c))
        # a gap the rules cannot place is caught, not dropped: take away the cause it would get
        prog, _ = K.facts(self.ctx, run_programs=False)
        prog.facts = [f for f in prog.facts if not (f[0] == "priority" and f[1][0] == "observation_proprietary")]
        from cardmodel.engines import logic as L
        model = L.evaluate(prog, self.ctx.ops)
        self.assertTrue(any("caused" in str(v.get("rule")) for v in model.violations))
        # and the real classification (the model's cards) gives every unknown name an observation cause
        real = K.classify(model_ctx(), run_programs=False)
        real_causes = {c.name: c["class"] for c in model_ctx().store.cards("anyps5_cause")}
        for e, k, c in real.rel("cause"):
            if real.exports[e].get("unknown_name"):
                self.assertEqual(real_causes[c], "observation", (e, k, c))
        self.assertEqual(real.model.violations, [])

    def test_the_ladder_ends_at_complete(self):
        rep = V.report(self.ctx, self.cls)
        self.assertEqual(rep["unclassified"], 0)
        self.assertEqual(rep["ladder"][1]["count"], 9)
        self.assertEqual(rep["complete"], len(self.cls.rel("complete")))
        self.assertIn({"export": "libSceRtc.sceRtcStub", "blocks": 1}, rep["blocks"])
        self.assertIn("## The real coverage", V.markdown(rep))


class Resolving(unittest.TestCase):
    def test_a_host_call_is_not_the_guest_export(self):
        """AnyPS5's own code calls the host's readlink; only the C++ name reaches the export readlink_nid_postfix."""
        root = fixture_tree()
        try:
            extra = {"core/libs/prx/libc/src/Unistd.cpp":
                     '#include "prx/libc/include/General.hpp"\nextern "C" {\nint APS5_VABI readlink_nid_postfix(const char* p) {\n'
                     '    NotImplemented_nid_no_patch(__func__);\n    return -1;\n}\n'
                     'int APS5_VABI readlinkat_nid_postfix(const char* p) { return readlink_nid_postfix(p); }\n}\n',
                     "core/libs/prx/libSceSysmodule/Export.cpp":
                     '#include "prx/libc/include/General.hpp"\n#include <unistd.h>\nextern "C" {\n'
                     'int APS5_VABI sceSysmoduleHostPath(char* b) { return static_cast<int>(::readlink("/proc/self/exe", b, 64)); }\n}\n',
                     "core/libs/tests/Host.cpp": 'int main() { char b[64]; return readlink("/proc/self/exe", b, 64) < 0; }\n'}
            for rel, text in extra.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            names = {c["name"]: c for c in C.build(S.Scan(root))["anyps5_export"]}
            self.assertNotIn("libc.readlink_nid_postfix", names["libSceSysmodule.sceSysmoduleHostPath"].get("uses") or [])
            self.assertIn("libc.readlink_nid_postfix", names["libc.readlinkat_nid_postfix"].get("uses") or [])
            self.assertFalse(names["libc.readlink_nid_postfix"].get("tests"))     # the test calls the host's readlink
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Layering(unittest.TestCase):
    def test_a_project_scan_replaces_the_model_scan(self):
        """A project scanning its own fixed checkout: its scan replaces the model's (an export it removed does not
        linger from the lower layer), and the comparison shows both."""
        upstream, fixed = fixture_tree(), fixture_tree()
        ctx, cards = fixture_store(upstream)
        project = Path(tempfile.mkdtemp(prefix="anyps5_project_"))
        try:
            rtc = fixed / "core/libs/prx/libSceRtc/Export.cpp"
            rtc.write_text(RTC.replace("int APS5_VABI sceRtcStub() {\n    NotImplemented_nid_no_patch(__func__);\n",
                                       "int APS5_VABI sceRtcStub() {\n")
                           .replace("int APS5_VABI sceRtcInit() { return 0; }\n", ""), encoding="utf-8")
            C.save(ctx.store, C.build(S.Scan(upstream)), layer="model")
            pctx = Ctx(open_store(project=project, home_cards=cards))
            C.save(pctx.store, C.build(S.Scan(fixed)), layer="project")
            exports = C.scan_cards(pctx.store, "anyps5_export")
            self.assertEqual({c.layer for c in exports}, {"project"})
            self.assertNotIn("libSceRtc.sceRtcInit", {c.name for c in exports})
            self.assertIn("libSceRtc.sceRtcInit", {c.name for c in C.scan_cards(ctx.store, "anyps5_export")})
            base_cls, cls = K.classify(ctx, run_programs=False), K.classify(pctx, run_programs=False)
            self.assertIn(("libSceRtc.sceRtcCallsStub", "reaches_stub"), {(e, k) for e, k, _ in base_cls.rel("cause")})
            self.assertNotIn(("libSceRtc.sceRtcCallsStub", "reaches_stub"), {(e, k) for e, k, _ in cls.rel("cause")})
            base, rep = V.report(ctx, base_cls), V.report(pctx, cls)
            self.assertEqual([base["declared"], rep["declared"]], [15, 14])
            self.assertGreater(rep["complete"], base["complete"])
            md = V.comparison(base, rep, "upstream", "fixed")
            self.assertIn("| declared exports | 15 | 14 | -1 |", md)
            self.assertIn(f"| complete by AnyPS5's own records | {base['complete']} | {rep['complete']} | "
                          f"{rep['complete'] - base['complete']:+d} |", md)
        finally:
            for d in (upstream, fixed, cards, project):
                shutil.rmtree(d, ignore_errors=True)


@unittest.skipIf(not probes.probe({"kind": "executable", "name": "c++", "env_override": "CXX"})[0],
                 "no C++ compiler on this host")
class Witnessing(unittest.TestCase):
    def test_a_build_is_cached_by_everything_that_makes_it(self):
        ctx = model_ctx()
        base = W.build_dir(ctx, "int main() {}", "h", "c++", ["-O1", "-Iupstream/core/libs"])
        self.assertEqual(base, W.build_dir(ctx, "int main() {}", "h", "c++", ["-O1", "-Iupstream/core/libs"]))
        for other in (W.build_dir(ctx, "int main() {}", "h", "c++", ["-O1", "-Iupstream/core/libs", "-arch", "x86_64"]),
                      W.build_dir(ctx, "int main() {}", "h", "c++", ["-O1", "-Icopy/core/libs"]),
                      W.build_dir(ctx, "int main() {}", "h", "clang++", ["-O1", "-Iupstream/core/libs"]),
                      W.build_dir(ctx, "int main() {}", "h2", "c++", ["-O1", "-Iupstream/core/libs"])):
            self.assertNotEqual(base, other)

    def test_agreement_and_a_planted_bug(self):
        root = fixture_tree()
        try:
            ctx = model_ctx()
            sem = dict(ctx.store.get("anyps5_semantics/net_byte_order"))
            sem["harness"] = {"language": "cpp", "include": ["core/libs/prx/libSceNet/Export.cpp"],
                              "link": sem["harness"]["link"]}
            sem["checks"] = [c for c in sem["checks"] if c["export"].endswith("Htonl_nid_postfix")]
            from cardmodel.kernel.card import Card
            card = Card(sem, registry="anyps5_semantics")
            good = W.run_semantics(ctx, card, root, seed=SEED, samples=60)
            self.assertEqual(good["status"], "agree", seed_note(self))
            self.assertGreaterEqual(good["checks"][0]["inputs"], 60)
            net = root / "core/libs/prx/libSceNet/Export.cpp"
            net.write_text(NET.replace("(v >> 24)", "(v >> 23)"), encoding="utf-8")
            bad = W.run_semantics(ctx, card, root, seed=SEED, samples=60)
            self.assertEqual(bad["status"], "disagree", seed_note(self))
            self.assertTrue(bad["checks"][0]["examples"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


    def test_floats_cross_the_harness_exactly(self):
        root = fixture_tree()
        try:
            ctx = model_ctx()
            math = root / "core/libs/prx/libc/src/Math.cpp"
            math.parent.mkdir(parents=True, exist_ok=True)
            math.write_text('#include <cmath>\n#include "prx/libc/include/General.hpp"\nextern "C" {\n'
                            'double APS5_VABI floor_nid_postfix(double x) { return std::floor(x); }\n'
                            'double APS5_VABI ldexp_nid_postfix(double x, int e) { return std::ldexp(x, e); }\n}\n',
                            encoding="utf-8")
            sem = dict(ctx.store.get("anyps5_semantics/libm_exact"))
            sem["harness"] = {"language": "cpp", "include": ["core/libs/prx/libc/src/Math.cpp"],
                              "link": sem["harness"]["link"]}
            sem["checks"] = [c for c in sem["checks"] if c["export"] in ("libc.floor_nid_postfix", "libc.ldexp_nid_postfix")]
            from cardmodel.kernel.card import Card
            good = W.run_semantics(ctx, Card(sem, registry="anyps5_semantics"), root, seed=SEED, samples=80)
            self.assertEqual(good["status"], "agree", seed_note(self))
            math.write_text(math.read_text(encoding="utf-8").replace("std::floor(x)", "std::ceil(x)"), encoding="utf-8")
            bad = W.run_semantics(ctx, Card(sem, registry="anyps5_semantics"), root, seed=SEED, samples=80)
            self.assertEqual(bad["status"], "disagree", seed_note(self))
            floor = next(c for c in bad["checks"] if c["export"] == "libc.floor_nid_postfix")
            self.assertGreater(floor["disagree"], 0)
            self.assertIsInstance(floor["examples"][0]["anyps5"], float)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class ModelCards(unittest.TestCase):
    """The scan of AnyPS5 the repository carries, read from the cards alone."""

    def test_snapshot_reproduces_the_badge(self):
        snap = model_ctx().store.get("anyps5_snapshot/current")
        self.assertIsNotNone(snap)
        self.assertEqual(snap["parity"]["mismatch_count"], 0)
        exports = [c for c in model_ctx().store.cards("anyps5_export") if c.get("kind") == "function"]
        done = sum(1 for c in exports if c["state"] == "implemented")
        self.assertEqual([done, len(exports)], [snap["badge"]["done"], snap["badge"]["total"]])

    def test_witness_cards_agree_and_are_current(self):
        ctx = model_ctx()
        snap = ctx.store.get("anyps5_snapshot/current")
        witnesses = ctx.store.cards("anyps5_witness")
        self.assertGreaterEqual(len(witnesses), 8)
        for w in witnesses:
            self.assertEqual(w["status"], "agree", w.name)
            self.assertEqual(w["snapshot"], snap["sha256"], w.name)
            self.assertTrue(all(c["ok"] for c in w["checks"]), w.name)


@unittest.skipUnless(os.environ.get("CARDMODEL_ANYPS5"), "set CARDMODEL_ANYPS5=<checkout> to scan a real AnyPS5")
class RealCheckout(unittest.TestCase):
    def test_scan_matches_the_recorded_snapshot(self):
        sc = S.Scan(os.environ["CARDMODEL_ANYPS5"])
        snap = model_ctx().store.get("anyps5_snapshot/current")
        self.assertEqual(sc.badge(), snap["badge"])
        if sc.sha256 != snap["sha256"]:
            self.skipTest("the checkout changed since the recorded scan: rescan with `cardmodel anyps5 scan PATH --save`")


if __name__ == "__main__":
    unittest.main()
