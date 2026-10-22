"""Code found by reasoning (cardmodel/machine/absint.py): a synthetic cartridge whose code is reached only through a
far call (a bank number and an address in registers, a trampoline that switches the bank and jumps through HL) and
a jump table (an index into a table of addresses, a routine that jumps to the entry). Recursive descent cannot see
either; the abstract run of the machine's cards finds the far call's target in its bank and every entry of the
table, and stops at the word that is not an address of code."""
import unittest

from helpers import model_ctx

from cardmodel.machine import absint, asm, lift


def cartridge(ctx) -> bytes:
    a = lambda items, org: asm.assemble(ctx.store, items, org=org)  # noqa: E731
    main = [("LD SP,nn", 0xFFFE),
            ("LD A,n", 2), ("LD HL,nn", 0x4000), ("CALL nn", 0x0200),          # far call: bank 2, 0x4000
            ("LD A,n", 1), ("LD HL,nn", 0x0400), ("CALL nn", 0x0280),          # jump table at 0x0400, entry 1
            ("label", "idle"), ("HALT",), ("JR e", "idle")]
    extra = {
        0x0200: a([("LD (nn),A", 0x2000), ("JP HL",)], 0x0200),              # switch to bank A, jump to HL
        0x0280: a([("LD E,A",), ("LD D,n", 0), ("ADD HL,DE",), ("ADD HL,DE",), ("LD A,(HL+)",), ("LD H,(HL)",),
                   ("LD L,A",), ("JP HL",)], 0x0280),                           # PC = word at HL + 2A
        0x0300: a([("LD B,n", 1), ("RET",)], 0x0300),
        0x0310: a([("LD B,n", 2), ("RET",)], 0x0310),
        0x0320: a([("LD B,n", 3), ("RET",)], 0x0320),
        0x0400: bytes([0x00, 0x03, 0x10, 0x03, 0x20, 0x03, 0xFF, 0xFF]),     # three entries, then not an address
        0x8000: a([("LD C,n", 7), ("RET",)], 0x4000),                          # bank 2's first instruction
    }
    return asm.rom(ctx.store, main, title="ABSINT", cart_type=0x01, rom_size_code=1, extra=extra)


class CodeFoundByReasoning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rom = cartridge(cls.ctx)
        cls.mask = len(cls.rom) - 1
        cls.leaders = lift.discover(cls.ctx.store, cls.rom, cls.mask)["leaders"]
        cls.r = absint.discover(cls.ctx, cls.rom, cls.mask, cls.leaders)

    def test_recursive_descent_does_not_see_it(self):
        phys = {k >> 1 for k in self.leaders}
        for a in (0x8000, 0x0300, 0x0310, 0x0320):
            self.assertNotIn(a, phys, hex(a))

    def test_the_far_call_and_the_table_are_found(self):
        new = set(self.r["entries"])
        self.assertIn(lift._key(0x8000, 0x4000), new, "the far call's target, in bank 2")
        for a in (0x0300, 0x0310, 0x0320):
            self.assertIn(lift._key(a, a), new, f"the table's entry {a:#x}")
        self.assertNotIn(lift._key(0x7FFF, 0x7FFF), new)
        self.assertGreaterEqual(self.r["far"], 1)
        self.assertGreaterEqual(self.r["tables"], 3)


if __name__ == "__main__":
    unittest.main()
