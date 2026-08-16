"""基础工具: dsh_session_read —— 读取 DSH session 事件日志（回放检索，协议 v2 §7.1 ③）.

背景: dsh_task 只回收最终回答文本（headless 契约），中间过程（推理/工具调用/中间结论）
在 DSH session 事件日志（~/.dsh/sessions/<workspace-key>/session-<uuid>/session.jsonl.zstd，
zstd 压缩 JSONL）里。本工具按需回放——需要中间细节时读日志提取，不需要时零开销。

事件格式（已实测 DSH session 文件）:
- 首行: session 元数据（type/version/id/createdAt/cwd）
- 逐行: {type, seq, time, data}；类型含 assistant/message（完整消息，content 含
  reasoning/text 块）、assistant/chunk、tool/call + tool/result、user/message、
  turn/start|end、step/start|end 等
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.workspace.store import workspace_key

logger = logging.getLogger(__name__)

_DSH_SESSIONS_ROOT = Path(os.environ.get("DSH_SESSIONS_ROOT", str(Path.home() / ".dsh" / "sessions")))
_MAX_OUTPUT_CHARS = 30_000
_MAX_EVENTS_DEFAULT = 40  # 默认提取事件上限（防超大日志淹没回执）


class DshSessionReadTool:
    name = "dsh_session_read"
    description = (
        "读取 DeepSeek Harness 最近 session 的事件日志（回放检索，协议 v2 补全中间过程）。何时用: "
        "dsh_task 只回了最终文本，需要看 DSH 执行过程中的推理/工具调用/中间结论（排查为什么这么"
        "做、验证执行轨迹）时，回放日志。何时不用: 只需最终结果时（dsh_task 回执已含）。"
        "注意: 读取 ~/.dsh/sessions/ 下指定工作区的最新 session（或按 session_id 指定）；输出"
        "提取最终回答 + 工具调用轨迹 + 关键事件，截断 3 万字符；日志不存在/不可读时如实标注。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "workspace": {
                "type": "string",
                "description": "目标工作区目录（可选，默认当前工作区；决定读哪个 ~/.dsh/sessions 目录）",
            },
            "session_id": {
                "type": "string",
                "description": "指定 session id（可选，默认取该工作区最新 session；形如 session-<uuid> 或 <uuid>）",
            },
            "keyword": {
                "type": "string",
                "description": "关键词过滤（可选，只回显包含该关键词的事件文本）",
            },
            "limit": {
                "type": "integer",
                "description": "最大提取事件数（可选，默认 40，上限 200）",
            },
        },
        "required": [],
    }

    def execute(self, **kwargs) -> ToolResult:
        workspace = str(kwargs.get("workspace", "") or "").strip()
        if not workspace:
            from llm_loop.core.run_context import workspace_base

            workspace = workspace_base()
        session_id = str(kwargs.get("session_id", "") or "").strip()
        keyword = str(kwargs.get("keyword", "") or "").strip()
        limit = int(kwargs.get("limit") or _MAX_EVENTS_DEFAULT)
        limit = max(1, min(limit, 200))

        key = workspace_key(workspace)
        root = self._sessions_root()
        base = root / key
        if not base.is_dir():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] DSH session 目录不存在: {base}（该工作区尚无 DSH 任务）",
                tool_call_id="",
                tool_name=self.name,
            )

        session_dir = self._pick_session_dir(base, session_id)
        if session_dir is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: failure] 未找到 session"
                    f"{f'（id={session_id}）' if session_id else '（该工作区无 session）'}: {base}"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

        events = self._read_events(session_dir)
        if events is None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[状态: failure] session 日志不可读: {session_dir}",
                tool_call_id="",
                tool_name=self.name,
            )

        digest = self._digest(events, keyword, limit)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[状态: success] DSH session 回放: {session_dir.name}\n"
                f"（事件 {len(events)} 条，关键词{f'「{keyword}」' if keyword else '无'}，"
                f"提取 {len(digest)} 段）\n\n{digest}"
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    # ── 内部 ──
    @staticmethod
    def _sessions_root() -> Path:
        """session 根目录：DSH_HOME 已重定向（服务进程写项目内 data/dsh-home）→ 跟随；
        否则用模块常量（~/.dsh/sessions 或 DSH_SESSIONS_ROOT 覆盖）."""
        dsh_home = os.environ.get("DSH_HOME", "").strip()
        if dsh_home:
            return Path(dsh_home) / "sessions"
        return _DSH_SESSIONS_ROOT

    @staticmethod
    def _pick_session_dir(base: Path, session_id: str) -> Path | None:
        """选 session 目录：指定 id 精确匹配；否则取最新（按 mtime）."""
        if session_id:
            cand = base / session_id
            if cand.is_dir():
                return cand
            return None
        dirs = [d for d in base.iterdir() if d.is_dir()]
        if not dirs:
            return None
        return max(dirs, key=lambda d: d.stat().st_mtime)

    @staticmethod
    def _read_events(session_dir: Path) -> list[dict] | None:
        """读 session.jsonl.zstd → 事件列表（不可读返回 None）."""
        zstd_file = session_dir / "session.jsonl.zstd"
        if not zstd_file.is_file():
            return None
        try:
            import zstandard

            dctx = zstandard.ZstdDecompressor()
            with zstd_file.open("rb") as f:
                data = dctx.stream_reader(f).read()
            events = []
            for line in data.decode("utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return events
        except Exception:  # noqa: BLE001 — 读失败如实标注（fail-open，日志损坏不影响主链路）
            logger.warning("dsh_session_read 读取失败: %s", zstd_file)
            return None

    @classmethod
    def _digest(cls, events: list[dict], keyword: str, limit: int) -> str:
        """提取摘要：最终回答 + 工具调用轨迹 + 关键事件（keyword 过滤可选）."""
        parts: list[str] = []
        kw_re = re.compile(re.escape(keyword), re.IGNORECASE) if keyword else None

        def _matches(text: str) -> bool:
            return kw_re is None or kw_re.search(text) is not None

        # 最终回答（最后一条 assistant/message 的 text 块）
        final_text = ""
        for e in events:
            if e.get("type") == "assistant/message":
                msg = (e.get("data") or {}).get("message") or {}
                text = "".join(
                    b.get("text", "")
                    for b in msg.get("content", [])
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                if text:
                    final_text = text
        if final_text and (kw_re is None or _matches(final_text)):
            parts.append(f"── 最终回答 ──\n{final_text}")

        # 工具调用轨迹（tool/call + tool/result 配对）
        for e in events:
            if e.get("type") == "tool/call":
                d = e.get("data") or {}
                name = (d.get("call") or {}).get("name") or d.get("name") or "?"
                args = (d.get("call") or {}).get("arguments") or d.get("arguments") or {}
                if isinstance(args, dict):
                    args = json.dumps(args, ensure_ascii=False)[:300]
                line = f"[tool/call seq={e.get('seq')}] {name} {args}"
                if _matches(line):
                    parts.append(line)
            elif e.get("type") == "tool/result":
                d = e.get("data") or {}
                status = d.get("status") or ""
                line = f"[tool/result seq={e.get('seq')}] {status}"
                if _matches(line):
                    parts.append(line)
            elif e.get("type") == "turn/end":
                d = e.get("data") or {}
                reason = (d.get("reason") or {})
                if isinstance(reason, dict):
                    reason = reason.get("kind", "")
                line = f"[turn/end seq={e.get('seq')}] reason={reason}"
                if _matches(line):
                    parts.append(line)

        if not parts:
            parts.append("（无可提取事件，或关键词无匹配）")
        joined = "\n".join(parts)
        if len(joined) > _MAX_OUTPUT_CHARS:
            joined = joined[:_MAX_OUTPUT_CHARS] + "\n…[摘要截断]…"
        # 上限保护：只保留前 limit 段
        kept = joined.split("\n")
        if len(kept) > limit * 2:
            kept = kept[: limit * 2] + [f"…（事件过多，仅显示前 {limit} 段）"]
        return "\n".join(kept)
