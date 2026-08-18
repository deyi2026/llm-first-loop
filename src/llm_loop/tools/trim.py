"""工具输出截断公共实现（2026-08-18 对齐 DSH——统一模式）.

EVO-20260817-f485acac 模式（execute_command 首创）: 超阈值输出落盘 +
保留首尾 + search_archive 可检索——read_file/web_search 对齐同款——
控制尾部新增体积（缓存命中率：尾部新增段无缓存——小=命中高）。
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def trim_config() -> tuple[int, int, int]:
    """返回 (max, head, tail) 裁剪参数；环境变量非法/未设置回退默认."""

    def _get(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, "") or default)
        except ValueError:
            return default

    return (
        _get("TOOL_TRIM_MAX", 3000),
        _get("TOOL_TRIM_HEAD", 1500),
        _get("TOOL_TRIM_TAIL", 1500),
    )


def truncate_output(content: str, source: str = "") -> str:
    """截断长输出：保留首 N + 末 M 字符，中间附截断说明；超阈值完整输出落盘.

    - 落盘目录 data/audit/tool_outputs/（显式文件——AI 可 read_file 按需读全文）
    - 落盘失败 fail-open 不影响截断
    """
    max_chars, keep_head, keep_tail = trim_config()
    if len(content) <= max_chars:
        return content
    head = content[:keep_head]
    tail = content[-keep_tail:]
    kw = " ".join(
        w for w in source.split() if w.isalnum() and len(w) >= 2 and w not in {"and", "or", "not", "the", "for", "with", "echo"}
    )[:3]
    saved_note = ""
    try:
        out_dir = Path(os.environ.get("DATA_DIR", "data")) / "audit" / "tool_outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in source[:40]) or "out"
        dump_path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe[:24]}.log"
        dump_path.write_text(content, encoding="utf-8")
        saved_note = f"\n完整输出已落盘: {dump_path}（可 read_file 按需读取全文）"
    except Exception:  # noqa: BLE001 — 落盘失败不阻断截断
        saved_note = ""
    return (
        f"{head}\n"
        f"[输出已截断] 事实: 完整输出 {len(content)} 字符，仅展示首 {keep_head} + 末 {keep_tail} 字符"
        f"（触发阈值: {max_chars} 字符，TOOL_TRIM_MAX/HEAD/TAIL 环境变量可调）。"
        f"\n原因: 上下文优化（方案 4 工具输出截断——对齐 DSH——尾部新增小=缓存命中高）。"
        f"\n建议: 如需完整内容可用 search_archive 检索{'，搜索关键词: ' + kw if kw else '（按相关词检索）'}。"
        f"{saved_note}\n"
        f"{tail}"
    )
