"""Shared HTTP identity for every source fetcher.

One constant rather than a copy per source: the User-Agent is the project's identity
to upstream operators, not a per-source implementation detail, and a single value
means a site that objects can block or contact us in one place.

The contact is written as a bare domain rather than `+https://github.com/...`.
DoPDX's WAF rejects any User-Agent containing a URL scheme — measured directly: the
bare product token alone and the token followed by a parenthesized bare domain both
return 200, while the same string with `+https://` returns 403, and plain `curl/8.0`
returns 200. So the trigger is the scheme, not the token or the domain. The bare
domain keeps us identifiable to an operator reading their logs without tripping that
pattern; do not add a scheme back when editing this value.
"""

from __future__ import annotations

USER_AGENT = "ballyhoo-pipeline/0.1 (github.com/ryangurn/ballyhoo)"

JSON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

HTML_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html",
}
