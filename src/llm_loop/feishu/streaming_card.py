"""飞书流式状态卡（M46，对齐 本地既有实现 streaming_card.py 生命周期，状态卡形式）.

解决复杂任务"等待几十秒~分钟无感知"：收到消息即建 cardkit 流式卡（⏳ 处理中），
引擎同步无增量回调 → 状态卡内容固定，完成时更新为完成态 + 关闭 streaming_mode 定稿。

生命周期三步（走 lark-oapi SDK，token 生命周期交 SDK 内部管理）:
1. cardkit.v1.card.create      建卡（schema 2.0 + streaming_mode）→ card_id
2. im.v1.message.create        interactive 消息绑定 card_id → 发到会话（用户可见）
3. cardkit.v1.card.update      更新内容（完成态）
   cardkit.v1.card.settings    关闭 streaming_mode + summary 定稿

任一 API 失败: 调用方回退普通分段路径（_reply_chunked），不阻断主流程。
"""

from __future__ import annotations

import json
import logging
import uuid

import lark_oapi

logger = logging.getLogger(__name__)

# 限流/失败静默跳过的错误码（对齐 rest.py _RATE_LIMIT_CODES）
_RATE_LIMIT_CODES = frozenset({429, 99991400, 99991403})
# token 失效类错误码（重试一次，对齐 rest.py _TOKEN_INVALID_CODES）
_TOKEN_INVALID_CODES = frozenset({99991663, 99991668, 99991661})


def _card_json(content: str, *, streaming: bool, summary: str) -> str:
    """构造 cardkit 卡片 JSON 字符串（schema 2.0 + markdown 元素）.

    Args:
        content: 卡片 markdown 内容（处理中占位 / 完成态）.
        streaming: 是否开启 streaming_mode.
        summary: 卡片摘要（≤50 字符）.
    """
    config: dict = {"width_mode": "fill", "summary": summary}
    if streaming:
        config["streaming_mode"] = True
        config["streaming_config"] = {
            "print_frequency_ms": {"default": 50},
            "print_step": {"default": 1},
        }
    card = {
        "schema": "2.0",
        "config": config,
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }
    return json.dumps(card, ensure_ascii=False)


