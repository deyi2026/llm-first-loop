"""清单与校验：产物哈希 + 码字来源 + 复核。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import tag36h11_table as table
from .codes import family_invariants
from .layout import Layout

GENERATOR_VERSION = "ctp_gen/0.1.0"
LAYOUT_NAME = "layout.json"
MATRICES_NAME = "board-matrices.json"
PDF_NAME = "target-board.pdf"
ARTIFACTS = (LAYOUT_NAME, MATRICES_NAME, PDF_NAME)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(outdir: Path, layouts: list[Layout]) -> dict[str, Any]:
    invariants = family_invariants()
    if not invariants["invariant_ok"]:
        raise ValueError(f"family invariants violated: {invariants}")
    return {
        "generator": GENERATOR_VERSION,
        "family": table.FAMILY,
        "codes_source": {
            "file": "ctp/docs/upstream/apriltag-tag36h11.c",
            "sha256": sha256_file(Path(__file__).resolve().parents[2] / "docs/upstream/apriltag-tag36h11.c"),
            "license": "BSD-2-Clause (Univ. of Michigan Regents, 2013-2016)",
            "ncodes": table.NCODES,
            "min_pairwise_hamming": invariants["min_pairwise_hamming"],
        },
        "boards": [
            {
                "board_index": layout.board_index,
                "target_indices": list(layout.target_indices),
                "frame_ref": layout.frame_ref,
            }
            for layout in layouts
        ],
        "artifacts": {name: sha256_file(outdir / name) for name in ARTIFACTS},
    }


def verify_manifest(outdir: str | Path) -> dict[str, Any]:
    """复核目录内 manifest.json 与产物哈希是否一致；任何不匹配即 ok=False。"""
    out = Path(outdir)
    manifest_path = out / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "errors": ["manifest.json absent"]}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for name in ARTIFACTS:
        path = out / name
        if not path.is_file():
            errors.append(f"{name} absent")
            continue
        actual = sha256_file(path)
        expected = manifest.get("artifacts", {}).get(name)
        if actual != expected:
            errors.append(f"{name} sha256 mismatch: {actual} != {expected}")
    codes_sha = manifest.get("codes_source", {}).get("sha256")
    if codes_sha:
        upstream = Path(__file__).resolve().parents[2] / "docs/upstream/apriltag-tag36h11.c"
        if sha256_file(upstream) != codes_sha:
            errors.append("upstream codes source sha256 mismatch")
    return {"ok": not errors, "errors": errors, "manifest": manifest}
