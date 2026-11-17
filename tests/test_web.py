"""From native to the web: machine modules emitted by the JavaScript language card run in Node and in a browser
page (platform/browser) and must answer exactly as the reference interpreter and the native C library do.

Engines that are not installed are skipped with the reason (Node for ``javascript``; Node's playwright module and
its Chromium for ``browser``). Every ROM is built here by the card assembler."""
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path

from helpers import SEED, model_ctx, seed_note
from test_machine import SERIAL, graphics_rom

from cardmodel.engines.codegen import Emitter
from cardmodel.machine import asm, bench, gb, native, web
from cardmodel.machine import build as Bd


def _engine(ctx, name):
    try:
        native.resolve_engine(ctx, name)
        return None
    except native.EngineError as exc:
        return str(exc)


class Emission(unittest.TestCase):
    """No toolchain needed: the cards say how to write a machine in JavaScript."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_every_machine_module_emits_as_javascript(self):
        for name in ("lr35902_bench", "armv5te_bench", "gameboy"):
            src = Emitter(self.ctx.store, "javascript", self.ctx.ops).module_source(Bd.module(self.ctx, name))
            self.assertIn("function", src, name)

    def test_server_names_every_function_global_and_array(self):
        ir = Bd.module(self.ctx, "gameboy")
        text, emb, _ = native.served_module(self.ctx, ir, native.process_parts(self.ctx, "javascript"))
        self.assertEqual(emb["kind"], "process")
        for key in ("run_frame", "PC", "frame"):
            self.assertIn(f'"{key}":', text)

    def test_the_browser_is_a_platform_card_hosting_javascript(self):
        card = native.host_platform(self.ctx, "browser")
        self.assertEqual(card["embed"]["language"], "javascript")
        self.assertIn("@module@", card["page"])

    def test_engine_names_compose_from_cards(self):
        P = native.process_parts
        self.assertEqual(P(self.ctx, "javascript")["lang"], "javascript")
        self.assertEqual(P(self.ctx, "browser")["host"]["name"], "browser")
        w = P(self.ctx, "wasm@browser")
        self.assertEqual((w["lang"], w["server"], w["code"]["name"], w["host"]["name"]),
                         ("c", "javascript", "wasm", "browser"))
        self.assertIsNone(P(self.ctx, "c"))          # a cabi language is not a process engine
        with self.assertRaises(native.EngineError):
            P(self.ctx, "wasm@nowhere")


class Conformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def _need(self, engine):
        why = _engine(self.ctx, engine)
        if why:
            self.skipTest(why)

    def test_lr35902_cards_agree_in_javascript(self):
        self._need("javascript")
        r = bench.conformance(self.ctx, "lr35902", engines=["ir", "native", "javascript"], samples=2, seed=SEED)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertIn("javascript", r["engines"])
        self.assertEqual(r["passed"], 512)

    def test_armv5te_cards_agree_in_javascript(self):
        self._need("javascript")
        r = bench.conformance(self.ctx, "armv5te", engines=["ir", "javascript"], samples=2, seed=SEED)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertEqual(r["status"], "pass")

    def test_cards_agree_in_webassembly(self):
        """The C card's module compiled to wasm32 runs the same words as the native library."""
        self._need("wasm")
        for isa_name, n in (("lr35902", 512), ("armv5te", 167)):
            r = bench.conformance(self.ctx, isa_name, engines=["ir", "wasm"], samples=2, seed=SEED)
            bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
            self.assertEqual(bad, {}, seed_note(self))
            self.assertEqual((r["passed"], r["engines"]), (n, ["ir", "wasm"]))

    def test_cards_agree_in_the_browser(self):
        engines = [e for e in ("browser", "wasm@browser") if not _engine(self.ctx, e)]
        if not engines:
            self.skipTest(_engine(self.ctx, "browser"))
        cards = sorted(c.name for c in bench.I.instructions(self.ctx.store, "lr35902"))
        only = random.Random(SEED).sample(cards, 48)
        r = bench.conformance(self.ctx, "lr35902", engines=["ir", *engines], samples=2, seed=SEED, only=only)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertEqual(r["engines"], sorted(["ir", *engines]))

    def test_wrong_instruction_is_caught_in_javascript(self):
        """CM07: a JavaScript machine running a wrong ADD (a SUB) must disagree with the reference."""
        self._need("javascript")
        ir = Bd.module(self.ctx, "lr35902_bench")
        bad = copy.deepcopy(ir)
        for f in bad["functions"]:
            if f["name"] == "LR35902_80":
                f["body"] = [{"k": "do", "value": ["CALL", "alu_sub", ["var", "B"], ["int", 0]]}]
        good_m, bad_m = native.load(self.ctx, ir, "ir"), native.load(self.ctx, bad, "javascript")
        card = self.ctx.store.get("isa/LR35902_80")
        rng = random.Random(SEED)
        caught = 0
        for _ in range(8):
            st = bench._case_state(rng, card, None)
            ram = rng.randbytes(0x10000)
            if bench._compare(bench.run_case(good_m, card, st, ram), bench.run_case(bad_m, card, st, ram)):
                caught += 1
        self.assertGreater(caught, 0, seed_note(self))


