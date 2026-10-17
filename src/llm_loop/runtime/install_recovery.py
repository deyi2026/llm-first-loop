"""Operator-attested *cold* install backup and isolated recovery.

This module does not update a wheel, control services, mutate process env or
restore over a live data root. Its snapshots provide SHA integrity, not a signed
origin or a transaction across otherwise live application processes.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from llm_loop.config import read_env_file_values
from llm_loop.runtime.first_use import _open_directory_chain
from llm_loop.runtime.paths import infer_state_root

SCHEMA = "lfl.install-backup/v1"
_MAX_FILES = 100_000
_MAX_BYTES = 8 * 1024**3
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


class BackupRejectedError(Exception):
    """Bounded denial, never includes a file path or credential."""


def _path(raw: str | Path) -> Path:
    value = Path(raw).expanduser()
    if ".." in value.parts:
        raise BackupRejectedError("unsafe_path")
    absolute = Path(os.path.abspath(value))
    if absolute.is_symlink():
        raise BackupRejectedError("symlink_root")
    return Path(os.path.realpath(absolute.parent)) / absolute.name


def _is_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _safe_input(path: Path, bundle: Path | None = None) -> None:
    if path.is_symlink():
        raise BackupRejectedError("symlink_root")
    if bundle is not None and (
        _is_within(path, Path(os.path.realpath(bundle)))
        or (path.is_dir() and _is_within(Path(os.path.realpath(bundle)), path))
    ):
        raise BackupRejectedError("immutable_bundle")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise BackupRejectedError("unsupported_file_type")


def _effective_sources(*, args: Any, home: Path, bundle: Path | None,
                       environment: Mapping[str, str]) -> dict[str, Path]:
    shell = dict(environment)
    config = _path(args.config or shell.get("LFL_ENV_FILE") or home / ".env")
    _safe_input(config, bundle)
    try:
        values = read_env_file_values(config) if config.is_file() else {}
    except (OSError, UnicodeError, ValueError) as exc:
        raise BackupRejectedError("unreadable_config") from exc

    merged = dict(shell)
    for key, value in values.items():
        merged.setdefault(key, value)

    def configured(key: str) -> str:
        raw = str(merged.get(key, "") or "")
        # Like the application loader, relative env-file path values are
        # anchored to the config's parent, never to an arbitrary shell cwd.
        if key in values and key not in shell and raw and not Path(raw).expanduser().is_absolute():
            return str(config.parent / raw)
        return raw

    data_arg = args.data_dir or configured("DATA_DIR") or configured("LFL_DATA_DIR")
    data = _path(data_arg or home / "data")
    state_root, _source = infer_state_root(data)
    experiences = _path(configured("EXPERIENCES_DIR") or state_root / "experiences")
    methods = _path(configured("METHODS_DIR") or data / "methods")
    roots = {"config": config, "data": data, "experiences": experiences, "methods": methods}
    for role, root in roots.items():
        _safe_input(root, bundle)
        if root.exists() and (root.is_file() if role != "config" else root.is_dir()):
            raise BackupRejectedError("unexpected_source_kind")
    return roots


def _capture_layout(roots: Mapping[str, Path]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Choose each existing physical source once; retain logical nested roles.

    Always select the outermost directory. Equal directories break ties with a
    fixed role order so that aliases can never point at another alias.
    """
    priority = {"data": 0, "experiences": 1, "methods": 2, "config": 3}
    sources: dict[str, str] = {}
    aliases: dict[str, dict[str, str]] = {}
    for role, root in roots.items():
        if role not in priority:
            raise BackupRejectedError("unknown_source_role")
        if not root.exists():
            sources[role] = "absent"
            continue
        kind = "file" if role == "config" else "directory"
        if not (root.is_file() if kind == "file" else root.is_dir()):
            raise BackupRejectedError("unexpected_source_kind")
        parents = [
            (len(other.parts), priority[other_role], other_role, other)
            for other_role, other in roots.items()
            if other_role != role
            and other_role != "config"
            and other.is_dir()
            and _is_within(root, other)
            and (root != other or priority[other_role] < priority[role])
        ]
        if not parents:
            sources[role] = kind
            continue
        _, _, parent_role, parent = min(parents)
        relative = "" if root == parent else root.relative_to(parent).as_posix()
        sources[role] = "alias"
        aliases[role] = {"under": parent_role, "relative": relative}
    return sources, aliases


