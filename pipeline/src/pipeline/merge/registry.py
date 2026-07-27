"""Which sources are configured, as distinct from which ones happen to have a file.

The health index exists so a broken source reports itself broken instead of vanishing
from the app's Sources tab. Built purely from the per-source files on disk it could not
do that for the worst case of all: a source that has *never* published successfully has
no file, so it was absent from the index rather than failing in it — the one state a
user most needs told about, and the only one the index stayed silent on.

Sources are discovered from the `pipeline.sources` package rather than listed in a
constant here. A hand-maintained list is the same bug wearing a different hat: it goes
stale the first time someone adds a source directory and forgets the entry, and the
symptom is again a source that is missing rather than one that is broken. Every source
package already declares `SOURCE` in its `config` module and is named for its own id,
so the package tree is the registry — it cannot drift from itself.
"""

from __future__ import annotations

import pkgutil
from importlib import import_module

from .. import sources as sources_package
from ..common.log import get_logger
from ..common.models import Source

log = get_logger(__name__)


def configured_sources() -> list[Source]:
    """Every source package that declares a `SOURCE`, ordered by id.

    A package that cannot be imported is logged and skipped. The merge publishes the
    feed for every other source; refusing to run because one source's config is broken
    would turn a single source's outage into a total one.
    """
    found: list[Source] = []

    for module in pkgutil.iter_modules(sources_package.__path__):
        if not module.ispkg:
            continue

        name = f"{sources_package.__name__}.{module.name}.config"
        try:
            config = import_module(name)
        except Exception as exc:  # noqa: BLE001 - any import failure must stay non-fatal
            log.error("cannot import %s, so %s will not be reported on: %s", name, module.name, exc)
            continue

        source = getattr(config, "SOURCE", None)
        if isinstance(source, Source):
            found.append(source)
        else:
            log.error("%s declares no SOURCE, so %s will not be reported on", name, module.name)

    return sorted(found, key=lambda s: s.id)
