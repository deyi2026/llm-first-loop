"""飞书 REST 面（M45，FeishuRestClient，全链路官方 SDK + md 显示层增强）.

M44 SDK 化（用户拍板 2026-08-11）：发送/下载切换 lark.Client（lark.im.v1 message.create /
message_resource.get），token 生命周期交 SDK 内部管理——feishu 层零 token 值接触。
M45 发送显示层增强（用户反馈 2026-08-11）：send_text 从 msg_type="text" 纯文本 →
interactive（Card 2.0 markdown 元素，双端一致渲染）+ 失败如实回退 text + 表格超限
（230099/11310）转 bullets 重试一次 + token 失效重试延续（interactive/text 两层）+
回退路径发送审计落盘（fail-open）。
"""

import json
import logging
import os
from pathlib import Path

import lark_oapi

from llm_loop.feishu.card_utils import _build_card_content, convert_tables_to_bullets
from llm_loop.feishu.config import FeishuConfig

logger = logging.getLogger(__name__)

# 飞书 token 失效类错误码（官方文档；HTTP 401 亦触发重试，SDK 化检测）
_TOKEN_INVALID_CODES = frozenset({99991663, 99991668, 99991661})
# 卡片表格超限类错误码（表格密集回复触发，转 bullets 兜底）
_TABLE_OVERFLOW_CODES = frozenset({230099, 11310})
# 限流类错误码（Typing reaction 遇之静默跳过，防风暴；对齐 本地既有实现 ws_bridge _RATE_LIMIT_CODES）
_RATE_LIMIT_CODES = frozenset({429, 99991400, 99991403})


class FeishuRestError(Exception):
    """飞书 REST 调用失败（含 code/msg 如实信息）."""


class _TableOverflowError(Exception):
    """卡片表格超限信号（触发转 bullets 重试）."""

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"卡片表格超限（code={code}）")


def _mask_id(value: str) -> str:
    """标识符日志脱敏（保留前 8 字符，防完整外泄）."""
    return f"{value[:8]}..." if value else ""


def _default_audit_dir() -> str:
    """审计目录默认（与 handlers 既有路径一致）."""
    return os.environ.get("DATA_DIR", "./data") + "/audit"


