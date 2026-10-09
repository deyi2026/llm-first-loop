"""扩展安装记录存储（DESIGN-20261009 §5.3，P1-A）.

文件布局（经 runtime/paths.py 派生的 <data_dir>/extensions）:
    installed.json              权威安装记录（单一事实源）
    packages/<digest>/          包内容不可变副本（同 digest 不重写）
    instances/<install_id>/data/   PLUGIN_DATA（跨更新保留，T21）
    locks/                      并发锁

写路径纪律（§9.1 CAS）:
- 全部变更经 _commit(): 独占锁 → 读 installed.json(rev=N) → expected_revision
  必须等于 N（否则 RevisionConflictError，晚到提交失败）→ 变更 → revision=N+1
- 临时文件 + os.replace 原子替换 + fsync（文件与目录）→ 读回校验；
  读回失败抛 CommitUncertainError（如实报告，不假装成功）
- 记录不含明文 token / 完整 env / Authorization（formats 层已隔离，
  store 再做序列化前敏感键扫描兜底）
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypeVar

from llm_loop.extensions.formats import (
    PACKAGE_UNAVAILABLE,
    parse_plugin_package,
)
from llm_loop.extensions.vendor_formats import (
    FORMAT_STANDARD,
    detect_vendor_format,
    parse_vendor_package,
)

try:
    import fcntl

    _FLOCK_OK = True
except ImportError:  # pragma: no cover - 非 POSIX 平台降级为无锁
    fcntl = None  # type: ignore[assignment]
    _FLOCK_OK = False

_T = TypeVar("_T")

_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "authorization")
_MAX_RECORD_BYTES = 4 * 1024 * 1024  # installed.json 上限（防失控膨胀）


class RevisionConflictError(Exception):
    """CAS 失败：expected_revision 与当前 installed.json revision 不一致."""


class CommitUncertainError(Exception):
    """原子替换后读回校验失败：提交结果不确定，必须重读确认."""


class InstallRejectedError(Exception):
    """安装被拒绝（包不可用/敏感字段等），如实携带原因."""


@dataclass(frozen=True)
class ComponentRecord:
    """安装记录中的组件条目（无 env/headers 明文值）."""

    kind: str  # skill | mcp_server
    name: str
    status: str
    enabled: bool


@dataclass
class InstallRecord:
    install_id: str
    plugin_name: str
    version: str
    source: str
    digest: str
    revision: int  # 创建/最后变更时的 store revision
    components: list[ComponentRecord] = field(default_factory=list)
    scopes: list[str] = field(default_factory=lambda: ["user"])
    created_at: str = ""
    updated_at: str = ""
    # P2-A：来源格式 provenance（标准包 = agent-plugins/1.0.0；厂商包见 vendor_formats）
    source_format: str = "agent-plugins/1.0.0"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["components"] = [asdict(c) for c in self.components]
        return d

    @staticmethod
    def from_dict(d: dict) -> InstallRecord:
        comps = [
            ComponentRecord(
                kind=str(c.get("kind", "")),
                name=str(c.get("name", "")),
                status=str(c.get("status", "")),
                enabled=bool(c.get("enabled", False)),
            )
            for c in d.get("components", [])
            if isinstance(c, dict)
        ]
        return InstallRecord(
            install_id=str(d.get("install_id", "")),
            plugin_name=str(d.get("plugin_name", "")),
            version=str(d.get("version", "")),
            source=str(d.get("source", ""))[:2048],
            digest=str(d.get("digest", "")),
            revision=int(d.get("revision", 0)),
            components=comps,
            scopes=[str(s) for s in d.get("scopes", ["user"])],
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
            source_format=str(d.get("source_format", "agent-plugins/1.0.0")),
        )


@dataclass(frozen=True)
class StoreState:
    revision: int
    installs: tuple[InstallRecord, ...]

    def find(self, install_id: str) -> InstallRecord | None:
        for rec in self.installs:
            if rec.install_id == install_id:
                return rec
        return None


def _install_id_for(plugin_name: str) -> str:
    """install_id 绑定 plugin_name（跨版本稳定 → PLUGIN_DATA 跨更新保留，T21）."""
    slug = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in plugin_name
    ).strip("-")
    if not slug or slug.startswith(".") or ".." in slug:
        raise InstallRejectedError(f"unsafe plugin name: {plugin_name!r}")
    return slug


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S")


def _digest_tree(root: Path) -> str:
    """包内容摘要: 排序相对路径 + 内容 bytes 的规范化 SHA256（跳过符号链接）."""
    h = hashlib.sha256()
    for path in sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    ):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _scan_sensitive(obj, path: str = "") -> str | None:
    """序列化前敏感键扫描（兜底；命中返回说明，拒绝提交）."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            if any(m in key for m in _SENSITIVE_KEY_MARKERS) and v not in ("", None):
                return f"sensitive field at {path}.{k}"
            found = _scan_sensitive(v, f"{path}.{k}")
            if found:
                return found
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found = _scan_sensitive(item, f"{path}[{i}]")
            if found:
                return found
    return None


