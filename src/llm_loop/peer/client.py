"""控制端 peer 客户端（DESIGN §5.8.5 / §D14）：配对产物 → 四头 HMAC → /peer/v1。

边界（与设计一致，不扩张）：
- 一次调用一个请求，不重试、不 rebind、不做"任务完成"判断；重试由模型显式发起。
- 所有错误映射到封闭 reason_code（``errors.REASON_CODES``），不私造码。
- ``base_url`` 必须是纯 origin（http/https + host[:port]）：带路径/query 直接拒绝。
  canonical 里的 PATH 与服务端 ``request.url.path`` 必须逐字节一致，否则
  "签名对但路由错"是最难查的故障形态。
- ``effect_id`` 由 (run_key, peer_id, kind, params) 确定性派生：模型用同一组参数
  重试得到同一 id，受控端按幂等语义返回原回执；参数改一个字符就是新任务。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from .auth import sign_request
from .errors import PeerError, is_known_reason_code
from .store import NodeRecord, PeerStore

PEER_MANIFEST_PATH = "/peer/v1/manifest"
PEER_TASKS_PATH = "/peer/v1/tasks"
PEER_ARTIFACTS_PATH = "/peer/v1/artifacts"
DEFAULT_TIMEOUT_S = 20

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ARTIFACT_REF_RE = re.compile(r"^artifact://v1/([A-Za-z0-9._-]{8,128})$")


def origin_of(base_url: str) -> str:
    """校验并归一 ``base_url`` 为纯 origin；不合规则是传输层不可用。"""
    raw = str(base_url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise PeerError("peer_transport_unavailable", f"base_url 不是 http(s) origin: {raw!r}")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise PeerError(
            "peer_transport_unavailable",
            f"base_url 必须是纯 origin（不带路径/query）: {raw!r}",
        )
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True)
class PeerEndpoint:
    """已配对节点 + 本机持有的 link_secret。"""

    node_id: str
    base_url: str
    secret: bytes
    display_name: str = ""
    role: str = ""
    state: str = "paired"


class PeerClient:
    """单个对端的签名传输客户端。secret 是本机与对端的共享 link_secret。"""

    def __init__(
        self,
        endpoint: PeerEndpoint,
        *,
        local_node_id: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        clock: Any = time.time,
    ) -> None:
        self._endpoint = endpoint
        self._origin = origin_of(endpoint.base_url)
        self._local_node_id = str(local_node_id or "").strip()
        if not self._local_node_id:
            raise ValueError("local_node_id is required")
        self._timeout_s = max(1, int(timeout_s))
        self._clock = clock

    @property
    def node_id(self) -> str:
        return self._endpoint.node_id

    @property
    def base_url(self) -> str:
        return self._origin

    # ---- 传输 --------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        timeout_s: int | None = None,
    ) -> httpx.Response:
        headers = sign_request(
            secret=self._endpoint.secret,
            method=method,
            path=path,
            node_id=self._local_node_id,
            nonce=uuid.uuid4().hex,
            timestamp=int(self._clock()),
            body=body,
        )
        try:
            return httpx.request(
                method,
                self._origin + path,
                headers=headers,
                content=body,
                timeout=httpx.Timeout(max(1, int(timeout_s or self._timeout_s))),
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:  # 连接失败/超时/协议错都归传输不可用
            raise PeerError(
                "peer_transport_unavailable", f"{type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _error_from(response: httpx.Response) -> PeerError:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - 非 JSON 错误体只回状态码
            payload = None
        code = payload.get("reason_code") if isinstance(payload, dict) else None
        detail = payload.get("detail") if isinstance(payload, dict) else ""
        if isinstance(code, str) and is_known_reason_code(code):
            return PeerError(code, str(detail or ""))
        return PeerError("peer_transport_unavailable", f"HTTP {response.status_code}")

    @staticmethod
    def _as_json(response: httpx.Response) -> dict[str, Any]:
        if not 200 <= response.status_code < 300:
            raise PeerClient._error_from(response)
        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise PeerError(
                "peer_transport_unavailable", f"HTTP {response.status_code} 响应不是 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise PeerError("peer_transport_unavailable", "响应 JSON 不是对象")
        return payload

    # ---- 四个端点 ----------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        return self._as_json(self._request("GET", PEER_MANIFEST_PATH))

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        deadline = int(payload.get("deadline_s") or 30)
        return self._as_json(
            self._request("POST", PEER_TASKS_PATH, body=body, timeout_s=deadline + 5)
        )

    def receipt(self, task_id: str) -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not _TASK_ID_RE.match(task_id):
            raise PeerError("params_schema_invalid", f"bad task_id: {task_id!r}")
        return self._as_json(self._request("GET", f"{PEER_TASKS_PATH}/{task_id}/receipt"))

    def artifact(self, ref: str) -> tuple[bytes, str, str | None]:
        """取产物字节；返回 (bytes, sha256, media_type)。sha256 重算不符即 fail-closed。"""
        match = _ARTIFACT_REF_RE.match(str(ref or ""))
        if not match:
            raise PeerError("params_schema_invalid", f"bad artifact ref: {ref!r}")
        digest = match.group(1)
        response = self._request("GET", f"{PEER_ARTIFACTS_PATH}/v1/{digest}")
        if not 200 <= response.status_code < 300:
            raise self._error_from(response)
        data = response.content
        if hashlib.sha256(data).hexdigest() != digest:
            raise PeerError(
                "artifact_digest_mismatch", f"{ref} 内容 sha256 与 ref 不符（{len(data)} bytes）"
            )
        media_type = response.headers.get("content-type") or None
        return data, digest, media_type


class PeerDirectory:
    """把 ``data/peer`` 的配对产物翻译成可调用客户端；不缓存远端状态。"""

    def __init__(
        self,
        store: PeerStore,
        *,
        local_node_id: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._store = store
        self._local_node_id = str(local_node_id or "").strip()
        self._timeout_s = max(1, int(timeout_s))

    def _endpoint(self, node: NodeRecord) -> PeerEndpoint | None:
        stored = self._store.read_secret(node.node_id)
        if not stored:
            return None
        from .pair import secret_key_from_store

        try:
            secret = secret_key_from_store(stored)
        except (PeerError, ValueError):
            return None
        return PeerEndpoint(
            node_id=node.node_id,
            base_url=node.base_url,
            secret=secret,
            display_name=node.display_name or "",
            role=node.role or "",
            state=node.state,
        )

    def clients(self) -> list[PeerClient]:
        result: list[PeerClient] = []
        for node in self._store.list_nodes():
            if node.state != "paired":
                continue
            endpoint = self._endpoint(node)
            if endpoint is None:
                continue
            try:
                result.append(
                    PeerClient(
                        endpoint,
                        local_node_id=self._local_node_id,
                        timeout_s=self._timeout_s,
                    )
                )
            except ValueError:
                continue
        return result

    def resolve(self, peer_id: str) -> PeerClient:
        peer_id = str(peer_id or "").strip()
        node = self._store.get_node(peer_id) if peer_id else None
        if node is None:
            raise PeerError("peer_unknown_node", peer_id or "<empty>")
        if node.state != "paired":
            raise PeerError("peer_not_paired", f"{peer_id} state={node.state}")
        endpoint = self._endpoint(node)
        if endpoint is None:
            raise PeerError("peer_not_paired", f"{peer_id} 缺本地 shared secret")
        return PeerClient(
            endpoint, local_node_id=self._local_node_id, timeout_s=self._timeout_s
        )

    def observe(self) -> list[dict[str, Any]]:
        """peer_list 的事实面：静态配对信息 + 远端 manifest（拿不到就标 unreachable）。"""
        rows: list[dict[str, Any]] = []
        for node in self._store.list_nodes():
            base: dict[str, Any] = {
                "peer_id": node.node_id,
                "display_name": node.display_name or node.node_id,
                "role": node.role or "",
                "base_url": node.base_url,
                "state": node.state,
            }
            if node.state != "paired":
                rows.append({**base, "health": "unavailable", "reason_code": "peer_not_paired"})
                continue
            endpoint = self._endpoint(node)
            if endpoint is None:
                rows.append({**base, "health": "unavailable", "reason_code": "peer_not_paired"})
                continue
            try:
                client = PeerClient(
                    endpoint, local_node_id=self._local_node_id, timeout_s=self._timeout_s
                )
                manifest = client.manifest()
            except PeerError as exc:
                rows.append({**base, "health": "unreachable", "reason_code": exc.reason_code})
                continue
            except ValueError as exc:
                rows.append(
                    {**base, "health": "unreachable", "reason_code": "peer_transport_unavailable",
                     "detail": str(exc)}
                )
                continue
            row = {
                **base,
                "health": str(manifest.get("health") or "unknown"),
                "display_protocol": manifest.get("display_protocol") or "none",
                "kinds": list(manifest.get("kinds") or []),
                "limits": manifest.get("limits") or {},
                "grant": manifest.get("grant"),
                "observed_at": manifest.get("observed_at"),
            }
            if manifest.get("display_name"):
                row["display_name"] = str(manifest["display_name"])
            rows.append(row)
        return rows


def effect_id_for(*, run_key: str, peer_id: str, kind: str, params: dict[str, Any]) -> str:
    """确定性 effect_id：同一 run 内同一 (peer, kind, params) 恒等。"""
    canonical = json.dumps(
        {"kind": kind, "params": params, "peer_id": peer_id},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(f"{run_key}\n{canonical}".encode()).hexdigest()
    return "eff_" + digest[:40]
