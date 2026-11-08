"""Distribution ownership facts with no dependency on lifecycle or installers."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


def installed_identity(module: Path, *, bundle: Path | None = None,
                       distribution_resolver=distribution) -> dict[str, str] | None:
    root = bundle if bundle is not None else module.resolve().parent / "_bundled"
    if not (root / "manifest.json").is_file():
        return None
    try:
        dist = distribution_resolver("llm-first-loop")
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
