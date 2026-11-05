"""The environment card (docs/ENVIRONMENTS.md V-A): declared identity, measured levels, evidence tiers."""
import unittest

from helpers import ROOT  # noqa: F401  (sets up the test environment)

from cardmodel.engines import environment as E
from cardmodel.kernel.schema import validate
from cardmodel.kernel.store import open_store

CURVE = [(4096, 1.5), (16384, 1.6), (32768, 1.6), (65536, 2.4), (131072, 3.4), (524288, 5.0), (1 << 20, 8.0),
         (4 << 20, 22.0), (16 << 20, 70.0), (64 << 20, 130.0)]


class FakeStore:
    def __init__(self):
        self.cards, self.registries = {}, []

    def get(self, name):
        return self.cards.get(name)

    def ensure_registry(self, category, layer=None, **_):
        self.registries.append((category, layer))

    def save(self, card, layer=None):
        self.cards[f"{card['category']}/{card['name']}"] = dict(card, _layer=layer)


class EnvironmentTest(unittest.TestCase):
    def test_levels_are_plateaus(self):
        lv = E.levels_from_curve(CURVE)
        self.assertEqual([x["up_to_bytes"] for x in lv], [65536, 524288, 1 << 20, 4 << 20, None])
        self.assertEqual(lv[0]["ns"], 1.5)
        self.assertEqual(lv[-1]["ns"], 130.0)
        self.assertEqual(E.levels_from_curve([(4096, 2.0)]), [{"up_to_bytes": None, "ns": 2.0}])

    def test_fingerprint_is_the_declared_identity(self):
        ident = E.static()
        self.assertEqual(E.fingerprint(ident), E.fingerprint(E.static()))
        other = dict(ident, os=dict(ident["os"], release="other"))
        self.assertNotEqual(E.fingerprint(ident), E.fingerprint(other))
        self.assertGreaterEqual(ident["cpu"]["logical"], 1)
        self.assertGreater(ident["memory"]["ram_mb"], 0)

    def test_card_matches_its_type_and_names_its_evidence(self):
        schema = open_store(project=False).get("card_type/environment")["schema"]
        bare = E.build_card()
        self.assertEqual(validate(bare, schema), [])
        self.assertEqual(bare["capabilities"]["latency_memory_ns"]["evidence"], "unknown")
        self.assertIsNone(bare["measured_at"])
        card = E.build_card(measured={"chase": CURVE, "copy_gb_s": 12.345}, today="2026-11-05")
        self.assertEqual(validate(card, schema), [])
        caps = card["capabilities"]
        self.assertEqual((caps["latency_first_level_ns"]["value"], caps["latency_first_level_ns"]["evidence"]),
                         (1.5, "measured"))
        self.assertEqual(caps["copy_gb_s"]["value"], 12.35)
        self.assertEqual(caps["cores_logical"]["evidence"], "declared")
        self.assertEqual(card["measured_at"], "2026-11-05")
        self.assertEqual(card["name"], f"env_{card['fingerprint']}")
        unk = E.build_card(measured={"unknown": "no C compiler"})
        self.assertEqual(unk["capabilities"]["copy_gb_s"]["reason"], "no C compiler")

    def test_generator_is_written_once_into_the_local_layer(self):
        store, calls = FakeStore(), []

        def fake():
            calls.append(1)
            return {"chase": CURVE, "copy_gb_s": 10.0}

        card, written = E.generator(store, measure_fn=fake)
        self.assertTrue(written)
        self.assertEqual(store.registries, [("environment", "local")])
        self.assertEqual(store.cards[f"environment/{card['name']}"]["_layer"], "local")
        _, written = E.generator(store, measure_fn=fake)
        self.assertFalse(written)
        self.assertEqual(len(calls), 1)
        E.generator(store, refresh=True, measure_fn=fake)
        self.assertEqual(len(calls), 2)

    def test_stale_card_is_remeasured(self):
        import datetime
        today = datetime.date(2026, 11, 5)
        self.assertTrue(E._stale({"measured_at": None}, today))
        self.assertTrue(E._stale({"measured_at": "2026-09-01"}, today))
        self.assertFalse(E._stale({"measured_at": "2026-11-01"}, today))


if __name__ == "__main__":
    unittest.main()
