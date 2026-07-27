"""Minimal .env.local loader.

Deliberately not python-dotenv: this needs to read a handful of KEY=value lines for
local development only, and in CI the same values arrive as real environment
variables. Existing environment values always win, so a shell export can override the
file without editing it.
"""

from __future__ import annotations

import os
from pathlib import Path

# pipeline/src/pipeline/common/env.py -> pipeline/
_PIPELINE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = _PIPELINE_ROOT / ".env.local"


def load_env_file(path: Path | None = None) -> None:
    path = path or DEFAULT_ENV_FILE
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Locally, copy pipeline/.env.local.example to "
            f"pipeline/.env.local and fill it in. In CI it comes from a repository secret."
        )
    return value
