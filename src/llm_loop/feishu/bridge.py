"""飞书 WS 长连接桥（M42，薄壳适配器，借鉴 本地既有实现 ws_bridge.py 算法思路）.

事件注册 im.message.receive_v1 → 去重 → 消息处理 → 回复原会话。
启用条件：凭证已配置 且 FEISHU_WS_ENABLED != "0"。凭证预检、指数退避重连、生命周期。
_WsConnector 封装 websockets 可注入 Mock（测试零真实 WS 连接）。
"""

import json
import logging
import re
import threading
from collections import deque
from collections.abc import Callable
from time import sleep as _sleep
from typing import Any

import httpx
import lark_oapi

from llm_loop.feishu.config import FeishuConfig
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.rest import FeishuRestClient, FeishuRestError, _mask_id

logger = logging.getLogger(__name__)

_MAX_DEDUP_IDS = 500
_RECONNECT_BASE_S = 5
_RECONNECT_MAX_S = 30
_RECONNECT_MAX_ATTEMPTS = 5
_RECONNECT_LONG_BACKOFF_S = 300
_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"  # 探针端点（M44：token 生命周期交 SDK，仅预检用）


class _WsConnector:
    """飞书 WS 长连接（lark-oapi ws.Client 包装，FR-RW-WS-01~06）.

    路径 B' 修正（用户拍板 2026-08-11）：SDK 实测协议为 protobuf 帧 + 自定义握手，
    远超自实现假设 → 改用 lark-oapi ws.Client（官方维护、实测可靠）。
    token 检查（无缓存等待零触网，保 Mock 面）→ ws.Client.start（SDK 内部完成
    endpoint/连接/心跳/重连/收帧）；事件经 EventDispatcherHandler 注册
    im.message.receive_v1 → 序列化回 payload dict → on_message 分发（既有链路零改动）。
    """

    def __init__(
        self,
        config: FeishuConfig,
        on_message: Callable[[dict], None],
        has_token: Callable[[], bool],
        rest_client: FeishuRestClient | None = None,
        *,
        ws_client_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        self._on_message = on_message
        self._has_token = has_token
        self._rest = rest_client
        self._ws_client_factory = ws_client_factory or self._default_ws_client
        self._sleep = sleep or _sleep
        self._stop = False

    def _default_ws_client(self, event_handler):
        """默认 lark ws.Client（官方长连接；Mock 测试注入替代）."""
        import lark_oapi as lark

        return lark.ws.Client(
            self._config.app_id,
            self._config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.WARNING,
        )

    def _build_event_handler(self):
        """构造 lark 事件分发器：im.message.receive_v1 → _handle_event."""
        import lark_oapi as lark

        return (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_event)
            .build()
        )

    def _handle_event(self, data, ctx=None) -> None:
        """lark 事件对象 → payload dict → on_message 分发（回调异常如实记录不中断）."""
        try:
            import json

            import lark_oapi as lark

            raw = lark.JSON.marshal(data)
            if isinstance(raw, dict):
                self._on_message(raw)
                return
            payload = json.loads(raw or "{}")
            if isinstance(payload, dict):
                self._on_message(payload)
        except Exception as exc:  # noqa: BLE001 — 回调异常如实记录不中断连接
            logger.exception("飞书事件回调处理异常: %s", exc)

    def stop(self) -> None:
        """停止（lark ws.Client 无公开 stop API；daemon 线程 + 进程退出兜底）."""
        self._stop = True

    def run(self) -> None:
        """长连接主循环（token 未就绪等待零触网；就绪后 lark ws.Client.start 阻塞）."""
        if not self._has_token():
            logger.warning(
                "飞书 WS 连接未启动：tenant_access_token 未就绪（预检未获取），进入等待（零触网）"
            )
            while not self._stop:
                self._sleep(1)
            return
        client = self._ws_client_factory(self._build_event_handler())
        # SDK 内部完成 endpoint/连接/心跳/重连/收帧（阻塞；断线 SDK 自动重连）
        client.start()


