"""Exact WebUI source-to-dist binding for controlled releases.

An asset tree SHA proves that the copied bundle was preserved, but says
nothing about which tracked WebUI sources produced it. Keep that second
proof separately so an old but internally consistent dist cannot publish.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

_MANIFEST = ".lfl-webui-source.json"
_SCHEMA = "lfl-webui-source/v1"


def tracked_webui_fingerprint(code_root: Path) -> tuple[str, int]:
    """Hash path + exact bytes for every tracked WebUI file, in stable order.

    This deliberately does not rely on commit id, so the build can be tested
    before a commit. The publish entrypoint already requires a clean HEAD.
    """
    paths = subprocess.run(
        ["git", "-C", str(code_root), "ls-files", "-z", "--", "webui"],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout
    tracked = sorted(path for path in paths.split(b"\0") if path)
    if not tracked:
        raise ValueError("webui source binding: no tracked WebUI files")
    checksum = hashlib.sha256()
    for relative in tracked:
        checksum.update(relative)
        checksum.update(b"\0")
        file_digest = hashlib.sha256((code_root / os.fsdecode(relative)).read_bytes()).digest()
        checksum.update(file_digest)
        checksum.update(b"\0")
    return checksum.hexdigest(), len(tracked)


def verify_webui_source_binding(code_root: Path, *, dist_root: Path | None = None) -> None:
    """Fail closed for real WebUI packages; lightweight test repos have none.

    Returns only when the currently stored static bundle declares the exact
    tracked WebUI input tree used for its build. No network or mutation.
    """
    if not (code_root / "webui" / "package.json").is_file():
        # Legacy Python-only unit fixtures have synthetic HTML but no npm app.
        return
    untracked = subprocess.run(
        [
            "git", "-C", str(code_root), "ls-files", "--others",
            "--exclude-standard", "-z", "--", "webui",
        ],
        check=True, capture_output=True, timeout=10,
    ).stdout
    if untracked.strip(b"\0"):
        raise ValueError(
            "webui source binding has untracked WebUI inputs; commit or remove them before publish"
        )
    dist = dist_root if dist_root is not None else code_root / "webui" / "dist"
    manifest = dist / _MANIFEST
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            "webui source binding missing or unreadable; run npm run build in this code_root"
        ) from exc
    if (
        not isinstance(raw, dict)
        or raw.get("schema") != _SCHEMA
        or not isinstance(raw.get("source_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", raw["source_sha256"])
        or type(raw.get("tracked_files")) is not int
        or raw["tracked_files"] <= 0
    ):
        raise ValueError("webui source binding malformed; run npm run build in this code_root")
    source_sha, count = tracked_webui_fingerprint(code_root)
    if raw["source_sha256"] != source_sha or raw["tracked_files"] != count:
        raise ValueError(
            "webui source binding mismatch: dist was not built from this tracked WebUI source "
            f"(bundle={raw['source_sha256'][:16]}/{raw['tracked_files']} "
            f"source={source_sha[:16]}/{count}); run npm run build"
        )
