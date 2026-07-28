"""Commit files to a publishing branch.

Several workflows push to the same branches concurrently — each source workflow plus
the merge workflow. They write disjoint paths, so conflicts are rare, but "rare" over
hourly runs still means "eventually". Every push therefore rebases onto the remote
first and retries.

The caller supplies a directory that is already a checkout of the target branch; in CI
that is a second `actions/checkout` into a subdirectory.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .log import get_logger

log = get_logger(__name__)

MAX_PUSH_ATTEMPTS = 5

# Commits are attributed to the workflow rather than to whoever last touched the repo.
BOT_NAME = "ballyhoo-pipeline"
BOT_EMAIL = "ballyhoo-pipeline@users.noreply.github.com"


class PublishError(Exception):
    """A git operation failed in a way retrying will not fix."""


@dataclass(frozen=True)
class PublishResult:
    committed: bool
    reason: str
    files_written: int


def _git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


def _ensure_identity(repo_dir: Path) -> None:
    _git(repo_dir, "config", "user.name", BOT_NAME)
    _git(repo_dir, "config", "user.email", BOT_EMAIL)


def write_files(repo_dir: Path, files: dict[str, str | bytes]) -> int:
    for relative, content in files.items():
        target = repo_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
    return len(files)


def publish(
    repo_dir: Path,
    files: dict[str, str | bytes],
    *,
    message: str,
    branch: str,
    dry_run: bool = False,
    remove: list[str] | None = None,
) -> PublishResult:
    """Write, commit, and push. Returns without committing when nothing changed."""
    if not (repo_dir / ".git").exists():
        raise PublishError(f"{repo_dir} is not a git checkout")

    written = write_files(repo_dir, files)

    for relative in remove or []:
        target = repo_dir / relative
        if target.exists():
            target.unlink()

    if dry_run:
        return PublishResult(False, "dry run", written)

    _ensure_identity(repo_dir)
    _git(repo_dir, "add", "-A")

    # An unchanged artifact must not produce an empty commit; the archive's content
    # dedup depends on commits meaning something actually changed.
    if _git(repo_dir, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return PublishResult(False, "no changes", written)

    _git(repo_dir, "commit", "-m", message)

    last_error = ""
    for attempt in range(1, MAX_PUSH_ATTEMPTS + 1):
        push = _git(repo_dir, "push", "origin", f"HEAD:{branch}", check=False)
        if push.returncode == 0:
            return PublishResult(True, f"pushed to {branch}", written)

        last_error = push.stderr.strip()
        if attempt == MAX_PUSH_ATTEMPTS:
            break

        # Another workflow pushed between our fetch and our push. Replay on top.
        log.warning("push to %s rejected (attempt %d/%d); rebasing", branch, attempt, MAX_PUSH_ATTEMPTS)
        # CI clones shallow, and rebasing needs a common ancestor. Deepen rather than
        # unshallowing outright, which on the archive branch would pull years of history.
        _git(repo_dir, "fetch", "--deepen=50", "origin", branch, check=False)
        _git(repo_dir, "fetch", "origin", branch, check=False)
        rebase = _git(repo_dir, "rebase", "--autostash", f"origin/{branch}", check=False)
        if rebase.returncode != 0:
            _git(repo_dir, "rebase", "--abort", check=False)
            raise PublishError(
                f"could not rebase onto origin/{branch}: {rebase.stderr.strip()}. "
                f"Workflows should write disjoint paths; a conflict means two are writing the same file."
            )
        time.sleep(attempt)

    raise PublishError(f"push to {branch} failed after {MAX_PUSH_ATTEMPTS} attempts: {last_error}")