def upgrade_plan(*, bundle: Path | None, installed_version: str | None) -> dict[str, Any]:
    return {
        "schema": "lfl.upgrade.plan/v1",
        "read_only": True,
        "package_replaced": False,
        "services_changed": False,
        "current_installation": "wheel" if bundle is not None else "source_or_unverified",
        "current_version": installed_version if bundle is not None else None,
        "compatibility": "unknown_requires_operator_review",
        "data_migration": "not_performed",
        "next_steps": [
            "lfl backup --plan --json",
            "operator-confirmed cold backup and integrity verification",
            "verify trusted wheel digest and prior wheel availability",
            "separately approve wheel replacement and service restart",
        ],
    }


def backup_plan(*, args: Any, home: Path, bundle: Path | None,
                environment: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, Path]]:
    roots = _effective_sources(args=args, home=home, bundle=bundle, environment=environment)
    captures, aliases = _capture_layout(roots)
    sources: dict[str, dict[str, Any]] = {}
    for role, root in roots.items():
        sources[role] = {"exists": root.exists(),
                         "kind": "file" if root.is_file() else "directory" if root.is_dir() else "absent",
                         "captured_via": aliases[role]["under"] if role in aliases
                         else role if captures[role] != "absent" else None}
    return ({
        "schema": "lfl.backup.plan/v1",
        "read_only": True,
        "write_performed": False,
        "coverage": "selected_roots",
        "source_consistency": "operator_attestation_required_not_verified",
        "max_files": _MAX_FILES,
        "max_bytes": _MAX_BYTES,
        "sources": sources,
        "next_steps": ["stop affected processes", "lfl backup --to NEW_DIR --confirm-services-stopped"],
    }, roots)