def _write_audit_line(path: Path, record: dict) -> None:
    """审计单条落盘（模块级函数，与 handlers._write_audit_line 格式兼容，fail-open）."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class FeishuRestClient:
    """飞书 REST 面客户端（持共享 lark.Client，token 生命周期交 SDK 内部管理）."""

    def __init__(
        self,
        config: FeishuConfig,
        lark_client: lark_oapi.Client,
        audit_path: str | Path | None = None,
    ) -> None:
        self._config = config
        self._lark_client = lark_client
        self._audit_path = Path(audit_path or f"{_default_audit_dir()}/feishu_audit.jsonl")

    def _raise_if_token_invalid(self, code: int | None, status_code: int | None) -> bool:
        """token 失效判定（SDK 化 401 检测：HTTP 401 或失效错误码）."""
        return (status_code or 0) == 401 or (code or 0) in _TOKEN_INVALID_CODES

    def _audit_fallback(self, receive_id: str, send_type: str, code: int, msg: str) -> None:
        """回退路径发送审计落盘（fail-open：写失败静默，不阻断发送链路）."""
        from contextlib import suppress

        with suppress(OSError):
            _write_audit_line(
                self._audit_path,
                {
                    "kind": "send_fallback",
                    "send_type": send_type,
                    "fallback": True,
                    "code": code,
                    "msg": msg[:200],
                    "receive_id": _mask_id(receive_id),
                },
            )

    # ── 消息发送（FR-FMD-CRD-01~03 + FBK-01~03 + TBL-01/03，interactive 卡片 + 回退链）──
    def send_text(self, receive_id: str, text: str, receive_id_type: str = "chat_id") -> str:
        """发送文本消息到指定会话（interactive Card 2.0 markdown 渲染，失败如实回退 text）.

        Args:
            receive_id: 目标会话 id（chat_id 或 open_id，取决于 receive_id_type）.
            text: 回复 markdown 原文（如实透传进卡片 markdown 元素，不截断不篡改）.
            receive_id_type: 目标 id 类型（"chat_id" 群聊 / "open_id" 私聊，默认 chat_id）.

        Returns:
            data.message_id（成功）.

        Raises:
            FeishuRestError: interactive 与 text 回退均失败（含两段失败 code/msg 如实信息）.
        """
        try:
            return self._send_interactive(receive_id, text, receive_id_type, converted=False)
        except _TableOverflowError as exc:
            # 表格超限 → 转 bullets 重发一次（对齐 本地既有实现 算法思路，不无限重试）
            converted = convert_tables_to_bullets(text)
            self._audit_fallback(receive_id, "interactive", exc.code, "表格超限转 bullets")
            try:
                return self._send_interactive(
                    receive_id, converted, receive_id_type, converted=True
                )
            except FeishuRestError as exc2:
                return self._fallback_text(receive_id, converted, receive_id_type, exc2)
        except FeishuRestError as exc:
            return self._fallback_text(receive_id, text, receive_id_type, exc)

    def _send_interactive(
        self, receive_id: str, text: str, receive_id_type: str, *, converted: bool
    ) -> str:
        """interactive 卡片发送（Card 2.0 markdown 元素；token 失效重试一次；表格超限信号）."""
        from lark_oapi.api.im.v1.model.create_message_request import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(_build_card_content(text))
                .build()
            )
            .build()
        )

        im = self._lark_client.im
        assert im is not None
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = im.v1.message.create(request)
            if resp.code == 0:
                message_id = (resp.data.message_id if resp.data else "") or ""
                if not message_id:
                    raise FeishuRestError("发送成功但响应缺少 data.message_id")
                return message_id
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue  # token 失效 → SDK 内部已重新获取 → 重试一次
                raise FeishuRestError(f"token 失效重试仍失败（code={resp.code} msg={resp.msg}）")
            if resp.code in _TABLE_OVERFLOW_CODES and not converted:
                raise _TableOverflowError(resp.code)
            raise FeishuRestError(f"code={resp.code} msg={resp.msg}")
        raise FeishuRestError("发送失败（重试后仍失败）")  # 不可达，类型兜底

    def _fallback_text(
        self, receive_id: str, text: str, receive_id_type: str, cause: Exception
    ) -> str:
        """interactive 失败 → 如实回退 text 同一内容（显示层降级非内容降级，降级不丢内容）.

        Raises:
            FeishuRestError: text 回退也失败（含 interactive 与 text 两段失败 code/msg）.
        """
        self._audit_fallback(receive_id, "text", 0, str(cause)[:200])
        try:
            return self._send_text_plain(receive_id, text, receive_id_type)
        except Exception as exc2:  # noqa: BLE001 — 两段失败如实汇总
            raise FeishuRestError(f"interactive 失败（{cause}）+ text 回退失败（{exc2}）") from exc2

    def _send_text_plain(self, receive_id: str, text: str, receive_id_type: str) -> str:
        """text 纯文本发送（回退链底层；token 失效重试一次）."""
        from lark_oapi.api.im.v1.model.create_message_request import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )

        im = self._lark_client.im
        assert im is not None
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = im.v1.message.create(request)
            if resp.code == 0:
                message_id = (resp.data.message_id if resp.data else "") or ""
                if not message_id:
                    raise FeishuRestError("回退发送成功但响应缺少 data.message_id")
                return message_id
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue
                raise FeishuRestError(
                    f"回退 token 失效重试仍失败（code={resp.code} msg={resp.msg}）"
                )
            raise FeishuRestError(f"回退 code={resp.code} msg={resp.msg}")
        raise FeishuRestError("回退发送失败（重试后仍失败）")  # 不可达，类型兜底

    # ── Typing reaction 回执（M46，FR-TYP-01~04，对齐 本地既有实现 ws_bridge Typing reaction）──
    def add_typing_reaction(self, message_id: str) -> str:
        """对用户消息加 Typing 表情 reaction（处理中回执）.

        对齐 本地既有实现 ws_bridge._add_typing_reaction 算法思路：收到消息立即加
        Typing 表情，回复发出后删除，消除复杂任务等待期"是否收到"疑虑。

        Args:
            message_id: 目标消息 id（用户刚发的消息）.

        Returns:
            reaction_id（删除用）；限流/失败时返回空串（fail-open，不阻断主流程）.
        """
        from lark_oapi.api.im.v1.model.create_message_reaction_request import (
            CreateMessageReactionRequest,
            CreateMessageReactionRequestBody,
        )
        from lark_oapi.api.im.v1.model.emoji import Emoji

        request = (
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type("Typing").build())
                .build()
            )
            .build()
        )

        im = self._lark_client.im
        assert im is not None
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = im.v1.message_reaction.create(request)
            if resp.code == 0:
                reaction_id = (resp.data.reaction_id if resp.data else "") or ""
                if not reaction_id:
                    logger.debug("feishu typing reaction 响应缺少 reaction_id")
                return reaction_id
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue  # token 失效 → SDK 内部已重新获取 → 重试一次
                break
            break
        if resp.code in _RATE_LIMIT_CODES:
            logger.info("feishu typing reaction 限流, 跳过: code=%s", resp.code)
        else:
            logger.debug(
                "feishu typing reaction failed: code=%s msg=%s", resp.code, resp.msg
            )
        return ""

    def remove_reaction(self, message_id: str, reaction_id: str) -> None:
        """回复完成后删除 Typing reaction（best-effort，永不阻断主流程）."""
        if not reaction_id:
            return
        from lark_oapi.api.im.v1.model.delete_message_reaction_request import (
            DeleteMessageReactionRequest,
        )

        request = (
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        im = self._lark_client.im
        assert im is not None
        try:
            for attempt in range(2):  # 首次 + token 失效重试一次
                resp = im.v1.message_reaction.delete(request)
                if resp.code == 0:
                    return
                if self._raise_if_token_invalid(
                    resp.code, resp.raw.status_code if resp.raw else 0
                ):
                    if attempt == 0:
                        continue
                    break
                break
            logger.debug(
                "feishu reaction delete failed: code=%s msg=%s", resp.code, resp.msg
            )
        except Exception as exc:  # noqa: BLE001 — 删除失败静默，不影响主流程
            logger.debug("feishu reaction delete error: %s", exc)

    # ── 附件下载（FR-SDK-DLD-01/03）──
    def download_resource(self, message_id: str, file_key: str, resource_type: str) -> bytes:
        """下载消息附件（lark.im.v1.message_resource.get）.

        Args:
            message_id: 消息 id.
            file_key: 资源 key（图片 image_key / 文件 file_key）.
            resource_type: "image" 或 "file".

        Returns:
            附件二进制内容（SDK 响应 resp.file 为 io.BytesIO → .read()）.

        Raises:
            FeishuRestError: code≠0（含 code/msg 如实信息）.
        """
        from lark_oapi.api.im.v1.model.get_message_resource_request import GetMessageResourceRequest

        request = (
            GetMessageResourceRequest.builder()
            .type(resource_type)
            .message_id(message_id)
            .file_key(file_key)
            .build()
        )

        im = self._lark_client.im
        assert im is not None
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = im.v1.message_resource.get(request)
            if resp.code == 0:
                if resp.file is None:
                    raise FeishuRestError("下载成功但响应缺少 file 内容")
                return resp.file.read()
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue  # token 失效 → SDK 内部已重新获取 → 重试一次
                raise FeishuRestError(f"token 失效重试仍失败（code={resp.code} msg={resp.msg}）")
            raise FeishuRestError(f"code={resp.code} msg={resp.msg}")
        raise FeishuRestError("下载失败（重试后仍失败）")  # 不可达，类型兜底
