"""Read SvelteKit `__data.json` responses.

DoPDX's site is a SvelteKit app. Every page has a `__data.json` twin that returns the
data the page renders, as one node per layout or route. Each node's data is a flat
array in the `devalue` format: index 0 is the root, and every object or array member
is an index into that same array, so repeated values are stored once.
"""

from __future__ import annotations

from typing import Any

# devalue's reserved negative indices.
_UNDEFINED = -1
_HOLE = -2
_SPECIALS: dict[int, Any] = {
    _UNDEFINED: None,
    _HOLE: None,
    -3: float("nan"),
    -4: float("inf"),
    -5: float("-inf"),
    -6: -0.0,
}


class SvelteKitPayloadError(ValueError):
    """The response was not a usable SvelteKit data payload."""


def decode_node(values: list[Any]) -> Any:
    """Rebuild the value a single node's flat `data` array describes."""
    if not values:
        return None

    cache: dict[int, Any] = {}

    def resolve(index: int) -> Any:
        if index in _SPECIALS:
            return _SPECIALS[index]
        if index in cache:
            return cache[index]
        if not 0 <= index < len(values):
            raise SvelteKitPayloadError(f"reference {index} is outside a {len(values)}-value node")

        value = values[index]
        if isinstance(value, dict):
            result: Any = {}
            cache[index] = result
            for key, ref in value.items():
                result[key] = resolve(ref)
        elif isinstance(value, list):
            if value and isinstance(value[0], str):
                # A typed value such as ["Date", "2026-11-22T00:00:00Z"]. Only dates
                # are plausible in an events payload; anything else is not needed.
                result = value[1] if value[0] == "Date" and len(value) > 1 else None
                cache[index] = result
            else:
                result = []
                cache[index] = result
                result.extend(resolve(ref) for ref in value)
        else:
            result = value
            cache[index] = result
        return result

    return resolve(0)


def page_data(payload: Any) -> list[dict[str, Any]]:
    """Decode every data node of a `__data.json` response, outermost layout first."""
    if not isinstance(payload, dict):
        raise SvelteKitPayloadError("payload is not an object")
    if payload.get("type") != "data":
        raise SvelteKitPayloadError(f"payload type is {payload.get('type')!r}, not 'data'")

    decoded = []
    for node in payload.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "data":
            value = decode_node(node.get("data") or [])
            if isinstance(value, dict):
                decoded.append(value)
    return decoded


def find_key(payload: Any, key: str) -> Any:
    """The value of `key` from the innermost node that carries it."""
    for node in reversed(page_data(payload)):
        if key in node:
            return node[key]
    raise SvelteKitPayloadError(f"no node carries {key!r}")