class FeishuWsBridge:
    """飞书 WS 桥：事件注册/去重/预检/重连/生命周期（薄壳）."""

    def __init__(
        self,
        config: FeishuConfig,
        handler: FeishuMessageHandler | None = None,
        lark_client: lark_oapi.Client | None = None,
    ) -> None:
        self._config = config
        self._handler = handler
        self._lark_client = lark_client
        self._connector: _WsConnector | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._ws_state = "disconnected"
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()  # 到达序（裁剪最旧用，保证窗口有序有界）
        self._dedup_lock = threading.Lock()
        # token 生命周期交 lark.Client（M44，FR-SDK-TKN-01：feishu 层零 token 值接触）
        self._token_ready: bool = False  # 凭证有效标志（替代 _token 缓存，token 值仅 SDK 内部）
        # REST 面（M44：共享 lark.Client 惰性创建真实实例 / 测试注入 Mock）
        self._rest_client: FeishuRestClient | None = None

    @property
    def config(self) -> FeishuConfig:
        return self._config

    # ── 生命周期 ──
    def start(self) -> bool:
        """启动桥（启用条件 + 凭证预检 + 后台线程）."""
        if not self._config.enabled:
            logger.warning(
                "飞书桥未启用（FEISHU_APP_ID/FEISHU_APP_SECRET 未配置或 FEISHU_WS_ENABLED=0）"
            )
            return False
        preflight = self._preflight()
        if preflight:
            logger.warning("飞书桥凭证预检失败: %s", preflight)
            return False
        self._running = True
        self._ws_state = "connected"
        self._connector = _WsConnector(
            self._config,
            self._on_ws_message,
            self._has_token,
            self._ensure_rest_client(),
        )
        self._thread = threading.Thread(target=self._run_loop, name="feishu-ws", daemon=True)
        self._thread.start()
        logger.info("飞书桥已启动")
        return True

    def stop(self) -> None:
        self._running = False
        self._ws_state = "disconnected"
        self._token_ready = False
        if self._connector:
            self._connector.stop()
        if self._thread:
            self._thread.join(timeout=2)

    def is_healthy(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def state(self) -> str:
        """连接状态（connected/reconnecting/disconnected，如实可查）."""
        return self._ws_state

    # ── 预检 ──
    def _preflight(self) -> str | None:
        """凭证预检（借鉴 本地既有实现 ws_bridge preflight 算法思路）.

        两段：app_id 格式校验（cli_ 前缀）+ tenant_access_token 凭证预检。
        网络不可达不阻断启动（WS 重连兜底）；失败如实返回原因。
        """
        if not self._config.has_credentials:
            return "FEISHU_APP_ID/FEISHU_APP_SECRET 未配置"
        app_id = self._config.app_id
        if not re.fullmatch(r"cli_[a-z0-9]+", app_id):
            return f"FEISHU_APP_ID 格式异常（{app_id[:8]}...，应为 cli_ 开头）"
        return self._token_probe()

    def _token_probe(self) -> str | None:
        """凭证预检探针（M44，FR-SDK-TKN-02：签名 str|None 保持）.

        仅探针不缓存 token 值（token 生命周期交 SDK）；成功置 `_token_ready=True` 返回 None；
        凭证错误返回含 code/msg 原因（_token_ready 保持 False）；网络不可达返回 None（不阻断启动）。
        """
        try:
            self._fetch_token()  # 探针一次性调用（验证凭证有效性，不缓存 token 值）
            self._token_ready = True
            return None
        except FeishuRestError as exc:
            return str(exc)  # 凭证错误如实返回原因（含 code/msg）
        except Exception:  # noqa: BLE001 — 网络不可达不阻断启动
            return None

    def _fetch_token(self) -> tuple[str, int]:
        """httpx POST 认证端点获取 token（成功返回 (token, expire_seconds)）.

        Raises:
            FeishuRestError: 凭证错误（含 code/msg 如实信息）.
        """
        resp = httpx.post(
            _TOKEN_URL,
            json={"app_id": self._config.app_id, "app_secret": self._config.app_secret},
            timeout=5,
        )
        data = resp.json()
        if data.get("code", 0) != 0:
            raise FeishuRestError(
                f"凭证校验失败（code={data.get('code')} msg={data.get('msg', '')}）"
            )
        token = data.get("tenant_access_token", "")
        if not token:
            raise FeishuRestError("认证响应缺少 tenant_access_token")
        return token, int(data.get("expire", 7200))

    def _has_token(self) -> bool:
        """凭证预检标志（_WsConnector 等待零触网判定，FR-SDK-TKN-02：返回 _token_ready）."""
        return self._token_ready

    def _ensure_lark_client(self) -> lark_oapi.Client:
        """共享 lark.Client（None 时惰性 builder 创建真实实例；测试可注入 Mock）."""
        if self._lark_client is None:
            import lark_oapi as lark

            self._lark_client = (
                lark.Client.builder()
                .app_id(self._config.app_id)
                .app_secret(self._config.app_secret)
                .log_level(lark.LogLevel.WARNING)
                .build()
            )
        return self._lark_client

    def _ensure_rest_client(self) -> FeishuRestClient:
        """REST 客户端（None 时惰性创建，持共享 lark.Client；测试可注入 Mock）."""
        if self._rest_client is None:
            self._rest_client = FeishuRestClient(self._config, self._ensure_lark_client())
        return self._rest_client

    def attach_handler(self, handler: FeishuMessageHandler) -> None:
        """装配消息处理器（build_bridge 顺序：bridge 先建 → attach_handler）."""
        self._handler = handler

    # ── REST 面委托（M43，FR-RW-SND-01/02 + DLD-01/03）──
    def send_text(self, receive_id: str, text: str, receive_id_type: str = "chat_id") -> bool:
        """发送文本消息（委托 rest；失败如实记录 + 尝试如实告知，不伪装成功）.

        receive_id_type: "chat_id" 群聊 / "open_id" 私聊（p2p 无 chat_id 时用 open_id 发送）.
        """
        try:
            self._ensure_rest_client().send_text(receive_id, text, receive_id_type)
            return True
        except Exception as exc:  # noqa: BLE001 — 发送失败如实反馈（fail-open）
            logger.warning("飞书消息发送失败（receive_id=%s）: %s", _mask_id(receive_id), exc)
            # 尝试如实告知（错误说明也失败则日志已完整可追溯，不递归）
            from contextlib import suppress

            with suppress(Exception):
                self._ensure_rest_client().send_text(
                    receive_id,
                    f"[发送失败] 上一条回复未能送达（{type(exc).__name__}）。",
                    receive_id_type,
                )
            return False

    def download_attachment(self, msg: FeishuMessage) -> tuple[bytes | None, str]:
        """下载附件（委托 rest；失败返回 (None, 原因)，handlers fail-open 如实回复）."""
        resource_type = "image" if msg.msg_type == "image" else "file"
        file_key = msg.file_key or ""
        filename = msg.file_name or f"feishu_attachment_{file_key}"
        try:
            data = self._ensure_rest_client().download_resource(
                msg.message_id, file_key, resource_type
            )
            return data, filename
        except Exception as exc:  # noqa: BLE001 — 下载失败如实反馈（fail-open 延续）
            logger.warning("飞书附件下载失败: %s", exc)
            return None, str(exc)

    # ── 消息分发 ──
    def _on_ws_message(self, payload: dict) -> None:
        """WS 事件分发（im.message.receive_v1）：去重 → 解包 → handler."""
        header = payload.get("header") or {}
        event_type = header.get("event_type", "")
        if event_type != "im.message.receive_v1":
            return
        if self._handler is None:
            logger.warning("飞书消息事件到达但 handler 未装配，跳过（build_bridge 后自动装配）")
            return
        event_id = header.get("event_id", "")
        if not self._is_new_event(event_id):
            return  # 去重
        event = payload.get("event") or {}
        msg = self._unpack_message(event)
        if msg is not None:
            try:
                self._handler.handle(msg)
            except Exception as exc:  # 处理异常不中断桥
                logger.exception("feishu message handle crashed: %s", exc)

    def _unpack_message(self, event: dict) -> FeishuMessage | None:
        """解包飞书消息事件 → FeishuMessage（类型/文本/附件/会话信息）.

        chat_id/chat_type 兼容提取（真实结构校准 2026-08-11）：SDK marshal 后事件
        的 chat_id/chat_type 在 `event.message` 内（EventMessage.chat_id/chat_type），
        无 `event.chat` 字段——message 优先，event.chat 兜底（兼容既有 Mock 结构）。
        """
        sender = event.get("sender") or {}
        sender_id = sender.get("sender_id") or {}
        open_id = sender_id.get("open_id", "")
        sender_type = sender.get("sender_type", "")
        message = event.get("message") or {}
        chat = event.get("chat") or {}
        chat_id = message.get("chat_id") or chat.get("chat_id", "")
        chat_type = message.get("chat_type") or chat.get("chat_type", "")
        msg_type = message.get("message_type", "")
        content_raw = message.get("content") or ""
        content = json.loads(content_raw) if isinstance(content_raw, str) else (content_raw or {})
        text = ""
        file_key = None
        file_name = ""
        if msg_type == "text":
            text = content.get("text", "")
        elif msg_type == "post":
            text = _extract_post_text(content)
        elif msg_type == "file":
            file_key = content.get("file_key")
            file_name = content.get("file_name", "")
        elif msg_type == "image":
            file_key = content.get("image_key")
            file_name = "image.png"
        is_group = bool(chat_type == "group")
        return FeishuMessage(
            message_id=message.get("message_id", ""),
            sender_id=open_id,
            chat_id=chat_id,
            msg_type=msg_type,
            text=text,
            is_group=is_group,
            sender_type=sender_type,
            file_key=file_key,
            file_name=file_name,
            raw=payload_safe(event),
        )

    # ── 工具 ──
    def _is_new_event(self, event_id: str) -> bool:
        if not event_id:
            return True
        with self._dedup_lock:
            if event_id in self._seen_ids:
                return False
            self._seen_ids.add(event_id)
            self._seen_order.append(event_id)
            if len(self._seen_order) > _MAX_DEDUP_IDS:
                # 防无限增长：按到达序淘汰最旧（窗口有界，对齐 本地既有实现 _seen_ids 语义）
                oldest = self._seen_order.popleft()
                self._seen_ids.discard(oldest)
            return True

    def _run_loop(self) -> None:
        """后台循环：指数退避重连（5→30s，连续失败超限长退避 300s）."""
        fail_count = 0
        while self._running:
            try:
                if self._connector:
                    self._connector.run()
                fail_count = 0
                self._ws_state = "connected"
            except Exception as exc:
                fail_count += 1
                self._ws_state = "reconnecting"
                logger.warning("飞书 WS 连接异常: %s，%ds 后重连", exc, _backoff_delay(fail_count))
            if not self._running:
                break
            _sleep(_backoff_delay(fail_count))
        self._ws_state = "disconnected"


def _backoff_delay(fail_count: int) -> int:
    """指数退避时长（连续失败计数 → 秒）.

    序列：5/10/20/30/30（1-5 次）→ 连续失败超限（>5 次）长退避 300s（不高频重试）。
    """
    if fail_count > _RECONNECT_MAX_ATTEMPTS:
        return _RECONNECT_LONG_BACKOFF_S
    if fail_count < 1:
        return _RECONNECT_BASE_S
    return min(_RECONNECT_BASE_S * (2 ** (fail_count - 1)), _RECONNECT_MAX_S)


def _extract_post_text(content: dict) -> str:
    """飞书 post 富文本提取（对齐 本地既有实现 _extract_post_text 算法思路）.

    结构：{"title": str, "content": [[{"tag": "text", "text": "..."}]]}。
    拼接各行文本（行内元素以空格连接），标题前置。
    """
    parts: list[str] = []
    title = content.get("title")
    if isinstance(title, str) and title:
        parts.append(title)
    rows = content.get("content") or []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, list):
            continue
        cells = [
            str(c.get("text", "")) for c in row if isinstance(c, dict) and c.get("tag") == "text"
        ]
        line = " ".join(c for c in cells if c)
        if line:
            parts.append(line)
    return "\n".join(parts)


def payload_safe(event: dict) -> dict | None:
    """事件原始数据（日志脱敏用，密钥不外泄）."""
    return event if isinstance(event, dict) else None
