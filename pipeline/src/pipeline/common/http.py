"""Shared HTTP identity for every source fetcher.

One constant rather than a copy per source: the User-Agent is the project's identity
to upstream operators, not a per-source implementation detail, and a single value
means a site that objects can block or contact us in one place.

The contact is written as a bare domain rather than `+https://github.com/...`.
DoPDX's WAF rejects any User-Agent containing a URL scheme — measured directly:
`sociallist-pipeline/0.1` and `sociallist-pipeline/0.1 (github.com/ryangurn/sociallist)`
both return 200, while the same string with `+https://` returns 403, and plain
`curl/8.0` returns 200. So the block is an incidental pattern match on the scheme,
not a policy about automated access, which their robots.txt permits. Dropping the
scheme keeps us fully identifiable while staying out of that rule's way.
"""

from __future__ import annotations

USER_AGENT = "sociallist-pipeline/0.1 (github.com/ryangurn/sociallist)"

JSON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

HTML_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html",
}
