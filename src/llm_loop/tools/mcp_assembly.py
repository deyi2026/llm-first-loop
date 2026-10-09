"""MCP 装配（P1-C）：配置合并优先级 + 精确身份冲突报告 + 装配 epoch 基线.

设计 §4.2：迁移优先级 用户/工作区显式覆盖 → 固定安装实例 → legacy 配置
（MCP_SERVERS）；同一精确身份冲突必须报告，不静默叠加；覆盖不隐式扩大
授权；保留每个 effective 字段的 provenance。

层次实现（当前权威源）：
- installed@workspace：扩展安装实例（store 记录 scopes 含 workspace）
- installed@user：扩展安装实例（user 作用域）
- legacy:MCP_SERVERS：旧环境变量配置（列表 JSON）

身份语义：精确身份 = (name, transport, 端点规范形)——http 为
scheme://netloc/path；stdio 为 command+argv。同名不同端点同样不得叠加
（注册名 mcp_<name>_<tool> 会碰撞），按优先级取一并报告。

装配 epoch：assemble_mcp_tools 完成后记录 catalog_epoch() 基线；
后续任何目录变化（list_changed/刷新/注册/清理）都会推进 catalog_epoch，
上层以 mcp_catalog_changed_since_assembly() 判定装配失效。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from llm_loop.tools.mcp_client import (
    catalog_epoch,
    parse_servers,
    register_mcp_tools,
)

logger = logging.getLogger(__name__)

LAYER_WORKSPACE = "installed@workspace"
LAYER_USER = "installed@user"
LAYER_LEGACY = "legacy:MCP_SERVERS"
_LAYER_RANK = {LAYER_WORKSPACE: 2, LAYER_USER: 1, LAYER_LEGACY: 0}

_MCP_FILE = "mcp.json"


@dataclass
class LayeredServer:
    """单层单服务器候选（entry = register_mcp_tools 兼容条目）."""

    entry: dict[str, Any]
    name: str
    layer: str
    install_id: str | None = None
    identity: str = ""
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class IdentityConflict:
    """同一名字（含同一精确身份）多层出现：只生效最高优先层并报告."""

    name: str
    identity: str  # 精确身份；同名不同端点时为 "<name-conflict>"
    winner_layer: str
    loser_layers: list[str] = field(default_factory=list)


@dataclass
class AssemblyPlan:
    raw: str  # register_mcp_tools 直接消费（列表 JSON）
    servers: list[LayeredServer] = field(default_factory=list)
    conflicts: list[IdentityConflict] = field(default_factory=list)


_ASSEMBLY_LOCK = threading.Lock()
_ASSEMBLY_EPOCH: int | None = None


def assembly_catalog_epoch() -> int | None:
    """最近一次装配完成后的目录 epoch 基线（None = 尚未装配）."""
    with _ASSEMBLY_LOCK:
        return _ASSEMBLY_EPOCH


def mcp_catalog_changed_since_assembly() -> bool:
    """装配失效判定：装配后目录是否已变化（epoch 单调递增）."""
    with _ASSEMBLY_LOCK:
        baseline = _ASSEMBLY_EPOCH
    if baseline is None:
        return False
    return catalog_epoch() > baseline


def _reset_assembly_state_for_tests() -> None:
    global _ASSEMBLY_EPOCH
    with _ASSEMBLY_LOCK:
        _ASSEMBLY_EPOCH = None


def _identity(entry: dict[str, Any]) -> str:
    """精确身份：transport + 端点规范形（http 路径去尾斜杠；stdio argv 全列）."""
    if entry.get("type") == "http":
        parts = urlsplit(str(entry.get("url") or ""))
        return f"http|{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"
    argv = [str(entry.get("command") or "")] + [str(a) for a in entry.get("args") or []]
    return "stdio|" + " ".join(argv)


def _provenance(entry: dict[str, Any], layer: str) -> dict[str, str]:
    """每个 effective 字段的来源层（整条目取胜，无字段级混并）."""
    return {key: layer for key in entry}


def _expand_standard_vars(value: str, pkg_root: Path, data_dir: Path) -> str:
    """标准保留变量（宿主提供）：${PLUGIN_ROOT}/${PLUGIN_DATA}（§5.1）.

    不做 shell 求值、不展开 command/URL/headers 之外的私有变量。
    """
    return (
        str(value).replace("${PLUGIN_ROOT}", str(pkg_root)).replace("${PLUGIN_DATA}", str(data_dir))
    )


def _normalize_package_entry(
    name: str,
    raw_entry: dict[str, Any],
    pkg_root: Path,
    data_dir: Path,
) -> dict[str, Any] | None:
    """包 mcpServers 条目 → register 兼容条目（未知/缺配置返回 None 隔离）."""
    server_type = str(raw_entry.get("type", "") or "").strip()
    if server_type == "http":
        url = str(raw_entry.get("url") or "").strip()
        if not url:
            logger.warning("MCP 包服务器 %s http 缺 url，隔离跳过", name)
            return None
        entry: dict[str, Any] = {"name": name, "type": "http", "url": url}
        raw_headers = raw_entry.get("headers")
        if isinstance(raw_headers, dict) and raw_headers:
            entry["headers"] = {str(k): str(v) for k, v in raw_headers.items()}
        credential_ref = raw_entry.get("credential_ref")
        if isinstance(credential_ref, str) and credential_ref.strip():
            entry["credential_ref"] = credential_ref.strip()
        return entry
    if server_type == "stdio":
        command = raw_entry.get("command")
        if not isinstance(command, str) or not command.strip():
            logger.warning("MCP 包服务器 %s stdio 缺 command，隔离跳过", name)
            return None
        entry = {
            "name": name,
            "type": "stdio",
            "command": _expand_standard_vars(command, pkg_root, data_dir),
        }
        raw_args = raw_entry.get("args")
        if isinstance(raw_args, list):
            entry["args"] = [_expand_standard_vars(str(a), pkg_root, data_dir) for a in raw_args]
        raw_env = raw_entry.get("env")
        if isinstance(raw_env, dict) and raw_env:
            entry["env"] = {
                str(k): _expand_standard_vars(str(v), pkg_root, data_dir)
                for k, v in raw_env.items()
            }
        credential_ref = raw_entry.get("credential_ref")
        if isinstance(credential_ref, str) and credential_ref.strip():
            entry["credential_ref"] = credential_ref.strip()
        return entry
    logger.warning("MCP 包服务器 %s 未知 transport %r，隔离跳过", name, server_type)
    return None


def _installed_servers(store: Any) -> list[LayeredServer]:
    """固定安装实例层：store 记录（enabled 组件）× 包副本 mcp.json 全量配置."""
    out: list[LayeredServer] = []
    state = store.read_state()
    for rec in state.installs:
        layer = LAYER_WORKSPACE if "workspace" in rec.scopes else LAYER_USER
        pkg_root = store.package_root(rec.digest)
        data_dir = store.instance_data_dir(rec.install_id)
        mcp_file = pkg_root / _MCP_FILE
        try:
            data = json.loads(mcp_file.read_text(encoding="utf-8"))
            servers = data.get("mcpServers")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "MCP 安装 %s（%s）mcp.json 不可读，按包隔离跳过: %s",
                rec.install_id,
                rec.plugin_name,
                exc,
            )
            continue
        if not isinstance(servers, dict):
            continue
        for comp in rec.components:
            if comp.kind != "mcp_server" or not comp.enabled:
                continue
            raw_entry = servers.get(comp.name)
            if not isinstance(raw_entry, dict):
                logger.warning(
                    "MCP 组件 %s（%s）在包 mcp.json 中无对应条目，隔离跳过",
                    comp.name,
                    rec.install_id,
                )
                continue
            entry = _normalize_package_entry(comp.name, raw_entry, pkg_root, data_dir)
            if entry is None:
                continue
            out.append(
                LayeredServer(
                    entry=entry,
                    name=comp.name,
                    layer=layer,
                    install_id=rec.install_id,
                    identity=_identity(entry),
                    provenance=_provenance(entry, layer),
                )
            )
    return out


def _legacy_servers(legacy_raw: str) -> list[LayeredServer]:
    """legacy 层：MCP_SERVERS 列表 JSON（parse_servers 规范化；含 disabled 条目）."""
    out: list[LayeredServer] = []
    for spec in parse_servers(legacy_raw):
        entry: dict[str, Any] = {"name": spec.name, "type": spec.type, "enabled": spec.enabled}
        if spec.type == "http":
            entry["url"] = spec.url
            if spec.headers:
                entry["headers"] = dict(spec.headers)
        else:
            entry["command"] = spec.command
            if spec.args:
                entry["args"] = list(spec.args)
            if spec.env:
                entry["env"] = dict(spec.env)
        if spec.credential_ref:
            entry["credential_ref"] = spec.credential_ref
        out.append(
            LayeredServer(
                entry=entry,
                name=spec.name,
                layer=LAYER_LEGACY,
                install_id=None,
                identity=_identity(entry),
                provenance=_provenance(entry, LAYER_LEGACY),
            )
        )
    return out


def effective_mcp_servers(store: Any = None, legacy_raw: str = "") -> AssemblyPlan:
    """合并三层候选：同名（含同精确身份）只生效最高优先层，其余报告不叠加."""
    candidates: list[LayeredServer] = []
    if store is not None:
        try:
            candidates.extend(_installed_servers(store))
        except Exception:  # noqa: BLE001 — store 读失败降级为 legacy-only（fail-open）
            logger.warning("MCP 安装层读取失败，仅用 legacy 配置", exc_info=True)
    candidates.extend(_legacy_servers(legacy_raw))

    by_name: dict[str, list[LayeredServer]] = {}
    for candidate in candidates:
        by_name.setdefault(candidate.name, []).append(candidate)

    conflicts: list[IdentityConflict] = []
    effective: list[LayeredServer] = []
    for name in sorted(by_name):
        layered = sorted(by_name[name], key=lambda s: _LAYER_RANK[s.layer], reverse=True)
        winner = layered[0]
        if len(layered) > 1:
            identities = {s.identity for s in layered}
            conflicts.append(
                IdentityConflict(
                    name=name,
                    identity=winner.identity if len(identities) == 1 else "<name-conflict>",
                    winner_layer=winner.layer,
                    loser_layers=[s.layer for s in layered[1:]],
                )
            )
        effective.append(winner)

    raw = json.dumps([s.entry for s in effective], ensure_ascii=False)
    return AssemblyPlan(raw=raw, servers=effective, conflicts=conflicts)


def assemble_mcp_tools(registry: Any, store: Any = None, legacy_raw: str = "") -> list[str]:
    """装配入口：合并 → 注册 → 冲突报告 → 记录装配 epoch 基线."""
    global _ASSEMBLY_EPOCH
    plan = effective_mcp_servers(store, legacy_raw)
    for conflict in plan.conflicts:
        logger.warning(
            "MCP 配置身份冲突（server=%s，identity=%s）：生效 %s，覆盖 %s（不叠加）",
            conflict.name,
            conflict.identity[:160],
            conflict.winner_layer,
            ", ".join(conflict.loser_layers),
        )
    registered = register_mcp_tools(registry, plan.raw)
    with _ASSEMBLY_LOCK:
        _ASSEMBLY_EPOCH = catalog_epoch()
    logger.info(
        "MCP 装配完成：%d 台生效服务器，%d 项冲突报告，装配 epoch=%s",
        len(plan.servers),
        len(plan.conflicts),
        _ASSEMBLY_EPOCH,
    )
    return registered