def _opened_file(path: Path) -> tuple[int, os.stat_result]:
    parent_fd, _ = _open_directory_chain(path.parent, create=False)
    try:
        fd = os.open(path.name, _FILE_FLAGS, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise BackupRejectedError("unsupported_file_identity")
    return fd, info


def _read_bytes(path: Path, limit: int = 16 * 1024 * 1024) -> bytes:
    fd, before = _opened_file(path)
    try:
        if before.st_size > limit:
            raise BackupRejectedError("manifest_too_large")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            content = stream.read(limit + 1)
        after = os.fstat(fd)
        if len(content) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise BackupRejectedError("unstable_file")
        return content
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    fd, _ = _open_directory_chain(path, create=False)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_private_file(target: Path, content: bytes) -> None:
    """Write exclusive private file, then data and parent directory fsync."""
    parent_fd, _ = _open_directory_chain(target.parent, create=False)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _safe_new_dir(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise BackupRejectedError("target_exists")
    parent_fd, _ = _open_directory_chain(path.parent, create=False)
    try:
        try:
            os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise BackupRejectedError("target_exists") from exc
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _budget_add(budget: dict[str, int], file_size: int) -> None:
    budget["count"] += 1
    budget["bytes"] += file_size
    if budget["count"] > _MAX_FILES or budget["bytes"] > _MAX_BYTES:
        raise BackupRejectedError("snapshot_budget_exceeded")


def _copy_file(source: Path, dest: Path, budget: dict[str, int]) -> dict[str, Any]:
    src_fd, before = _opened_file(source)
    try:
        _budget_add(budget, before.st_size)
        parent_fd, _ = _open_directory_chain(dest.parent, create=False)
        try:
            dest_fd = os.open(dest.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=parent_fd)
            sha = hashlib.sha256()
            total = 0
            with os.fdopen(src_fd, "rb", closefd=False) as origin, os.fdopen(dest_fd, "wb") as out:
                os.fchmod(out.fileno(), 0o600)
                while part := origin.read(1024 * 1024):
                    total += len(part)
                    if total > before.st_size:
                        raise BackupRejectedError("source_changed_while_copying")
                    out.write(part)
                    sha.update(part)
                out.flush()
                os.fsync(out.fileno())
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        after = os.fstat(src_fd)
        if total != before.st_size or (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise BackupRejectedError("source_changed_while_copying")
        return {"size": total, "sha256": sha.hexdigest()}
    finally:
        os.close(src_fd)


def _copy_directory(source: Path, target: Path, relative: str,
                    manifest: dict[str, Any], budget: dict[str, int]) -> None:
    if len(manifest["dirs"]) >= _MAX_FILES:
        raise BackupRejectedError("too_many_directories")
    _safe_new_dir(target)
    manifest["dirs"].append(relative)
    directory_fd, _ = _open_directory_chain(source, create=False)
    try:
        before = os.fstat(directory_fd)
        if not stat.S_ISDIR(before.st_mode):
            raise BackupRejectedError("source_directory_changed")
        with os.scandir(directory_fd) as scan:
            names = sorted(item.name for item in scan)
        for name in names:
            if name in ("", ".", ".."):
                raise BackupRejectedError("unsafe_source_entry")
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            child = source / name
            output = target / name
            path = relative + "/" + name
            if stat.S_ISLNK(info.st_mode):
                raise BackupRejectedError("symlink_in_source")
            if stat.S_ISDIR(info.st_mode):
                _copy_directory(child, output, path, manifest, budget)
            elif stat.S_ISREG(info.st_mode):
                result = _copy_file(child, output, budget)
                manifest["files"].append({"path": path, **result})
            else:
                raise BackupRejectedError("unsupported_source_entry")
        after = os.fstat(directory_fd)
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise BackupRejectedError("directory_changed_during_snapshot")
    finally:
        os.close(directory_fd)
    _fsync_dir(target)


def _manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def create_backup(target_raw: str, roots: dict[str, Path], *, bundle: Path | None) -> dict[str, Any]:
    target = _path(target_raw)
    _safe_input(target, bundle)
    if target.exists():
        raise BackupRejectedError("target_exists")
    if not target.parent.is_dir():
        raise BackupRejectedError("target_parent_missing")
    for role, source in roots.items():
        _safe_input(source, bundle)
        if source.exists() and (
            _is_within(target, source) if source.is_dir() else target == source
        ):
            raise BackupRejectedError("backup_inside_source")
        if role not in ("config", "data", "experiences", "methods"):
            raise BackupRejectedError("unknown_source_role")

    captures, aliases = _capture_layout(roots)

    # Exclusive mkdir reserves the final name; interrupted copies remain
    # visibly incomplete without a final manifest. Never replace/delete them.
    _safe_new_dir(target)
    payload = target / "payload"
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "complete": True,
        "coverage": "selected_roots",
        "consistency": "operator_attested_services_stopped_not_mechanically_verified",
        "sources": captures.copy(), "aliases": aliases, "dirs": [], "files": [],
    }
    budget = {"count": 0, "bytes": 0}
    try:
        _safe_new_dir(payload)
        for role, source in sorted(roots.items()):
            if captures[role] in ("absent", "alias"):
                continue
            if captures[role] == "file":
                _safe_new_dir(payload / role)
                manifest["dirs"].append(role)
                copied = _copy_file(source, payload / role / "value", budget)
                manifest["files"].append({"path": role + "/value", **copied})
                _fsync_dir(payload / role)
            elif captures[role] == "directory":
                _copy_directory(source, payload / role, role, manifest, budget)
            else:
                raise BackupRejectedError("unsupported_source_type")
        if all(kind == "absent" for kind in manifest["sources"].values()):
            raise BackupRejectedError("nothing_to_backup")
        manifest["dirs"].sort()
        manifest["files"].sort(key=lambda entry: entry["path"])
        content = _manifest_bytes(manifest)
        _fsync_dir(payload)
        _write_private_file(target / "manifest.json", content)  # Last: commit marker.
        _fsync_dir(target)
        # Read back and verify bytes as a post-commit mechanical check.
        verified = verify_backup(target)
        if not verified["valid"]:
            raise BackupRejectedError("post_write_verification_failed")
        return {"schema": "lfl.backup.create/v1", "created": True,
                "coverage": "selected_roots", "file_count": budget["count"],
                "byte_count": budget["bytes"], "manifest_sha256": hashlib.sha256(content).hexdigest(),
                "services_stopped": "operator_attested_not_verified"}
    except (OSError, ValueError, TypeError) as exc:
        raise BackupRejectedError("snapshot_incomplete_check_target") from exc


def _safe_rel_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BackupRejectedError("unsafe_manifest_path")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or not parsed.parts or any(part in ("", ".", "..") for part in value.split("/")):
        raise BackupRejectedError("unsafe_manifest_path")
    if str(parsed) != value or parsed.parts[0] not in ("config", "data", "experiences", "methods"):
        raise BackupRejectedError("unsafe_manifest_path")
    return value


def _validate_aliases(manifest: dict[str, Any], dirs: set[str], files: set[str]) -> None:
    """Prove logical roots point to a real physical snapshot entry.

    Older v1 snapshots had no aliases and remain readable. Aliases never
    contain host filesystem paths, and do not create new files on recovery.
    """
    sources = manifest["sources"]
    aliases = manifest.get("aliases", {})
    if not isinstance(aliases, dict) or set(aliases) != {
        role for role, kind in sources.items() if kind == "alias"
    }:
        raise BackupRejectedError("invalid_source_aliases")
    for role, kind in sources.items():
        if kind == "absent":
            if role in dirs or any(p == role or p.startswith(role + "/") for p in files):
                raise BackupRejectedError("absent_root_has_payload")
        elif kind == "file":
            if role + "/value" not in files or role not in dirs:
                raise BackupRejectedError("source_file_missing")
        elif kind == "directory":
            if role not in dirs:
                raise BackupRejectedError("source_directory_missing")
        elif kind == "alias":
            if role in dirs or role + "/value" in files:
                raise BackupRejectedError("duplicate_alias_payload")
            spec = aliases[role]
            if not isinstance(spec, dict) or set(spec) != {"under", "relative"}:
                raise BackupRejectedError("invalid_source_alias")
            under = spec["under"]
            relative = spec["relative"]
            if (not isinstance(under, str) or under == role
                    or sources.get(under) != "directory"):
                raise BackupRejectedError("alias_cannot_refer_to_alias_or_missing_root")
            if not isinstance(relative, str):
                raise BackupRejectedError("invalid_alias_relative_path")
            if relative and (
                relative.startswith("/") or "\\" in relative or "\x00" in relative
                or any(part in ("", ".", "..") for part in relative.split("/"))
                or PurePosixPath(relative).as_posix() != relative
            ):
                raise BackupRejectedError("unsafe_alias_relative_path")
            target = under + ("/" + relative if relative else "")
            if (target not in files if role == "config" else target not in dirs):
                raise BackupRejectedError("alias_target_missing_or_wrong_kind")
        else:
            raise BackupRejectedError("invalid_root_kind")


def _snapshot_inventory(snapshot: Path) -> tuple[set[str], set[str]]:
    payload = snapshot / "payload"
    if not payload.is_dir() or payload.is_symlink():
        raise BackupRejectedError("missing_payload")
    dirs: set[str] = set()
    files: set[str] = set()
    for directory, subdirs, names in os.walk(payload, topdown=True, followlinks=False):
        root = Path(directory)
        for name in sorted(subdirs):
            item = root / name
            if item.is_symlink():
                raise BackupRejectedError("symlink_in_snapshot")
            dirs.add(item.relative_to(payload).as_posix())
        for name in names:
            item = root / name
            if item.is_symlink() or not item.is_file():
                raise BackupRejectedError("unexpected_snapshot_file")
            files.add(item.relative_to(payload).as_posix())
    return dirs, files


def _read_manifest(snapshot: Path) -> tuple[dict[str, Any], bytes]:
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise BackupRejectedError("snapshot_missing_or_symlink")
    if stat.S_IMODE(snapshot.stat().st_mode) & 0o077:
        raise BackupRejectedError("nonprivate_snapshot")
    names = {p.name for p in snapshot.iterdir()}
    if names != {"payload", "manifest.json"}:
        raise BackupRejectedError("incomplete_or_extra_snapshot_files")
    if stat.S_IMODE((snapshot / "manifest.json").lstat().st_mode) & 0o077:
        raise BackupRejectedError("nonprivate_manifest")
    if stat.S_IMODE((snapshot / "payload").lstat().st_mode) & 0o077:
        raise BackupRejectedError("nonprivate_payload")
    raw = _read_bytes(snapshot / "manifest.json")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BackupRejectedError("invalid_snapshot_manifest") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("complete") is not True:
        raise BackupRejectedError("incomplete_snapshot")
    if data.get("coverage") != "selected_roots" or not isinstance(data.get("sources"), dict):
        raise BackupRejectedError("wrong_snapshot_scope")
    if set(data["sources"]) != {"config", "data", "experiences", "methods"}:
        raise BackupRejectedError("unexpected_snapshot_roots")
    if any(
        kind not in ({"absent", "file", "alias"} if role == "config"
                     else {"absent", "directory", "alias"})
        for role, kind in data["sources"].items()
    ):
        raise BackupRejectedError("invalid_snapshot_root_kind")
    if not isinstance(data.get("files"), list) or not isinstance(data.get("dirs"), list):
        raise BackupRejectedError("invalid_manifest_inventory")
    return data, raw


def verify_backup(snapshot_raw: str | Path) -> dict[str, Any]:
    """Verify contents and full inventory read-only (not release provenance)."""
    try:
        snapshot = _path(snapshot_raw)
        manifest, raw = _read_manifest(snapshot)
        expected_dirs = [_safe_rel_path(value) for value in manifest["dirs"]]
        expected_files: dict[str, tuple[str, int]] = {}
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise BackupRejectedError("invalid_manifest_entry")
            rel = _safe_rel_path(item.get("path"))
            size = item.get("size")
            digest = item.get("sha256")
            if rel in expected_files or type(size) is not int or not 0 <= size <= _MAX_BYTES:
                raise BackupRejectedError("invalid_manifest_entry")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise BackupRejectedError("invalid_manifest_digest")
            expected_files[rel] = (digest, size)
        if len(expected_dirs) != len(set(expected_dirs)) or len(expected_dirs) > _MAX_FILES:
            raise BackupRejectedError("duplicate_or_excessive_directory")
        if len(expected_files) > _MAX_FILES or sum(size for _, size in expected_files.values()) > _MAX_BYTES:
            raise BackupRejectedError("snapshot_budget_exceeded")
        dirs, files = _snapshot_inventory(snapshot)
        if dirs != set(expected_dirs) or files != set(expected_files):
            raise BackupRejectedError("snapshot_inventory_mismatch")
        _validate_aliases(manifest, dirs, files)
        for rel in dirs:
            if stat.S_IMODE((snapshot / "payload" / rel).stat().st_mode) & 0o077:
                raise BackupRejectedError("nonprivate_snapshot_directory")
        for rel, (digest, size) in expected_files.items():
            file_path = snapshot / "payload" / rel
            fd, before = _opened_file(file_path)
            try:
                if stat.S_IMODE(before.st_mode) & 0o077:
                    raise BackupRejectedError("nonprivate_snapshot_file")
                if before.st_size != size:
                    raise BackupRejectedError("snapshot_file_size_mismatch")
                calculated = hashlib.sha256()
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    while content := stream.read(1024 * 1024):
                        calculated.update(content)
                after = os.fstat(fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns
                ):
                    raise BackupRejectedError("snapshot_changed_during_verify")
                if calculated.hexdigest() != digest:
                    raise BackupRejectedError("snapshot_hash_mismatch")
            finally:
                os.close(fd)
        return {"schema": "lfl.backup.verify/v1", "read_only": True, "valid": True,
                "coverage": "selected_roots", "file_count": len(files),
                "manifest_sha256": hashlib.sha256(raw).hexdigest()}
    except (BackupRejectedError, OSError, ValueError, TypeError, KeyError):
        return {"schema": "lfl.backup.verify/v1", "read_only": True, "valid": False,
                "coverage": "unverified", "file_count": 0}


def restore_to_new_dir(snapshot_raw: str, target_raw: str) -> dict[str, Any]:
    """Recreate a verified snapshot in an unused *staging* dir, never live data."""
    source = _path(snapshot_raw)
    dest = _path(target_raw)
    if dest.exists() or dest.is_symlink():
        raise BackupRejectedError("target_exists")
    if not dest.parent.is_dir() or _is_within(dest, source) or _is_within(source, dest):
        raise BackupRejectedError("unsafe_restore_target")
    preflight = verify_backup(source)
    if not preflight["valid"]:
        raise BackupRejectedError("unverified_snapshot")
    manifest, raw = _read_manifest(source)
    _safe_new_dir(dest)
    try:
        _safe_new_dir(dest / "payload")
        # Inventories were validated above. All source files are read with the
        # same no-follow file/dirfd primitives, and their final hashes are
        # rechecked when the new staging snapshot is verified.
        for role in sorted(manifest["sources"]):
            if manifest["sources"][role] in ("absent", "alias"):
                continue
            _copy_directory(source / "payload" / role, dest / "payload" / role,
                            role, {"dirs": [], "files": []}, {"count": 0, "bytes": 0})
        _fsync_dir(dest / "payload")
        _write_private_file(dest / "manifest.json", raw)
        _fsync_dir(dest)
        if not verify_backup(dest)["valid"]:
            raise BackupRejectedError("recovery_post_verify_failed")
        return {"schema": "lfl.rollback.staging/v1", "restored": True,
                "production_cutover": False, "code_downgrade": False,
                "coverage": "selected_roots", "file_count": len(manifest["files"]),
                "next_steps": ["verify compatibility and trusted prior wheel",
                               "separately authorize service cutover; never overwrite live data"]}
    except (OSError, ValueError, TypeError) as exc:
        raise BackupRejectedError("staging_recovery_incomplete") from exc


def _output(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("LFL 升级/备份（离线）: " + str(payload.get("status") or payload.get("schema")))
        print("结果只包含本地机械事实；软件降级和生产切换均需单独审批。")


def run_upgrade(*, bundle: Path | None, installed_version: str | None, preview: bool, as_json: bool) -> int:
    if not preview:
        print("升级仅支持 --plan，实际 wheel 替换需另行授权。", file=sys.stderr)
        return 2
    _output(upgrade_plan(bundle=bundle, installed_version=installed_version), as_json)
    return 0


def run_backup(*, args: Any, home: Path, bundle: Path | None,
               environment: Mapping[str, str], preview: bool, as_json: bool,
               target: str | None, verify: str | None, confirmed: bool) -> int:
    if verify is not None:
        report = verify_backup(verify)
        _output(report, as_json)
        return 0 if report["valid"] else 1
    if preview:
        try:
            report, _ = backup_plan(args=args, home=home, bundle=bundle, environment=environment)
        except (BackupRejectedError, OSError, ValueError):
            report = {"schema": "lfl.backup.plan/v1", "read_only": True,
                      "write_performed": False, "coverage": "unverified", "status": "blocked"}
        _output(report, as_json)
        return 1 if report.get("status") == "blocked" else 0
    if not target or not confirmed:
        print("冷备份必须指定 --to NEW_DIR --confirm-services-stopped；不会自行停止服务。", file=sys.stderr)
        return 2
    try:
        _, roots = backup_plan(args=args, home=home, bundle=bundle, environment=environment)
        outcome = create_backup(target, roots, bundle=bundle)
        _output(outcome, as_json)
        return 0
    except (BackupRejectedError, OSError, ValueError, TypeError):
        print("冷备份未完成；请检查目标与完整性，不要当作可用快照。", file=sys.stderr)
        return 1


def run_rollback(*, source: str | None, target: str | None, confirmed: bool,
                 as_json: bool) -> int:
    if not source or not target or not confirmed:
        print("隔离恢复必须指定 --from、--into 和 --confirm-services-stopped。", file=sys.stderr)
        return 2
    try:
        outcome = restore_to_new_dir(source, target)
        _output(outcome, as_json)
        return 0
    except (BackupRejectedError, OSError, ValueError, TypeError):
        print("隔离恢复未完成；生产数据未被切换或覆盖。", file=sys.stderr)
        return 1
