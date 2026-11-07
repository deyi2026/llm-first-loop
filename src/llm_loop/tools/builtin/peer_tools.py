"""控制端四工具（DESIGN §5.8.5 / §D14）：peer_list / peer_dispatch / peer_task / peer_fetch。

何时用：把动作发到另一台已配对的 LFL 节点（受控端），或取回它产生的回执/产物。
何时不用：目标在本机（用原生工具）；只读本机文件（用 read_file）。
失败对策：工具只回传封闭 reason_code + 建议，不自动重试；是否重试由模型判断。
重试同一 (peer, kind, params) 会得到同一 effect_id，受控端按幂等语义返回原回执。

写侧边界：peer_fetch 默认落到本机 peer 缓存 ``<peer_data_dir>/inbox``（不属于用户
工作区）；只有显式给 ``to_path`` 时才写用户指定位置，且必须先过 ``current_write_scope``。
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import (
    current_run_generation,
    current_session_id,
    current_write_scope,
)
from llm_loop.core.write_scope import scope_allows
from llm_loop.peer.client import DEFAULT_TIMEOUT_S, PeerDirectory, effect_id_for
from llm_loop.peer.errors import PeerError
from llm_loop.peer.store import PeerStore
from llm_loop.peer.suggestions import REASON_SUGGESTIONS

_EXPECT_VALUES = ("summary", "artifact", "file_effect")
_NODE_ID_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


def default_node_id() -> str:
    """未显式配置时的本机节点 id：稳定、可读、满足协议字符面。"""
    raw = (socket.gethostname() or "").strip().lower()
    cleaned = _NODE_ID_CLEAN_RE.sub("-", raw).strip("-")[:63]
    return f"lfl-{cleaned or 'node'}"


class PeerToolRuntime:
    """四工具共享的静态依赖：settings → PeerStore/PeerDirectory（惰性，一次构造）。"""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._directory: PeerDirectory | None = None

    def node_id(self) -> str:
        configured = str(getattr(self._settings, "peer_node_id", "") or "").strip()
        return configured or default_node_id()

    def data_dir(self) -> Path:
        configured = str(getattr(self._settings, "peer_data_dir", "") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        base = str(getattr(self._settings, "data_dir", "") or "").strip()
        root = Path(base).expanduser() if base else Path.cwd()
        return (root / "peer").resolve()

    def workspace_root(self) -> str:
        extra = getattr(self._settings, "_extra", {}) or {}
        runtime_root = str(extra.get("runtime_root") or "").strip()
        return runtime_root or str(Path.cwd())

    def directory(self) -> PeerDirectory:
        with self._lock:
            if self._directory is None:
                timeout_s = int(
                    getattr(self._settings, "peer_timeout_s", DEFAULT_TIMEOUT_S)
                    or DEFAULT_TIMEOUT_S
                )
                self._directory = PeerDirectory(
                    PeerStore(self.data_dir()),
                    local_node_id=self.node_id(),
                    timeout_s=timeout_s,
                )
            return self._directory


def _failure(tool_name: str, code: str, detail: str = "") -> ToolResult:
    text = f"[{code}] {detail}".strip()
    suggestion = REASON_SUGGESTIONS.get(code)
    if suggestion:
        text = f"{text}\n建议: {suggestion}"
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=text,
        tool_call_id="",
        tool_name=tool_name,
    )


def _success(tool_name: str, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        tool_call_id="",
        tool_name=tool_name,
    )


def _dispatch_with(tool_name: str, fn: Callable[[], ToolResult]) -> ToolResult:
    try:
        return fn()
    except PeerError as exc:
        return _failure(tool_name, exc.reason_code, exc.detail)
    except Exception as exc:  # noqa: BLE001 - 程序缺陷如实报 error，不伪装成业务失败
        return ToolResult(
            status=ToolResultStatus.ERROR,
            content=f"[tool_error] {type(exc).__name__}: {exc}",
            tool_call_id="",
            tool_name=tool_name,
        )


class PeerListTool:
    name = "peer_list"
    description = (
        "枚举本机已配对的 peer 节点，并逐个取远端 manifest（kinds/limits/grant/health）。"
        "何时用: 派单前确认目标节点在线、可执行哪些 kind、有无 grant。"
        "何时不用: 已知节点且 peer_dispatch 已能成功。"
        "失败对策: 返回 unreachable/peer_not_paired 的节点不可派单；不要重试同一调用。"
        "返回: JSON {local_node_id, peers[]}，peers[].kinds 是 peer_dispatch 的 kind 白名单。"
    )
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, runtime: PeerToolRuntime) -> None:
        self._runtime = runtime

    def execute(self, **kwargs: Any) -> ToolResult:
        def _run() -> ToolResult:
            peers = self._runtime.directory().observe()
            return _success(
                self.name, {"local_node_id": self._runtime.node_id(), "peers": peers}
            )

        return _dispatch_with(self.name, _run)


class PeerDispatchTool:
    name = "peer_dispatch"
    description = (
        "向已配对 peer 提交一个受控端任务（kind 白名单由远端 manifest 决定），返回 receipt。"
        "何时用: 要在另一台节点执行动作并拿到受控回执。"
        "何时不用: 目标在本机；或只是想看已有任务（用 peer_task）。"
        "失败对策: kind 不在 kinds 内会被本地前置校验拒绝；params 不合 schema 由远端拒绝。"
        "同一组参数重试会复用同一 effect_id；改参数即新任务。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "peer_id": {"type": "string", "description": "目标节点 id（来自 peer_list）"},
            "kind": {
                "type": "string",
                "description": "任务 kind；必须是 peer_list 返回的该节点 kinds 之一（远端协议层同样校验）",
            },
            "params": {
                "type": "object",
                "description": "该 kind 的参数对象，形状由远端 manifest 的 params_schema_hint 决定",
            },
            "expect": {
                "type": "array",
                "items": {"type": "string", "enum": list(_EXPECT_VALUES)},
                "description": "期望产物类型（可选）；缺省 summary",
            },
            "deadline_s": {
                "type": "integer",
                "minimum": 5,
                "maximum": 3600,
                "description": "远端执行超时（秒），缺省 30",
            },
        },
        "required": ["peer_id", "kind", "params"],
    }

    def __init__(self, runtime: PeerToolRuntime) -> None:
        self._runtime = runtime

    def execute(self, **kwargs: Any) -> ToolResult:
        def _run() -> ToolResult:
            peer_id = str(kwargs.get("peer_id") or "").strip()
            kind = str(kwargs.get("kind") or "").strip()
            params = kwargs.get("params")
            expect = kwargs.get("expect") or []
            deadline_raw = kwargs.get("deadline_s", 30)
            if not peer_id or not kind:
                return _failure(self.name, "params_schema_invalid", "peer_id/kind 不能为空")
            if not isinstance(params, dict):
                return _failure(self.name, "params_schema_invalid", "params 必须是对象")
            if not isinstance(expect, list) or any(
                str(item) not in _EXPECT_VALUES for item in expect
            ):
                return _failure(
                    self.name, "params_schema_invalid", f"expect 只接受 {_EXPECT_VALUES}"
                )
            try:
                deadline = int(deadline_raw)
            except (TypeError, ValueError):
                return _failure(self.name, "params_schema_invalid", "deadline_s 必须是整数")
            if not 5 <= deadline <= 3600:
                return _failure(self.name, "params_schema_invalid", "deadline_s 必须在 5..3600")

            client = self._runtime.directory().resolve(peer_id)
            manifest = client.manifest()
            # manifest.kinds 是 KindSpec 对象列表（{kind, idempotency_class, ...}），
            # 不是字符串列表；这里提取 kind 名用于白名单校验。
            kinds = [
                str(item.get("kind") if isinstance(item, dict) else item)
                for item in (manifest.get("kinds") or [])
            ]
            if kind not in kinds:
                raise PeerError(
                    "policy_task_kind_not_allowed",
                    f"{kind!r} 不在 {peer_id} 的 kinds 内: {kinds}",
                )
            run_key = (
                f"{current_session_id.get() or 'nosession'}:"
                f"{current_run_generation.get() or 0}"
            )
            effect_id = effect_id_for(
                run_key=run_key, peer_id=peer_id, kind=kind, params=params
            )
            receipt = client.submit(
                {
                    "schema": "lfl.peer.v1",
                    "effect_id": effect_id,
                    "kind": kind,
                    "params": params,
                    "expect": [str(item) for item in expect],
                    "deadline_s": deadline,
                    "requested_by": self._runtime.node_id(),
                }
            )
            return _success(
                self.name,
                {
                    "peer_id": peer_id,
                    "kind": kind,
                    "effect_id": effect_id,
                    "receipt": receipt,
                },
            )

        return _dispatch_with(self.name, _run)


class PeerTaskTool:
    name = "peer_task"
    description = (
        "查询已提交任务的回执（durable 状态；受控端程序终态不被重新裁决）。"
        "何时用: 拿到 task_id 后轮询结果、核对 failed/超时原因。"
        "何时不用: 还没提交任务（先 peer_dispatch）；要取产物字节（用 peer_fetch）。"
        "失败对策: task_not_found 时核对 task_id；不要用本工具发起新任务。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "peer_id": {"type": "string", "description": "目标节点 id（来自 peer_list）"},
            "task_id": {"type": "string", "description": "peer_dispatch 回执里的 task_id"},
        },
        "required": ["peer_id", "task_id"],
    }

    def __init__(self, runtime: PeerToolRuntime) -> None:
        self._runtime = runtime

    def execute(self, **kwargs: Any) -> ToolResult:
        def _run() -> ToolResult:
            peer_id = str(kwargs.get("peer_id") or "").strip()
            task_id = str(kwargs.get("task_id") or "").strip()
            if not peer_id or not task_id:
                return _failure(self.name, "params_schema_invalid", "peer_id/task_id 不能为空")
            client = self._runtime.directory().resolve(peer_id)
            receipt = client.receipt(task_id)
            return _success(
                self.name, {"peer_id": peer_id, "task_id": task_id, "receipt": receipt}
            )

        return _dispatch_with(self.name, _run)


class PeerFetchTool:
    name = "peer_fetch"
    description = (
        "取回远端任务的产物字节并校验 sha256；默认落到本机 peer 缓存，给 to_path 才写工作区。"
        "何时用: receipt 里有 artifact(ref) 且需要本地内容。"
        "何时不用: 只需要回执摘要（用 peer_task）。"
        "失败对策: artifact_digest_mismatch 视为失败产物不要用；"
        "path_outside_allowed_paths 时换授权范围内路径，不得请求扩大范围。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "peer_id": {"type": "string", "description": "目标节点 id（来自 peer_list）"},
            "ref": {
                "type": "string",
                "description": "产物引用，形如 artifact://v1/<sha256>（来自 receipt）",
            },
            "to_path": {
                "type": "string",
                "description": "可选：写入本机工作区的目标路径（受写侧授权约束）；缺省落 peer 缓存",
            },
        },
        "required": ["peer_id", "ref"],
    }

    def __init__(self, runtime: PeerToolRuntime) -> None:
        self._runtime = runtime

    def _resolve_target(self, to_path: str) -> Path:
        root = Path(self._runtime.workspace_root()).expanduser()
        candidate = Path(to_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve()

    def execute(self, **kwargs: Any) -> ToolResult:
        def _run() -> ToolResult:
            peer_id = str(kwargs.get("peer_id") or "").strip()
            ref = str(kwargs.get("ref") or "").strip()
            to_path = str(kwargs.get("to_path") or "").strip()
            if not peer_id or not ref:
                return _failure(self.name, "params_schema_invalid", "peer_id/ref 不能为空")
            client = self._runtime.directory().resolve(peer_id)
            data, digest, media_type = client.artifact(ref)
            if to_path:
                target = self._resolve_target(to_path)
                allowed, reason = scope_allows(
                    current_write_scope.get(),
                    str(target),
                    self._runtime.workspace_root(),
                )
                if not allowed:
                    raise PeerError(
                        "path_outside_allowed_paths",
                        f"{target} 被写侧授权拒绝（{reason}）",
                    )
            else:
                inbox = self._runtime.data_dir() / "inbox"
                inbox.mkdir(parents=True, exist_ok=True)
                target = inbox / digest
            _atomic_write(target, data)
            return _success(
                self.name,
                {
                    "peer_id": peer_id,
                    "ref": ref,
                    "sha256": digest,
                    "bytes": len(data),
                    "media_type": media_type,
                    "local_path": str(target),
                },
            )

        return _dispatch_with(self.name, _run)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    os.chmod(path, 0o644)


def build_peer_tools(settings: Any) -> dict[str, Any]:
    """构造四工具实例（仅在 peer_enabled 时由 factory 调用）。"""
    runtime = PeerToolRuntime(settings)
    return {
        "peer_list": PeerListTool(runtime),
        "peer_dispatch": PeerDispatchTool(runtime),
        "peer_task": PeerTaskTool(runtime),
        "peer_fetch": PeerFetchTool(runtime),
    }
