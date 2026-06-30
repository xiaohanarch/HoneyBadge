"""Prompt file loader — loads markdown prompt templates from disk.

Loading strategy:
  - `load_prompt(name)` reads `prompts/{name}.md` from the resolved prompts
    directory, caches it, and returns the content (or ``None`` if missing).
  - The loader never raises if the directory or file is absent; callers fall
    back to inline prompts. This makes the prompts/ directory optional at
    runtime.

Directory resolution order:
  1. Explicit ``prompts_dir`` argument to :func:`load_prompt`
  2. ``HONEYBADGE_PROMPTS_DIR`` environment variable
  3. Repo-relative ``<package_root>/../prompts``
  4. ``/opt/honeybadge/prompts``
  5. ``/app/prompts``

Mirrors the :mod:`honeybadge.ontology.loader` pattern, but with a lenient
"return None" contract instead of raising, since prompt files have inline
fallbacks in ``adapter.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

_prompt_cache: dict[str, str] = {}
"""In-memory cache of name → file content. Populated lazily on first access."""

_resolved_dir: Path | None = None
"""Cached resolved prompts directory. ``None`` means "not resolved yet"."""


def _candidate_paths() -> list[Path]:
    """Build the ordered list of prompts-directory candidates."""
    paths: list[Path] = []
    env = os.environ.get("HONEYBADGE_PROMPTS_DIR")
    if env:
        paths.append(Path(env))
    # Repo layout: src/honeybadge/llm/prompt_loader.py → parents[3] = repo root
    pkg_root = Path(__file__).resolve().parents[3]
    paths.append(pkg_root / "prompts")
    paths.append(Path("/opt/honeybadge/prompts"))
    paths.append(Path("/app/prompts"))
    return paths


def _resolve_dir(explicit: Path | None = None) -> Path | None:
    """Return the first existing prompts directory, or ``None`` if none exist."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    candidates.extend(_candidate_paths())
    for p in candidates:
        if p and p.exists() and p.is_dir():
            return p
    return None


def _get_dir(prompts_dir: Path | None = None) -> Path | None:
    """Resolve (and cache) the prompts directory.

    An explicit ``prompts_dir`` bypasses the cache and re-resolves each call,
    so tests can point at a temp directory without polluting the singleton.
    """
    if prompts_dir is not None:
        return _resolve_dir(prompts_dir)
    global _resolved_dir
    if _resolved_dir is None:
        _resolved_dir = _resolve_dir()
    return _resolved_dir


def load_prompt(name: str, prompts_dir: Path | None = None) -> str | None:
    """Load ``prompts/{name}.md`` and return its content.

    Returns ``None`` if the prompts directory or the file is missing. Results
    are cached by ``name`` (scoped to the default resolved directory). Calls
    with an explicit ``prompts_dir`` bypass the cache.

    Args:
        name: Prompt file stem (e.g. ``"cypher_system"`` → ``cypher_system.md``).
        prompts_dir: Optional override for the prompts directory (tests).
    """
    if prompts_dir is not None:
        path = prompts_dir / f"{name}.md"
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    if name in _prompt_cache:
        return _prompt_cache[name]

    base = _get_dir()
    if base is None:
        return None
    path = base / f"{name}.md"
    if not path.exists() or not path.is_file():
        return None
    content = path.read_text(encoding="utf-8")
    _prompt_cache[name] = content
    return content


def reload() -> None:
    """Clear the prompt cache and force the next load to re-read from disk."""
    _prompt_cache.clear()
    global _resolved_dir
    _resolved_dir = None
