"""The card index (kernel/index.py): lookups read one card, and the index never serves stale contents."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets CARDMODEL_INDEX to a temp file)
from cardmodel.kernel import index
from cardmodel.kernel.registry import Registry
from cardmodel.kernel.store import AmbiguousName, Store


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    t = time.time_ns() + 1_000_000_000 * write.n          # distinct mtimes even on coarse clocks
    write.n += 1
    os.utime(path, ns=(t, t))


write.n = 1


class Index(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.saved = os.environ.get("CARDMODEL_INDEX")
        os.environ["CARDMODEL_INDEX"] = str(self.d / "idx.sqlite")
        index.reset_index()
        write(self.d / "w" / "_category.json", {"name": "w"})
        write(self.d / "w" / "_pack.jsonl", "\n".join(json.dumps({"name": f"p{i}", "v": i}) for i in range(50)) + "\n")
        write(self.d / "w" / "a" / "card.json", {"name": "a", "v": "dir"})
        write(self.d / "w" / "p3" / "card.json", {"name": "p3", "v": "dir wins"})

    def tearDown(self):
        os.environ["CARDMODEL_INDEX"] = self.saved
        index.reset_index()
        self.tmp.cleanup()

    def test_lookup_reads_one_card(self):
        Registry(self.d / "w").all_names()                  # first use indexes the registry
        reg = Registry(self.d / "w")
        self.assertEqual(reg.get("p17")["v"], 17)
        self.assertEqual(reg.get("p17").source, "pack:_pack.jsonl")
        self.assertEqual(reg.get("a").source, "dir")
        self.assertEqual(reg.get("p3")["v"], "dir wins")
        self.assertIsNone(reg.get("nope"))
        self.assertIsNone(reg._cards, "a lookup through the index must not load the registry")
        self.assertEqual(len(reg), 51)
        self.assertEqual(reg.all_names(), list(Registry(self.d / "w", strict=True).ALL))
        c = reg.get("p17")
        self.assertIs(reg.ALL["p17"], c, "a card handed out stays the same object after a full load")

    def test_never_stale(self):
        Registry(self.d / "w").all_names()
        write(self.d / "w" / "a" / "card.json", {"name": "a", "v": "edited"})
        self.assertEqual(Registry(self.d / "w").get("a")["v"], "edited")
        write(self.d / "w" / "b" / "card.json", {"name": "b"})
        self.assertIn("b", Registry(self.d / "w").all_names())
        write(self.d / "w" / "_pack.jsonl", json.dumps({"name": "only"}) + "\n")
        reg = Registry(self.d / "w")
        self.assertIsNone(reg.get("p17"))
        self.assertEqual(reg.get("only")["name"], "only")
        (self.d / "w" / "b" / "card.json").unlink()
        self.assertNotIn("b", Registry(self.d / "w").all_names())

    def test_errors_are_kept(self):
        write(self.d / "w" / "_pack_bad.jsonl", "{not json\n")
        Registry(self.d / "w").all_names()
        reg = Registry(self.d / "w")
        self.assertTrue(any("_pack_bad.jsonl:1" in e for e in reg.errors))
        self.assertIsNone(reg._cards)

    def test_store_bare_names(self):
        write(self.d / "v" / "_category.json", {"name": "v"})
        write(self.d / "v" / "a" / "card.json", {"name": "a"})
        write(self.d / "v" / "z" / "card.json", {"name": "z"})
        Store([("model", self.d)]).all_names()
        s = Store([("model", self.d)])
        self.assertEqual(s.get("z").registry, "v")
        self.assertEqual(s.get("p17")["v"], 17)
        with self.assertRaises(AmbiguousName):
            s.get("a")
        self.assertEqual(sorted(s.all_names()), sorted(Store([("model", self.d)], strict=True).ALL))

    def test_threads_share_one_store(self):
        from concurrent.futures import ThreadPoolExecutor
        Registry(self.d / "w").all_names()
        reg = Registry(self.d / "w")
        with ThreadPoolExecutor(8) as pool:
            got = list(pool.map(lambda i: reg.get(f"p{i % 50}"), range(400)))
        self.assertTrue(all(c is not None for c in got))

    def test_off_switch(self):
        os.environ["CARDMODEL_INDEX"] = "0"
        index.reset_index()
        reg = Registry(self.d / "w")
        self.assertEqual(reg.get("p17")["v"], 17)
        self.assertIsNotNone(reg._cards)


if __name__ == "__main__":
    unittest.main()
