#!/usr/bin/env python3
"""A.5 architecture-submission repository review gate.

This is deliberately a mechanical presence/coverage checker. It does not parse
source code to decide whether a change is "control machinery" and it does not
score the quality/truth of G1-G4 prose. The submission manifest partitions the
exact changed-path set; humans/models remain responsible for the classification
and architectural judgment.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_ID = "lfl.architecture_submission.v0.1"
MANIFEST_PREFIX = "docs/governance/submissions/"

_TOP_KEYS = {"schema", "submission_id", "summary", "components", "declarations"}
_COMPONENT_REQUIRED = {
    "component_id",
    "paths",
    "control_machinery",
    "owning_subsystem",
    "disposition",
    "evidence",
    "verification_level",
    "model_evidence_veto_recovery_exit",
    "rollback_route",
}
_COMPONENT_KEYS = _COMPONENT_REQUIRED | {"declaration_id"}
_DECLARATION_REQUIRED = {"declaration_id", "g1", "g2", "g3", "g4"}
_G1_KEYS = {"necessity"}
_G2_KEYS = {"authority_owner", "relationship", "non_duplication"}
_G3_KEYS = {"model_evidence", "recovery_or_reason"}
_G4_KEYS = {"rollback", "verification"}
_RELATIONSHIPS = {"reuse", "replace", "new_authority"}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(x) for x in value)


def _unknown_keys(value: dict[str, Any], allowed: set[str], *, where: str) -> list[str]:
    return [f"{where}: unknown field {key!r}" for key in sorted(set(value) - allowed)]


def _validate_path(path: Any, *, where: str) -> list[str]:
    if not _nonempty_string(path):
        return [f"{where}: path must be a non-empty string"]
    assert isinstance(path, str)
    if "\\" in path:
        return [f"{where}: path must use repository POSIX separators: {path!r}"]
    if path.startswith("/"):
        return [f"{where}: path must be repository-relative: {path!r}"]
    pure = PurePosixPath(path)
    if ".." in pure.parts or pure.as_posix() != path or path.endswith("/"):
        return [f"{where}: path must be normalized repository-relative POSIX form: {path!r}"]
    return []


def _validate_block(
    value: Any,
    *,
    where: str,
    required_keys: set[str],
    list_fields: set[str] = frozenset(),
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: must be an object"]
    errors = _unknown_keys(value, required_keys, where=where)
    for key in sorted(required_keys):
        if key not in value:
            errors.append(f"{where}: missing field {key!r}")
            continue
        if key in list_fields:
            if not _nonempty_string_list(value[key]):
                errors.append(f"{where}.{key}: must be a non-empty string list")
        elif not _nonempty_string(value[key]):
            errors.append(f"{where}.{key}: must be a non-empty string")
    return errors


def validate_manifest(doc: Any) -> list[str]:
    """Validate v0.1 structure only; never judge G1-G4 semantic quality."""
    if not isinstance(doc, dict):
        return ["manifest: top level must be an object"]

    errors = _unknown_keys(doc, _TOP_KEYS, where="manifest")
    if doc.get("schema") != SCHEMA_ID:
        errors.append(f"manifest.schema: expected {SCHEMA_ID!r}")
    if not _nonempty_string(doc.get("submission_id")):
        errors.append("manifest.submission_id: must be a non-empty string")
    if "summary" in doc and not _nonempty_string(doc.get("summary")):
        errors.append("manifest.summary: must be a non-empty string when present")

    components = doc.get("components")
    declarations = doc.get("declarations")
    if not isinstance(components, list) or not components:
        errors.append("manifest.components: must be a non-empty list")
        components = []
    if not isinstance(declarations, list):
        errors.append("manifest.declarations: must be a list")
        declarations = []

    declaration_ids: set[str] = set()
    declarations_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(declarations):
        where = f"manifest.declarations[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors.extend(_unknown_keys(raw, _DECLARATION_REQUIRED, where=where))
        for key in sorted(_DECLARATION_REQUIRED):
            if key not in raw:
                errors.append(f"{where}: missing field {key!r}")
        declaration_id = raw.get("declaration_id")
        if not _nonempty_string(declaration_id):
            errors.append(f"{where}.declaration_id: must be a non-empty string")
        elif declaration_id in declaration_ids:
            errors.append(f"{where}.declaration_id: duplicate declaration {declaration_id!r}")
        else:
            declaration_ids.add(str(declaration_id))
            declarations_by_id[str(declaration_id)] = raw

        errors.extend(_validate_block(raw.get("g1"), where=f"{where}.g1", required_keys=_G1_KEYS))
        errors.extend(_validate_block(raw.get("g2"), where=f"{where}.g2", required_keys=_G2_KEYS))
        if isinstance(raw.get("g2"), dict):
            relationship = raw["g2"].get("relationship")
            if _nonempty_string(relationship) and relationship not in _RELATIONSHIPS:
                errors.append(
                    f"{where}.g2.relationship: expected one of {sorted(_RELATIONSHIPS)}"
                )
        errors.extend(
            _validate_block(
                raw.get("g3"),
                where=f"{where}.g3",
                required_keys=_G3_KEYS,
                list_fields={"model_evidence"},
            )
        )
        errors.extend(
            _validate_block(
                raw.get("g4"),
                where=f"{where}.g4",
                required_keys=_G4_KEYS,
                list_fields={"verification"},
            )
        )

    component_ids: set[str] = set()
    path_owner: dict[str, str] = {}
    referenced_declarations: set[str] = set()
    for index, raw in enumerate(components):
        where = f"manifest.components[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors.extend(_unknown_keys(raw, _COMPONENT_KEYS, where=where))
        for key in sorted(_COMPONENT_REQUIRED):
            if key not in raw:
                errors.append(f"{where}: missing field {key!r}")

        component_id = raw.get("component_id")
        if not _nonempty_string(component_id):
            errors.append(f"{where}.component_id: must be a non-empty string")
            component_key = f"component-{index}"
        else:
            component_key = str(component_id)
            if component_key in component_ids:
                errors.append(f"{where}.component_id: duplicate component {component_key!r}")
            component_ids.add(component_key)

        paths = raw.get("paths")
        if not isinstance(paths, list) or not paths:
            errors.append(f"{where}.paths: must be a non-empty list")
            paths = []
        for path_index, path in enumerate(paths):
            errors.extend(_validate_path(path, where=f"{where}.paths[{path_index}]"))
            if not isinstance(path, str) or not path:
                continue
            previous = path_owner.get(path)
            if previous is not None:
                errors.append(
                    f"{where}.paths[{path_index}]: duplicate path {path!r}; already owned by {previous!r}"
                )
            else:
                path_owner[path] = component_key

        control = raw.get("control_machinery")
        if not isinstance(control, bool):
            errors.append(f"{where}.control_machinery: must be boolean")
            control = False

        for field in (
            "owning_subsystem",
            "disposition",
            "verification_level",
            "model_evidence_veto_recovery_exit",
            "rollback_route",
        ):
            if field in raw and not _nonempty_string(raw.get(field)):
                errors.append(f"{where}.{field}: must be a non-empty string")
        if "evidence" in raw and not _nonempty_string_list(raw.get("evidence")):
            errors.append(f"{where}.evidence: must be a non-empty string list")

        declaration_id = raw.get("declaration_id")
        if control:
            if not _nonempty_string(declaration_id):
                errors.append(
                    f"{where}.declaration_id: control_machinery=true requires a declaration reference"
                )
            elif declaration_id not in declarations_by_id:
                errors.append(f"{where}.declaration_id: missing declaration {declaration_id!r}")
            else:
                referenced_declarations.add(str(declaration_id))
        elif declaration_id is not None:
            errors.append(
                f"{where}.declaration_id: non-control component must not claim a control declaration"
            )

    for declaration_id in sorted(declaration_ids - referenced_declarations):
        errors.append(f"manifest.declarations: unused declaration {declaration_id!r}")
    return errors


def manifest_path_set(doc: Any) -> set[str]:
    paths: set[str] = set()
    if not isinstance(doc, dict):
        return paths
    components = doc.get("components")
    if not isinstance(components, list):
        return paths
    for component in components:
        if not isinstance(component, dict):
            continue
        raw_paths = component.get("paths")
        if isinstance(raw_paths, list):
            paths.update(path for path in raw_paths if isinstance(path, str) and path)
    return paths


def validate_coverage(doc: Any, changed_paths: set[str]) -> list[str]:
    """Require exact changed-path coverage; no source semantics are inspected."""
    declared = manifest_path_set(doc)
    errors: list[str] = []
    for path in sorted(changed_paths - declared):
        errors.append(f"coverage: missing changed path {path!r}")
    for path in sorted(declared - changed_paths):
        errors.append(f"coverage: manifest path not changed {path!r}")
    return errors


def parse_name_status_z(payload: str) -> set[str]:
    """Parse `git diff --name-status -z`, covering both sides of rename/copy."""
    tokens = payload.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    paths: set[str] = set()
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not status:
            raise ValueError("empty git diff status token")
        path_count = 2 if status[0] in {"R", "C"} else 1
        if index + path_count > len(tokens):
            raise ValueError(f"truncated git diff record for status {status!r}")
        for _ in range(path_count):
            path = tokens[index]
            index += 1
            if path:
                paths.add(path)
    return paths


def discover_manifest_path(changed_paths: set[str]) -> str:
    candidates = sorted(
        path
        for path in changed_paths
        if path.startswith(MANIFEST_PREFIX) and path.endswith(".json")
    )
    if len(candidates) != 1:
        raise ValueError(
            "expected exactly one changed architecture-submission manifest under "
            f"{MANIFEST_PREFIX!r}; found {len(candidates)}: {candidates}"
        )
    return candidates[0]


def git_changed_paths(
    root: Path,
    *,
    base: str | None = None,
    head: str | None = None,
    staged: bool = False,
) -> set[str]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-status", "-z", "--find-renames"]
    else:
        if not base or not head:
            raise ValueError("--base and --head are required unless --staged is used")
        cmd = ["git", "diff", "--name-status", "-z", "--find-renames", f"{base}...{head}"]
    proc = subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True)
    return parse_name_status_z(proc.stdout)


def _load_manifest(root: Path, relpath: str) -> Any:
    path = root / relpath
    if not path.is_file():
        raise ValueError(f"manifest file not found in working tree: {relpath}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {relpath}: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base commit for PR/review diff")
    parser.add_argument("--head", help="head commit for PR/review diff")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="validate the staged index instead of a base...head commit diff",
    )
    parser.add_argument(
        "--manifest",
        default="auto",
        help="repo-relative manifest path; default auto-discovers exactly one changed manifest",
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help="repository root (default: script parent repository)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.staged and (args.base or args.head):
        print("A.5 architecture submission gate: FAIL", file=sys.stderr)
        print("- use either --staged or --base/--head, not both", file=sys.stderr)
        return 2
    if not args.staged and (not args.base or not args.head):
        print("A.5 architecture submission gate: FAIL", file=sys.stderr)
        print("- --base and --head are required unless --staged is used", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    try:
        changed = git_changed_paths(root, base=args.base, head=args.head, staged=bool(args.staged))
        if not changed:
            raise ValueError("diff is empty; no architecture submission to review")
        manifest_path = discover_manifest_path(changed) if args.manifest == "auto" else str(args.manifest)
        doc = _load_manifest(root, manifest_path)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print("A.5 architecture submission gate: FAIL", file=sys.stderr)
        print(f"- {exc}", file=sys.stderr)
        return 2

    errors = validate_manifest(doc)
    errors.extend(validate_coverage(doc, changed))
    if errors:
        print("A.5 architecture submission gate: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    controls = sum(
        1
        for item in doc.get("components", [])
        if isinstance(item, dict) and item.get("control_machinery") is True
    )
    print(
        "A.5 architecture submission gate: PASS "
        f"manifest={manifest_path} changed_paths={len(changed)} "
        f"components={len(doc.get('components', []))} controls={controls}"
    )
    print("semantic_quality=not_evaluated classification_truth=not_evaluated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