class GameBoy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_the_whole_machine_runs_the_same_from_native_to_the_browser(self):
        engines = [e for e in ("native", "javascript", "browser", "wasm", "wasm@browser") if not _engine(self.ctx, e)]
        if len(engines) < 2 or engines[0] != "native":
            self.skipTest(f"needs native and one web engine; have {engines}")
        for rom, frames in ((asm.rom(self.ctx.store, SERIAL, title="SERIALTEST"), 3), (graphics_rom(self.ctx), 8)):
            seen = {}
            for e in engines:
                g = gb.GameBoy(self.ctx, rom, e, sample_rate=0)
                for _ in range(frames):
                    g.run_frame()
                seen[e] = (g.serial_text(), g.state_hash(), bytes(g.frame()))
            for e in engines[1:]:
                self.assertEqual(seen[e], seen["native"], e)
            self.assertEqual(seen["native"][0], "Passed\n" if frames == 3 else "")


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_page_replays_a_session_and_matches_native(self):
        for e in ("native", "javascript", "browser"):
            why = _engine(self.ctx, e)
            if why:
                self.skipTest(why)
        rom = asm.rom(self.ctx.store, SERIAL, title="SERIALTEST")
        ir, transcript, run = web.gameboy_session(self.ctx, rom, 3)
        self.assertEqual(run["serial"], "Passed\n")
        expected, ref = web.expected_answers(self.ctx, ir, transcript, "native")
        self.assertEqual(ref, "c")
        d = Path(tempfile.mkdtemp(prefix="cardmodel_web_"))
        good = d / "good.html"
        good.write_text(web.page(self.ctx, ir, transcript, expected, title="t", reference=ref, session="s"))
        r = web.check_page(self.ctx, good)
        self.assertEqual(r["result"], "pass", r["text"])
        # a planted wrong answer (one bit of one register read) must fail the page
        wrong = copy.deepcopy(expected)
        last = wrong[-1]
        k = next(i for i, v in enumerate(last) if isinstance(v, str) and v.isdigit())
        last[k] = str(int(last[k]) ^ 1)
        bad = d / "bad.html"
        bad.write_text(web.page(self.ctx, ir, transcript, wrong, title="t", reference=ref, session="s"))
        r = web.check_page(self.ctx, bad)
        self.assertEqual(r["result"], "fail", r["text"])
        self.assertIn(f"first difference at batch {len(wrong) - 1}", r["text"])
        if not _engine(self.ctx, "wasm"):
            w = d / "wasm.html"
            w.write_text(web.page(self.ctx, ir, transcript, expected, title="t", reference=ref, session="s",
                                  engine="wasm"))
            r = web.check_page(self.ctx, w)
            self.assertEqual(r["result"], "pass", r["text"])

    def test_answers_are_the_same_in_every_engine(self):
        """The protocol itself: a recorded transcript answered by the reference, the host and Node agree."""
        if _engine(self.ctx, "javascript"):
            self.skipTest("node")
        rom = asm.rom(self.ctx.store, SERIAL, title="SERIALTEST")
        ir, transcript, _ = web.gameboy_session(self.ctx, rom, 1)
        answers = {e: json.dumps(web.expected_answers(self.ctx, ir, transcript, e)[0])
                   for e in ("host", "javascript", "native", "wasm") if not _engine(self.ctx, e)}
        self.assertEqual(len(set(answers.values())), 1, list(answers))


if __name__ == "__main__":
    unittest.main()
