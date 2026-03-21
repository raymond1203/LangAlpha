"""Canonical workspace path constants shared across server, CLI, and sandbox.

All Python consumers (server, CLI, sandbox) import from here and derive their
own format (trailing ``/``, bare names, etc.).  The frontend (JS) keeps its own
copy in ``FilePanel.jsx`` with a comment pointing back to this file.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Agent system directories (toggleable in file listings, hidden in completions)
# ---------------------------------------------------------------------------
# These are agent-infrastructure dirs at the sandbox root (/home/workspace/).
# Update this set when adding new agent infrastructure directories.
AGENT_SYSTEM_DIRS: frozenset[str] = frozenset({
    "code",
    "tools",
    "mcp_servers",
    "skills",
    ".agent",
    ".self-improve",
})

# ---------------------------------------------------------------------------
# Hidden path filters (always hidden from listings and completions)
# ---------------------------------------------------------------------------
HIDDEN_DIR_NAMES: frozenset[str] = frozenset({"_internal"})

# Directories always hidden from listings and excluded from file sync.
# Matched as path segments (at any depth) — e.g. "node_modules" matches
# both root-level and nested occurrences like "foo/node_modules/".
ALWAYS_HIDDEN_DIR_NAMES: frozenset[str] = frozenset({
    # Package managers / dependencies
    "node_modules",
    ".venv",
    "venv",
    "vendor",
    # Build artifacts
    ".next",
    ".nuxt",
    # Caches
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    # VCS
    ".git",
    # Environment / tool dirs
    ".npm",
    ".local",
    ".config",
    ".ipython",
})

ALWAYS_HIDDEN_PATH_SEGMENTS: tuple[str, ...] = ("/__pycache__/",)
ALWAYS_HIDDEN_BASENAMES: tuple[str, ...] = (
    "__init__.py",
    ".bash_logout",
    ".bashrc",
    ".profile",
)
ALWAYS_HIDDEN_SUFFIXES: tuple[str, ...] = (".pyc",)