class StreamingCard:
    """一张 cardkit 流式状态卡的生命周期（create → bind → close）."""

    def __init__(
        self,
        lark_client: lark_oapi.Client,
        placeholder: str = "⏳ 处理中...",
        done_text: str = "✅ 处理完成",
    ) -> None:
        self._lark_client = lark_client
        self._placeholder = placeholder
        self._done_text = done_text
        self._card_id = ""
        self._sequence = 0
        self._broken = False  # 任一 API 失败后置位，后续操作直接跳过

    @property
    def active(self) -> bool:
        """卡片是否处于可操作状态（已建卡且未熔断）."""
        return bool(self._card_id) and not self._broken

    def _cardkit(self):
        """cardkit.v1.card service（None 时如实熔断）."""
        cardkit = self._lark_client.cardkit
        if cardkit is None:
            self._broken = True
            return None
        return cardkit.v1.card

    def _raise_if_token_invalid(self, code: int | None, status_code: int | None) -> bool:
        return (status_code or 0) == 401 or (code or 0) in _TOKEN_INVALID_CODES

    # ── 三步生命周期 ──
    def create(self) -> bool:
        """建流式卡（schema 2.0 + streaming_mode）. 失败返回 False."""
        from lark_oapi.api.cardkit.v1.model.create_card_request import (
            CreateCardRequest,
            CreateCardRequestBody,
        )

        card = self._cardkit()
        if card is None:
            return False
        request = (
            CreateCardRequest.builder()
            .request_body(
                CreateCardRequestBody.builder()
                .type("card")
                .data(_card_json(self._placeholder, streaming=True, summary="[生成中...]"))
                .build()
            )
            .build()
        )
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = card.create(request)
            if resp.code == 0:
                self._card_id = (resp.data.card_id if resp.data else "") or ""
                return bool(self._card_id)
            if self._raise_if_token_invalid(
                resp.code, resp.raw.status_code if resp.raw else 0
            ):
                if attempt == 0:
                    continue
                break
            break
        self._log_fail("create", resp.code, resp.msg)
        self._broken = True
        return False

    def bind(self, receive_id: str, receive_id_type: str = "chat_id") -> bool:
        """把卡片作为 interactive 消息发到会话. 失败返回 False."""
        if not self.active:
            return False
        from lark_oapi.api.im.v1.model.create_message_request import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        im = self._lark_client.im
        if im is None:
            self._broken = True
            return False
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(
                    json.dumps(
                        {"type": "card", "data": {"card_id": self._card_id}},
                        ensure_ascii=False,
                    )
                )
                .build()
            )
            .build()
        )
        for attempt in range(2):
            resp = im.v1.message.create(request)
            if resp.code == 0:
                return True
            if self._raise_if_token_invalid(
                resp.code, resp.raw.status_code if resp.raw else 0
            ):
                if attempt == 0:
                    continue
                break
            break
        self._log_fail("bind", resp.code, resp.msg)
        self._broken = True
        return False

    def update(self, content: str) -> bool:
        """H-UI(2026-08-14): 实时更新流式卡内容（思考/工具动作状态条）.

        未建卡/已熔断 → False（fail-open 不阻断）；调用方观察者回调内使用，
        429 限流静默跳过（_update_content 既有语义）。
        """
        if not self.active:
            return False
        return self._update_content(content)

    def close(self, content: str | None = None) -> bool:
        """定稿: 更新完成态（`content` 提供时回填回复摘要）+ 关闭 streaming_mode + summary.

        失败返回 False（回退分段）。`content=None`（默认）保持既有 `_done_text="✅ 处理完成"` 行为；
        summary 由回填内容首行截断 ≤50 字符（对齐 `_card_json` summary 契约）。
        """
        if not self.active:
            return False
        ok_update = self._update_content(content if content is not None else self._done_text)
        ok_settings = self._close_streaming()
        self._broken = True  # 生命周期结束，防止后续误操作
        return ok_update and ok_settings

    # ── 内部 ──
    def _update_content(self, content: str) -> bool:
        """更新卡片内容（cardkit.v1.card.update）."""
        from lark_oapi.api.cardkit.v1.model.card import Card
        from lark_oapi.api.cardkit.v1.model.update_card_request import (
            UpdateCardRequest,
            UpdateCardRequestBody,
        )

        card = self._cardkit()
        if card is None:
            return False
        self._sequence += 1
        summary = content.strip().splitlines()[0][:50] if content.strip() else "[处理完成]"
        request = (
            UpdateCardRequest.builder()
            .card_id(self._card_id)
            .request_body(
                UpdateCardRequestBody.builder()
                .card(
                    Card.builder()
                    .type("card")
                    .data(_card_json(content, streaming=False, summary=summary))
                    .build()
                )
                .uuid(uuid.uuid4().hex)
                .sequence(self._sequence)
                .build()
            )
            .build()
        )
        for attempt in range(2):
            resp = card.update(request)
            if resp.code == 0:
                return True
            if self._raise_if_token_invalid(
                resp.code, resp.raw.status_code if resp.raw else 0
            ):
                if attempt == 0:
                    continue
                break
            break
        self._log_fail("update", resp.code, resp.msg)
        return False

    def _close_streaming(self) -> bool:
        """关闭 streaming_mode + summary 定稿（cardkit.v1.card.settings）."""
        from lark_oapi.api.cardkit.v1.model.settings_card_request import (
            SettingsCardRequest,
            SettingsCardRequestBody,
        )

        card = self._cardkit()
        if card is None:
            return False
        request = (
            SettingsCardRequest.builder()
            .card_id(self._card_id)
            .request_body(
                SettingsCardRequestBody.builder()
                .settings(
                    json.dumps(
                        {
                            "config": {
                                "streaming_mode": False,
                                "summary": "[处理完成]",
                            }
                        },
                        ensure_ascii=False,
                    )
                )
                .uuid(uuid.uuid4().hex)
                .sequence(self._sequence)
                .build()
            )
            .build()
        )
        for attempt in range(2):
            resp = card.settings(request)
            if resp.code == 0:
                return True
            if self._raise_if_token_invalid(
                resp.code, resp.raw.status_code if resp.raw else 0
            ):
                if attempt == 0:
                    continue
                break
            break
        self._log_fail("settings", resp.code, resp.msg)
        return False

    @staticmethod
    def _log_fail(stage: str, code: int | None, msg: str | None) -> None:
        if code in _RATE_LIMIT_CODES:
            logger.info("cardkit %s 限流: code=%s", stage, code)
        else:
            logger.debug("cardkit %s failed: code=%s msg=%s", stage, code, msg)


__all__ = ["StreamingCard"]
