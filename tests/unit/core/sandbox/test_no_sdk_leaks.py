"""Phase 3 gate test: verify daytona_sdk imports are confined to the provider module.

Uses AST analysis to scan all .py files under src/ and ensure that only the
allowed file (providers/daytona.py) imports from daytona_sdk.  This prevents
SDK coupling from leaking back into the rest of the codebase.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The only file allowed to import daytona_sdk
ALLOWED_DAYTONA_IMPORTS = {
    "src/ptc_agent/core/sandbox/providers/daytona.py",
}

SRC_ROOT = Path(__file__).resolve().parents[4] / "src"


def _collect_python_files(root: Path) -> list[Path]:
    """Return all .py files under *root*, excluding __pycache__."""
    return [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _file_imports_daytona_sdk(filepath: Path) -> bool:
    """Return True if *filepath* contains any import of daytona_sdk (AST-based)."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "daytona_sdk" or alias.name.startswith("daytona_sdk."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "daytona_sdk"
                or node.module.startswith("daytona_sdk.")
            ):
                return True
    return False


def test_no_daytona_sdk_leaks() -> None:
    """All daytona_sdk imports must be inside the allowed provider module."""
    assert SRC_ROOT.is_dir(), f"src root not found: {SRC_ROOT}"

    violations: list[str] = []
    for py_file in _collect_python_files(SRC_ROOT):
        rel = py_file.relative_to(SRC_ROOT.parent)
        if str(rel) in ALLOWED_DAYTONA_IMPORTS:
            continue
        if _file_imports_daytona_sdk(py_file):
            violations.append(str(rel))

    assert violations == [], (
        f"daytona_sdk imported outside allowed modules:\n"
        + "\n".join(f"  - {v}" for v in sorted(violations))
    )


def test_allowed_file_exists() -> None:
    """Sanity check: the allowed provider file actually exists."""
    for allowed in ALLOWED_DAYTONA_IMPORTS:
        path = SRC_ROOT.parent / allowed
        assert path.is_file(), f"Allowed file not found: {path}"


def test_allowed_file_does_import_daytona_sdk() -> None:
    """Sanity check: the provider file does actually import daytona_sdk."""
    for allowed in ALLOWED_DAYTONA_IMPORTS:
        path = SRC_ROOT.parent / allowed
        assert _file_imports_daytona_sdk(path), (
            f"Expected {allowed} to import daytona_sdk but it does not"
        )