def _copy_package(src: Path, dst: Path) -> None:
    """复制包内容（仅常规文件/目录；符号链接跳过，保持不可变副本纯净）."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


class ExtensionStore:
    """installed.json 权威记录 + 包副本 + 实例数据目录管理."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.state_file = self.root / "installed.json"
        self.packages_dir = self.root / "packages"
        self.instances_dir = self.root / "instances"
        self.locks_dir = self.root / "locks"
        for d in (self.root, self.packages_dir, self.instances_dir, self.locks_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ── 读路径 ──

    def read_state(self) -> StoreState:
        if not self.state_file.is_file():
            return StoreState(revision=0, installs=())
        try:
            raw = self.state_file.read_text(encoding="utf-8")
            if len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
                raise InstallRejectedError("installed.json exceeds size limit")
            data = json.loads(raw)
            revision = int(data.get("revision", 0))
            installs = tuple(
                InstallRecord.from_dict(d)
                for d in data.get("installs", [])
                if isinstance(d, dict)
            )
            return StoreState(revision=revision, installs=installs)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstallRejectedError(f"installed.json unreadable: {exc}") from exc

    def package_root(self, digest: str) -> Path:
        return self.packages_dir / digest

    def instance_data_dir(self, install_id: str) -> Path:
        return self.instances_dir / install_id / "data"

    # ── 写路径（单一入口 _commit）──

    def _commit(
        self,
        mutator: Callable[[StoreState], tuple[list[InstallRecord], _T]],
        expected_revision: int,
    ) -> tuple[StoreState, _T]:
        """独占锁 + CAS + 原子替换 + 读回校验（§9.1）.

        mutator(state) -> (new_installs, result)；revision 由本函数统一 +1。
        """
        lock_path = self.locks_dir / "extensions.lock"
        with open(lock_path, "a+b") as lock_file:
            if fcntl is not None:  # _FLOCK_OK 等价判断（POSIX import 成功 ⟺ 非 None）
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                state = self.read_state()
                if state.revision != expected_revision:
                    raise RevisionConflictError(
                        f"expected revision {expected_revision} "
                        f"but current is {state.revision}"
                    )
                new_installs, result = mutator(state)
                new_state = {
                    "revision": state.revision + 1,
                    "installs": [r.as_dict() for r in new_installs],
                }
                payload = json.dumps(
                    new_state, ensure_ascii=False, indent=2, sort_keys=True
                )
                leak = _scan_sensitive(new_state)
                if leak:
                    raise InstallRejectedError(
                        f"refusing to persist sensitive field: {leak}"
                    )
                tmp = self.state_file.with_suffix(".json.tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.state_file)
                try:
                    dir_fd = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
                except OSError:
                    pass  # 目录 fsync 尽力而为（平台差异）
                # 读回校验（不确定即如实失败，不假装成功）
                readback = json.loads(self.state_file.read_text(encoding="utf-8"))
                if int(readback.get("revision", -1)) != state.revision + 1:
                    raise CommitUncertainError(
                        "readback revision mismatch after replace"
                    )
                return (
                    StoreState(
                        revision=state.revision + 1,
                        installs=tuple(new_installs),
                    ),
                    result,
                )
            finally:
                if fcntl is not None:  # _FLOCK_OK 等价判断
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    # ── 安装 / 更新 / 启停 ──

    def install(
        self,
        package_root: str | Path,
        *,
        source: str,
        scopes: list[str] | None = None,
        expected_revision: int,
        source_format: str | None = None,
    ) -> InstallRecord:
        """安装（或重装/更新）标准包或厂商包（P2-A）.

        - 先解析 → unavailable 拒绝
        - install_id 绑定 plugin_name（跨版本稳定）→ 同包更新走同一安装，
          instances/<id>/data（PLUGIN_DATA）保留（T21）
        - digest 变化 → 新不可变副本；既有 source 不同 → 身份冲突拒绝（不静默替换）
        - 同 digest 重装 → 记录如实更新（revision +1）
        - source_format：None 时自动嗅探（厂商包走 vendor_formats 转换报告）；
          标准包路径（agent-plugins/1.0.0）行为不变（§11 P2-A 不影响标准加载）
        """
        fmt = source_format or detect_vendor_format(Path(package_root)) or FORMAT_STANDARD
        if fmt == FORMAT_STANDARD:
            report = parse_plugin_package(package_root)
        else:
            report = parse_vendor_package(package_root, source_format=fmt).report
        if report.overall == PACKAGE_UNAVAILABLE:
            raise InstallRejectedError(
                f"package unavailable: {'; '.join(report.warnings) or report.overall}"
            )
        src_root = Path(package_root)
        digest = _digest_tree(src_root)
        install_id = _install_id_for(report.plugin_name)
        scopes = scopes or ["user"]
        now = _now()
        locked_source = source[:2048]

        def mutator(state: StoreState):
            existing = state.find(install_id)
            if (
                existing is not None
                and existing.source
                and existing.source != locked_source
            ):
                raise InstallRejectedError(
                    f"install {install_id} already exists from different "
                    f"source {existing.source!r}; refusing silent replacement"
                )
            components = [
                ComponentRecord(
                    kind="skill",
                    name=s.name,
                    status=s.status,
                    enabled=s.status == "supported",
                )
                for s in report.skills
            ] + [
                ComponentRecord(
                    kind="mcp_server",
                    name=s.name,
                    status=s.status,
                    enabled=s.status == "supported",
                )
                for s in report.servers
            ]
            if existing is not None:
                rec = InstallRecord(
                    install_id=existing.install_id,
                    plugin_name=report.plugin_name,
                    version=report.version,
                    source=source[:2048],
                    digest=digest,
                    revision=state.revision + 1,
                    components=components,
                    scopes=existing.scopes or scopes,
                    created_at=existing.created_at or now,
                    updated_at=now,
                    source_format=fmt,
                )
                installs = [
                    rec if r.install_id == install_id else r
                    for r in state.installs
                ]
                return installs, rec
            rec = InstallRecord(
                install_id=install_id,
                plugin_name=report.plugin_name,
                version=report.version,
                source=source[:2048],
                digest=digest,
                revision=state.revision + 1,
                components=components,
                scopes=scopes,
                created_at=now,
                updated_at=now,
                source_format=fmt,
            )
            installs = [*state.installs, rec]
            return installs, rec

        # 包副本：同 digest 已存在则不重写（不可变）
        dst = self.package_root(digest)
        if not dst.is_dir():
            _copy_package(src_root, dst)
        # PLUGIN_DATA 实例目录（跨更新保留，T21）
        self.instance_data_dir(install_id).mkdir(parents=True, exist_ok=True)
        _, rec = self._commit(mutator, expected_revision)
        return rec

    def set_enabled(
        self,
        install_id: str,
        *,
        enabled: bool,
        component: str | None = None,
        expected_revision: int,
    ) -> InstallRecord:
        """启用/停用整个安装或单个组件."""

        def mutator(state: StoreState):
            existing = state.find(install_id)
            if existing is None:
                raise InstallRejectedError(f"unknown install: {install_id}")
            components = [
                ComponentRecord(
                    kind=c.kind,
                    name=c.name,
                    status=c.status,
                    enabled=enabled
                    if (component is None or c.name == component)
                    else c.enabled,
                )
                for c in existing.components
            ]
            rec = InstallRecord(
                install_id=existing.install_id,
                plugin_name=existing.plugin_name,
                version=existing.version,
                source=existing.source,
                digest=existing.digest,
                revision=state.revision + 1,
                components=components,
                scopes=existing.scopes,
                created_at=existing.created_at,
                updated_at=_now(),
                source_format=existing.source_format,
            )
            installs = [
                rec if r.install_id == install_id else r for r in state.installs
            ]
            return installs, rec

        _, rec = self._commit(mutator, expected_revision)
        return rec

    def uninstall(self, install_id: str, *, expected_revision: int) -> str:
        """移除安装记录（包副本与实例数据保留: 不可变审计 + PLUGIN_DATA 不自动回滚）."""

        def mutator(state: StoreState):
            if state.find(install_id) is None:
                raise InstallRejectedError(f"unknown install: {install_id}")
            installs = [r for r in state.installs if r.install_id != install_id]
            return installs, install_id

        _, removed = self._commit(mutator, expected_revision)
        return removed
