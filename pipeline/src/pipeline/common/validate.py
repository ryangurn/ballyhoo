"""JSON Schema validation. Runs as a publish gate at both the source and merge steps.

A schema failure must block publishing: the client cannot tolerate a shape it doesn't
expect, and a bad feed reaches every user at once.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"


class SchemaValidationError(Exception):
    """Raised when a payload does not conform. Message lists every violation."""


@cache
def _registry() -> Registry:
    """Register every local schema so `$ref: event.schema.json` resolves offline."""
    registry = Registry()
    for path in SCHEMA_DIR.glob("*.schema.json"):
        contents = json.loads(path.read_text())
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        registry = registry.with_resource(uri=path.name, resource=resource)
        if "$id" in contents:
            registry = registry.with_resource(uri=contents["$id"], resource=resource)
    return registry


@cache
def _validator(schema_name: str) -> Draft202012Validator:
    schema_path = SCHEMA_DIR / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"no schema at {schema_path}")
    return Draft202012Validator(json.loads(schema_path.read_text()), registry=_registry())


def validate(payload: dict[str, Any], schema_name: str) -> None:
    """Validate or raise, reporting all errors rather than only the first.

    Fixing one error at a time across a few hundred events is miserable; the whole
    list up front usually reveals a single systematic normalizer bug.
    """
    errors = sorted(_validator(schema_name).iter_errors(payload), key=lambda e: list(e.absolute_path))
    if not errors:
        return

    lines = [f"{len(errors)} schema violation(s) against {schema_name}:"]
    for err in errors[:25]:
        location = "/".join(str(p) for p in err.absolute_path) or "<root>"
        lines.append(f"  {location}: {err.message}")
    if len(errors) > 25:
        lines.append(f"  ... and {len(errors) - 25} more")
    raise SchemaValidationError("\n".join(lines))


def validate_per_source(payload: dict[str, Any]) -> None:
    validate(payload, "per-source.schema.json")


def validate_merged(payload: dict[str, Any]) -> None:
    validate(payload, "events.schema.json")


def validate_sources_index(payload: dict[str, Any]) -> None:
    validate(payload, "sources-index.schema.json")
