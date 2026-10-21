"""Kernel: the universal contract, registries as directories, layering, validation, versioning, closure."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, TempProject, model_ctx  # noqa: F401

import cardmodel
from cardmodel.kernel.canon import card_hash
from cardmodel.kernel.registry import CardLoadError, Registry
from cardmodel.kernel.schema import validate
from cardmodel.kernel.store import AmbiguousName, Store, open_store
from cardmodel.kernel.types import closure, validate_card, validate_store


def make_root():
    d = Path(tempfile.mkdtemp(prefix="cm_kernel_"))
    (d / "widgets").mkdir()
    (d / "widgets" / "_category.json").write_text(json.dumps({"name": "widgets", "description": "test widgets"}))
    return d


class RegistryContract(unittest.TestCase):
    def test_registry_contract(self):
        d = make_root()
        try:
            (d / "widgets" / "a").mkdir()
            (d / "widgets" / "a" / "card.json").write_text(json.dumps({"name": "a", "category": "widgets"}))
            (d / "widgets" / "_pack.jsonl").write_text(json.dumps({"name": "b", "category": "widgets"}) + "\n")
            (d / "widgets" / "notacard").mkdir()          # a folder without card.json is not a card
            reg = Registry(d / "widgets")
            self.assertEqual(sorted(reg.all_names()), ["a", "b"])
            self.assertEqual(reg.get("a").source, "dir")
            self.assertTrue(reg.get("b").source.startswith("pack:"))
            self.assertIsNone(reg.get("zzz"))
            store = Store([("model", d)])
            self.assertEqual(store.get("widgets/a")["name"], "a")
            self.assertEqual(store.get("a").qualified, "widgets/a")
            self.assertIn("widgets/b", store.all_names())
            self.assertEqual(store.ALL["widgets/a"].registry, "widgets")
        finally:
            shutil.rmtree(d)

    def test_module_surface(self):
        self.assertIn("op/ADD", cardmodel.all_names())
        self.assertEqual(cardmodel.get("op/ADD")["name"], "ADD")
        self.assertIn("language/c", cardmodel.ALL)

    def test_ambiguous_bare_name_raises(self):
        d = make_root()
        try:
            (d / "other").mkdir()
            (d / "other" / "_category.json").write_text(json.dumps({"name": "other", "description": "other things"}))
            for reg in ("widgets", "other"):
                (d / reg / "x").mkdir()
                (d / reg / "x" / "card.json").write_text(json.dumps({"name": "x", "category": reg}))
            store = Store([("model", d)])
            with self.assertRaises(AmbiguousName):
                store.get("x")
            self.assertEqual(store.get("other/x").registry, "other")
        finally:
            shutil.rmtree(d)


class Contract(unittest.TestCase):
    def test_unknown_fields_round_trip(self):
        d = make_root()
        try:
            store = Store([("model", d)])
            card = {"name": "w1", "category": "widgets", "spiritual_vibe": {"calm": 0.9}, "thermal_budget": 3}
            store.save(card)
            again = Store([("model", d)]).get("widgets/w1")
            self.assertEqual(again["spiritual_vibe"], {"calm": 0.9})
            self.assertEqual(again["thermal_budget"], 3)
            errs, _ = validate_card(again, model_ctx().store)
            self.assertEqual([e for e in errs if "spiritual" in e or "thermal" in e], [])
        finally:
            shutil.rmtree(d)

    def test_malformed_card_is_reported(self):
        d = make_root()
        try:
            (d / "widgets" / "bad").mkdir()
            (d / "widgets" / "bad" / "card.json").write_text("{not json")
            store = Store([("model", d)])
            self.assertEqual(store.cards("widgets"), [])
            errs = store.load_errors()
            self.assertTrue(any("bad" in e and "JSONDecodeError" in e for e in errs), errs)
            with self.assertRaises(CardLoadError):
                Store([("model", d)], strict=True).cards("widgets")
        finally:
            shutil.rmtree(d)

    def test_versioning_archives_previous(self):
        d = make_root()
        try:
            store = Store([("model", d)])
            store.save({"name": "v", "category": "widgets", "statement": "one"})
            first = json.loads((d / "widgets" / "v" / "card.json").read_text())
            self.assertEqual(first["metadata"]["version"], "1.0.0")
            store.save({**first, "statement": "two"})
            second = json.loads((d / "widgets" / "v" / "card.json").read_text())
            self.assertEqual(second["metadata"]["version"], "1.1.0")  # semantic change -> minor
            self.assertEqual(second["metadata"]["previous_content_hash"], card_hash(first))
            archived = list((d / "_versions" / "widgets" / "v").glob("1.0.0__*.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(card_hash(json.loads(archived[0].read_text())), card_hash(first))
            _, changed = store.save(second)                         # identical content: no new version
            self.assertFalse(changed)
            data = dict(second)
            data.pop("statement")
            store.save(data)
            third = json.loads((d / "widgets" / "v" / "card.json").read_text())
            self.assertEqual(third["metadata"]["version"], "2.0.0")  # field removed -> major
        finally:
            shutil.rmtree(d)

    def test_layering_project_overrides_model(self):
        p = TempProject()
        try:
            ctx = p.ctx()
            base = ctx.store.get("op/ADD")
            ctx.store.save({**dict(base), "statement": "project-local ADD"}, layer="project")
            ctx.store.invalidate()
            self.assertEqual(ctx.store.get("op/ADD")["statement"], "project-local ADD")
            self.assertEqual(ctx.store.get("op/ADD").layer, "project")
            self.assertNotEqual(open_store(project=False).get("op/ADD")["statement"], "project-local ADD")
        finally:
            p.cleanup()


class Validation(unittest.TestCase):
    def test_schema_subset(self):
        s = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer", "minimum": 0},
                                                                 "k": {"enum": ["a", "b"]},
                                                                 "x": {"oneOf": [{"type": "string"}, {"type": "null"}]},
                                                                 "r": {"$ref": "#/definitions/r"}},
             "definitions": {"r": {"type": "array", "items": {"type": "string", "pattern": "^z"}}}}
        self.assertEqual(validate({"n": 1, "k": "a", "x": None, "r": ["zz"]}, s), [])
        errs = validate({"n": -1, "k": "c", "x": 3, "r": ["q"]}, s)
        self.assertEqual(len(errs), 4, errs)
        self.assertEqual(validate({}, s), ["$: missing required field 'n'"])

    def test_builtin_cards_validate(self):
        ctx = model_ctx()
        findings = validate_store(ctx.store)
        errors = {q: f["errors"] for q, f in findings.items() if f["errors"]}
        self.assertEqual(errors, {})
        self.assertEqual(ctx.store.load_errors(), [])

    def test_card_type_catches_bad_card(self):
        ctx = model_ctx()
        bad = cardmodel.Card({"name": "9bad name", "category": "op", "status": "great"}, registry="op")
        errs, _ = validate_card(bad, ctx.store)
        self.assertTrue(any("$.name" in e for e in errs))
        self.assertTrue(any("status 'great'" in e for e in errs))
        self.assertTrue(any("missing required field 'statement'" in e for e in errs))

    def test_builtin_closure(self):
        self.assertEqual(closure(model_ctx().store), [])


if __name__ == "__main__":
    unittest.main()
