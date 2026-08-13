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

    # === 主动出站文档创建（EVO-20260813-432813b2） ===
    def create_doc(self, title: str, content: str, folder_token: str | None = None) -> tuple[str, str]:
        """创建飞书 docx 文档.

        Args:
            title: 文档标题.
            content: Markdown 内容（转为 docx block 写入）.
            folder_token: 目标文件夹 token（None=根目录）.

        Returns:
            (doc_id, doc_url).
        """
        from lark_oapi.api.docx.v1 import (
            CreateDocumentRequest,
            CreateDocumentRequestBody,
        )
        builder = CreateDocumentRequestBody.builder().title(title)
        if folder_token:
            builder = builder.folder_token(folder_token)
        req = CreateDocumentRequest.builder().request_body(builder.build()).build()
        docx = self._lark_client.docx
        assert docx is not None
        resp = docx.v1.document.create(req)
        if resp.code != 0 or resp.data is None or resp.data.document is None:
            raise FeishuRestError(f"创建文档失败 code={resp.code} msg={resp.msg}")
        doc_id = resp.data.document.document_id or ""
        doc_url = f"https://feishu.cn/docx/{doc_id}" if doc_id else ""
        if content.strip():
            self._write_markdown_to_doc(doc_id, content)
        return doc_id, doc_url

    def _write_markdown_to_doc(self, doc_id: str, content: str) -> None:
        """Markdown -> docx block 转换器（增强版）.

        增强点:
        - 围栏代码块识别为 block_type=14 code（等宽渲染）
        - 行内双星粗体切分为多 TextRun（带 bold 样式）
        - 水平分割线 --- 识别为 divider（block_type=22）
        - 段落连续非空行合并
        - 标题/列表/引用按 SDK 字段方法构造
        """
        import re as _re

        from lark_oapi.api.docx.v1 import (
            CreateDocumentBlockChildrenRequest,
            CreateDocumentBlockChildrenRequestBody,
        )
        from lark_oapi.api.docx.v1.model import (
            BlockBuilder,
            TextBuilder,
            TextElementBuilder,
            TextElementStyleBuilder,
            TextRunBuilder,
        )
        bold_re = _re.compile(r"\*\*(.+?)\*\*")
        divider_re = _re.compile(r"^\s*---\s*$")
        ordered_re = _re.compile(r"^\s*(\d+)\.\s+(.+)$")

        def _run(content, bold=False, code=False):
            style = TextElementStyleBuilder()
            if bold:
                style = style.bold(True)
            if code:
                style = style.inline_code(True)
            tr = TextRunBuilder().content(content).text_element_style(style.build()).build()
            return TextElementBuilder().text_run(tr).build()

        def _split_runs(text):
            elements = []
            pos = 0
            for m in bold_re.finditer(text):
                if m.start() > pos:
                    elements.append(_run(text[pos:m.start()]))
                elements.append(_run(m.group(1), bold=True))
                pos = m.end()
            if pos < len(text):
                elements.append(_run(text[pos:]))
            if not elements:
                elements.append(_run(text))
            return elements

        def _text(elements):
            return TextBuilder().elements(elements).build()

        def _mk_text(text):
            return BlockBuilder().block_type(2).text(_text(_split_runs(text))).build()

        def _mk_heading(text, level):
            t = _text(_split_runs(text))
            if level == 1:
                return BlockBuilder().block_type(3).heading1(t).build()
            if level == 2:
                return BlockBuilder().block_type(4).heading2(t).build()
            return BlockBuilder().block_type(5).heading3(t).build()

        def _mk_bullet(text):
            return BlockBuilder().block_type(12).bullet(_text(_split_runs(text))).build()

        def _mk_ordered(text):
            return BlockBuilder().block_type(13).ordered(_text(_split_runs(text))).build()

        def _mk_quote(text):
            return BlockBuilder().block_type(15).quote(_text(_split_runs(text))).build()

        def _mk_code(text):
            style = TextElementStyleBuilder().inline_code(True).build()
            tr = TextRunBuilder().content(text).text_element_style(style).build()
            el = TextElementBuilder().text_run(tr).build()
            t = TextBuilder().elements([el]).build()
            return BlockBuilder().block_type(14).code(t).build()

        def _mk_divider():
            return BlockBuilder().block_type(22).divider({}).build()

        blocks = []
        lines = content.splitlines()
        i = 0
        backtick_char = chr(96)
        while i < len(lines):
            line = lines[i].rstrip()
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            if stripped.startswith(backtick_char * 3):
                i += 1
                code_lines = []
                while i < len(lines) and not lines[i].strip().startswith(backtick_char * 3):
                    code_lines.append(lines[i].rstrip())
                    i += 1
                i += 1
                code_text = "\n".join(code_lines) if code_lines else ""
                if code_text:
                    blocks.append(_mk_code(code_text))
                continue
            if divider_re.match(line):
                blocks.append(_mk_divider())
                i += 1
                continue
            if stripped.startswith("### "):
                blocks.append(_mk_heading(stripped[4:].strip(), 3))
                i += 1
                continue
            if stripped.startswith("## "):
                blocks.append(_mk_heading(stripped[3:].strip(), 2))
                i += 1
                continue
            if stripped.startswith("# "):
                blocks.append(_mk_heading(stripped[2:].strip(), 1))
                i += 1
                continue
            if stripped.startswith(("- ", "* ", "+ ")):
                blocks.append(_mk_bullet(stripped[2:].strip()))
                i += 1
                continue
            om = ordered_re.match(line)
            if om:
                blocks.append(_mk_ordered(om.group(2).strip()))
                i += 1
                continue
            if stripped.startswith("> "):
                blocks.append(_mk_quote(stripped[2:].strip()))
                i += 1
                continue
            para_lines = [line]
            j = i + 1
            while j < len(lines):
                nl = lines[j]
                ns = nl.strip()
                if not ns:
                    break
                if (
                    ns.startswith("#")
                    or ns.startswith(("- ", "* ", "+ ", "> "))
                    or ns.startswith(backtick_char * 3)
                    or ordered_re.match(nl)
                    or divider_re.match(nl)
                ):
                    break
                para_lines.append(nl.rstrip())
                j += 1
            i = j
            para_text = " ".join(item.strip() for item in para_lines)
            if para_text:
                blocks.append(_mk_text(para_text))
        if not blocks:
            return
        batch_size = 50
        docx = self._lark_client.docx
        assert docx is not None
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i:i + batch_size]
            req = (CreateDocumentBlockChildrenRequest.builder()
                   .document_id(doc_id).block_id(doc_id)
                   .request_body(CreateDocumentBlockChildrenRequestBody.builder().children(batch).build())
                   .build())
            resp = docx.v1.document_block_children.create(req)
            if resp.code != 0:
                raise FeishuRestError(f"写入文档内容失败 code={resp.code} msg={resp.msg}")

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

    # === 主动出站附件发送（EVO-20260813-432813b2: send_feishu_attachment） ===
    def send_file(
        self,
        receive_id: str,
        file_path: str | None = None,
        doc_id: str | None = None,
        receive_id_type: str = "open_id",
    ) -> str:
        """发送文件或文档链接到指定会话.

        Args:
            receive_id: 目标会话 id（open_id/chat_id/user_id/email）.
            file_path: 本地文件路径（与 doc_id 二选一；优先）。
            doc_id: 已创建的飞书文档 id（file_path 缺省时发送文档链接）.
            receive_id_type: 接收方 ID 类型，默认 open_id.

        Returns:
            data.message_id（成功）.

        Raises:
            FeishuRestError: 上传/发送失败（含 code/msg 如实信息）；file_path 与 doc_id 均缺省.
        """
        if not file_path and not doc_id:
            raise FeishuRestError("file_path 与 doc_id 至少传一个")
        if file_path:
            return self._send_file_upload(receive_id, file_path, receive_id_type)
        assert doc_id is not None  # 上述守卫已保证 doc_id 非空
        return self._send_doc_link(receive_id, doc_id, receive_id_type)

    def _send_file_upload(
        self, receive_id: str, file_path: str, receive_id_type: str
    ) -> str:
        """本地文件上传（lark.im.v1.file.create）→ file_key → 发送文件消息."""

        from lark_oapi.api.im.v1 import (
            CreateFileRequest,
            CreateFileRequestBody,
        )
        from lark_oapi.api.im.v1.model.create_message_request import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        fp = Path(file_path)
        if not fp.exists() or not fp.is_file():
            raise FeishuRestError(f"文件不存在或非普通文件: {file_path}")
        file_name = fp.name
        file_type = Path(file_name).suffix.lstrip(".").lower() or "stream"
        im = self._lark_client.im
        assert im is not None
        file_key = ""
        for attempt in range(2):  # 首次 + token 失效重试一次
            try:
                with fp.open("rb") as fh:
                    body = (
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(fh)
                        .build()
                    )
                    req = CreateFileRequest.builder().request_body(body).build()
                    resp = im.v1.file.create(req)
            except OSError as exc:
                raise FeishuRestError(f"文件读取失败: {exc}") from exc
            if resp.code == 0:
                file_key = (resp.data.file_key if resp.data else "") or ""
                if not file_key:
                    raise FeishuRestError("文件上传成功但响应缺少 file_key")
                break
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue
                raise FeishuRestError(f"token 失效重试仍失败（code={resp.code} msg={resp.msg}）")
            raise FeishuRestError(f"文件上传失败 code={resp.code} msg={resp.msg}")
        if not file_key:
            raise FeishuRestError("文件上传失败（重试后仍失败）")
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("file")
                .content(json.dumps({"file_key": file_key}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        for attempt in range(2):  # 首次 + token 失效重试一次
            resp = im.v1.message.create(request)
            if resp.code == 0:
                message_id = (resp.data.message_id if resp.data else "") or ""
                if not message_id:
                    raise FeishuRestError("文件消息发送成功但响应缺少 data.message_id")
                return message_id
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue
                raise FeishuRestError(f"token 失效重试仍失败（code={resp.code} msg={resp.msg}）")
            raise FeishuRestError(f"文件消息发送失败 code={resp.code} msg={resp.msg}")
        raise FeishuRestError("文件消息发送失败（重试后仍失败）")  # 不可达，类型兜底

    def _send_doc_link(
        self, receive_id: str, doc_id: str, receive_id_type: str
    ) -> str:
        """发送飞书文档链接（doc_id → feishu.cn/docx/<id> 链接消息）."""
        from lark_oapi.api.im.v1.model.create_message_request import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )

        url = f"https://feishu.cn/docx/{doc_id}"
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(json.dumps({"text": f"文档：{url}"}, ensure_ascii=False))
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
                    raise FeishuRestError("文档链接发送成功但响应缺少 data.message_id")
                return message_id
            if self._raise_if_token_invalid(resp.code, resp.raw.status_code if resp.raw else 0):
                if attempt == 0:
                    continue
                raise FeishuRestError(f"token 失效重试仍失败（code={resp.code} msg={resp.msg}）")
            raise FeishuRestError(f"文档链接发送失败 code={resp.code} msg={resp.msg}")
        raise FeishuRestError("文档链接发送失败（重试后仍失败）")  # 不可达，类型兜底
