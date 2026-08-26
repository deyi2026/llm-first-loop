"""工具输出截断公共实现（2026-08-18 对齐 DSH——统一模式）.

EVO-20260817-f485acac 模式（execute_command 首创）: 超阈值输出落盘 +
保留首尾；全文通过显式落盘路径 read_file 取回——read_file/web_search 对齐同款——
控制尾部新增体积（缓存命中率：尾部新增段无缓存——小=命中高）。

2026-08-21 修复（缓存前缀确定性）: 落盘路径由时间戳改为内容哈希——
时间戳使路径每轮变化 → 发送视图前缀字节变 → 服务端缓存全 miss
（12 实验规律: 已发送内容任何修改=全 miss）。内容哈希: 相同内容→
相同路径（前缀稳定可命中）；不同内容→不同路径（不误读旧文件）。
"""
from __future__ import annotations

import hashlib
import os
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


def truncation_marker(
    total: int,
    keep_head: int,
    keep_tail: int,
    max_chars: int,
    keywords: str = "",
    dump_path: str = "",
) -> str:
    """截断标记（事实 + 动作两段式，2026-08-20 停滞循环排查落地）.

    事实段如实告知截断与确定性；动作段显式声明"重跑相同命令/重读同一路径不会得到
    新信息"，并给出真实可用的取全文通道（full=true / read_file 落盘）——
    封死"截断视图 → 重跑同命令 → 同视图"的空转循环（事故: 20fdd562 会话连续 5 次
    相同参数重跑 grep 被停滞熔断）。

    2026-08-20 精简（token 用量反馈）: 标记随历史每轮重发，冗长解释按 token 计费——
    保留防重跑声明 + 两条真实取全文路径，砍掉原因/可调参数/建议等冗余说明。

    2026-08-24 如实化：本 helper 自己只写 data/audit/tool_outputs 显式文件，并未写
    ArchiveStore；且 ToolRegistry 看到的是已经裁剪后的结果，无法再归档原始全文。
    因此不得提示 search_archive，避免 AI 检索一个实际不存在的档案。
    """
    del keywords  # 兼容旧调用签名；本 helper 不写 ArchiveStore，关键词不能凭空变成档案索引。
    dump = f" {dump_path}" if dump_path else ""
    return (
        f"[输出已截断] 完整 {total} 字符，仅首 {keep_head} + 尾 {keep_tail}"
        f"（阈值 {max_chars}）。截断确定性: 重跑得同结果勿重跑。"
        f"取全文: full=true 重调 / read_file 读取落盘全文{dump}。"
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
        [
            w
            for w in source.split()
            if w.isalnum() and len(w) >= 2 and w not in {"and", "or", "not", "the", "for", "with", "echo"}
        ][:3]
    )
    dump_path_str = ""
    try:
        out_dir = Path(os.environ.get("DATA_DIR", "data")) / "audit" / "tool_outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in source[:40]) or "out"
        # 2026-08-21 修复: 内容哈希替代时间戳——确定性路径（相同内容→同路径，
        # 前缀稳定缓存命中；不同内容→不同路径，不误读）。保留源名前缀便于检索。
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
        dump_path = out_dir / f"{digest}_{safe[:24]}.log"
        dump_path.write_text(content, encoding="utf-8")
        dump_path_str = str(dump_path)
    except Exception:  # noqa: BLE001 — 落盘失败不阻断截断
        dump_path_str = ""
    return (
        f"{head}\n"
        f"{truncation_marker(len(content), keep_head, keep_tail, max_chars, kw, dump_path_str)}\n"
        f"{tail}"
    )
