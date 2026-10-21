"""schema — a dependency-free JSON-Schema subset validator.

Card types are cards whose ``schema`` field is JSON Schema (Pheros
``card_type``; Ting ``cardtype``). This validator implements the keywords
those schemas use, so validation needs no third-party package:

  type (incl. lists), enum, const, required, properties,
  additionalProperties (bool | schema), patternProperties, items,
  minItems, maxItems, uniqueItems, minLength, maxLength, pattern,
  minimum, maximum, exclusiveMinimum, exclusiveMaximum,
  minProperties, maxProperties, allOf, anyOf, oneOf, not,
  format (uuid, date-time, semver), $ref (local "#/..." pointers).

Unknown keywords are ignored, as JSON Schema requires.

Honest limits (L1): no remote $ref, no $dynamicRef, no if/then/else,
no dependentSchemas, no unevaluatedProperties. ``format`` checks only the
three formats listed. Errors are reported as "path: message" strings.
"""
from __future__ import annotations

import re

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _is_type(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return True  # unknown type names are permissive


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#"):
        raise ValueError(f"only local $ref supported, got {ref!r}")
    node = root
    for part in ref.lstrip("#").strip("/").split("/"):
        if not part:
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def validate(instance, schema: dict | bool, path: str = "$", root: dict | None = None) -> list[str]:
    """Return a list of "path: message" errors (empty when valid)."""
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [f"{path}: no value allowed here"]
    root = root if root is not None else schema
    errs: list[str] = []
    if "$ref" in schema:
        errs += validate(instance, _resolve(schema["$ref"], root), path, root)

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is_type(instance, x) for x in types):
            return errs + [f"{path}: expected {'/'.join(types)}, got {type(instance).__name__}"]

    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in {schema['enum']!r}")
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: expected constant {schema['const']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{path}: does not match {schema['pattern']!r}")
        fmt = schema.get("format")
        if fmt == "uuid" and not _UUID.match(instance):
            errs.append(f"{path}: not a uuid")
        elif fmt == "date-time" and not _DATETIME.match(instance):
            errs.append(f"{path}: not an RFC 3339 date-time")
        elif fmt == "semver" and not _SEMVER.match(instance):
            errs.append(f"{path}: not MAJOR.MINOR.PATCH")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: {instance} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: {instance} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errs.append(f"{path}: {instance} >= exclusiveMaximum {schema['exclusiveMaximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = []
            for item in instance:
                if item in seen:
                    errs.append(f"{path}: duplicate item {item!r}")
                    break
                seen.append(item)
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(instance):
                errs += validate(item, items, f"{path}[{i}]", root)

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errs.append(f"{path}: missing required field {key!r}")
        if "minProperties" in schema and len(instance) < schema["minProperties"]:
            errs.append(f"{path}: fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
            errs.append(f"{path}: more than {schema['maxProperties']} properties")
        props = schema.get("properties", {})
        pats = schema.get("patternProperties", {})
        addl = schema.get("additionalProperties", True)
        for key, value in instance.items():
            sub = f"{path}.{key}"
            matched = False
            if key in props:
                matched = True
                errs += validate(value, props[key], sub, root)
            for pat, ps in pats.items():
                if re.search(pat, key):
                    matched = True
                    errs += validate(value, ps, sub, root)
            if not matched and addl is not True:
                errs += validate(value, addl, sub, root)

    for sub in schema.get("allOf", []):
        errs += validate(instance, sub, path, root)
    if "anyOf" in schema:
        if not any(not validate(instance, s, path, root) for s in schema["anyOf"]):
            errs.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema:
        n = sum(1 for s in schema["oneOf"] if not validate(instance, s, path, root))
        if n != 1:
            errs.append(f"{path}: matches {n} of oneOf (need exactly 1)")
    if "not" in schema and not validate(instance, schema["not"], path, root):
        errs.append(f"{path}: must not match the 'not' schema")
    return errs
