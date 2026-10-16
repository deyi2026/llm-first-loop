"""Facts about the wheel installation, independent of the task workspace."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


def bundle_root() -> Path | None:
    root = Path(__file__).resolve().parents[1] / "_bundled"
    return root if (root / "manifest.json").is_file() else None


def installed_identity(module: Path) -> dict[str, str] | None:
    """Recognize a distribution-owned package, never a relocated source checkout."""
    root = bundle_root()
    if root is None:
        return None
    try:
        dist = distribution("llm-first-loop")
        owned_module = Path(str(dist.locate_file("llm_loop/__init__.py"))).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        listed = {str(f) for f in dist.files or ()}
        if (
            module.resolve() != owned_module
            or "llm_loop/_bundled/manifest.json" not in listed
            or manifest.get("schema") != "lfl.application-bundle/v1"
            or manifest.get("version") != dist.version
        ):
            return None
        return {"name": "llm-first-loop", "version": dist.version,
                "package_root": str(owned_module.parent)}
    except (PackageNotFoundError, OSError, ValueError, AttributeError):
        return None
