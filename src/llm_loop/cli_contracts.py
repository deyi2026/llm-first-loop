"""Shared CLI argument contracts for all terminal entrypoints.

Keep parser construction outside cli.py so the CLI and direct MCP export entrypoint
can share one contract without creating a runtime import cycle.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from llm_loop.runtime.resolver import legacy_env_snapshot

DEFAULT_DATA_DIR = "./data"


LEGACY_COMMANDS = {
    "list", "delete", "archive", "unarchive", "search", "extract", "fork", "rename",
    "evolve-list", "evolve-review", "evolve-complete", "evolve-verify", "export-distill",
    "export-serve-mcp", "event-inventory", "archive-index", "event-migrate", "event-verify",
    "event-rollback", "session-fork", "event-retire", "event-retire-rollback",
    "event-rotate-status", "event-hooks", "faults", "archive-stale",
}


def build_chat_parser(prog: str = "llm_loop") -> argparse.ArgumentParser:
    """One option contract for both command help and chat argument preflight."""
    parser = argparse.ArgumentParser(prog=prog, description="LFL terminal chat")
    parser.add_argument("message", nargs="?", help="单条消息（不填则进入交互模式）")
    parser.add_argument("--interactive", action="store_true", help="交互模式")
    parser.add_argument("--session", help="复用指定会话（单条/交互）")
    parser.add_argument("--stdin", action="store_true", help="标准输入全文作为一个用户消息")
    parser.add_argument("--message-file", help="UTF-8 文件全文作为一个用户消息")
    parser.add_argument("--output", choices=("text", "json", "jsonl"), default="text", help="stdout protocol")
    parser.add_argument("--plain", action="store_true", help="关闭终端增强；保留完整内容")
    parser.add_argument("--no-stream", action="store_true", help="仅显示最终回答（仍消费真实事件）")
    parser.add_argument("--theme", choices=("auto", "dark", "light", "high-contrast", "mono"), default=None)
    parser.add_argument(
        "--model", dest="model", default="",
        help="启动时为会话装配模型（provider/model 或裸模型名；与 Web /model 一致）",
    )
    return parser


def build_legacy_parser(command: str) -> argparse.ArgumentParser:
    """Canonical argument contract for legacy commands, used before any bootstrap."""
    descriptions = {
        "list": "列出会话（保留旧命令别名）", "delete": "删除指定会话",
        "archive": "归档指定会话", "unarchive": "取消归档指定会话",
        "search": "搜索会话", "extract": "触发独立记忆提取",
        "fork": "从现有会话创建分支", "rename": "重命名会话",
        "evolve-list": "列出演进建议", "evolve-review": "审阅演进建议",
        "evolve-complete": "登记演进执行结果", "evolve-verify": "核验演进结果",
        "export-distill": "导出 ReAct 蒸馏数据集", "export-serve-mcp": "启动只读导出 MCP server",
        "event-inventory": "只读盘点事件日志存储", "archive-index": "重建压缩档案索引",
        "event-migrate": "迁移会话到事件日志", "event-verify": "核对事件重放与源会话",
        "event-rollback": "从备份恢复源会话", "session-fork": "通过事件日志创建会话分支",
        "event-retire": "对账并退役旧存储", "event-retire-rollback": "恢复退役前的源文件",
        "event-rotate-status": "查看事件日志分段", "event-hooks": "查看或测试事件钩子",
        "faults": "汇总工具故障台账",
        "archive-stale": "批量归档超过 N 天未更新的 active 会话（薄壳命令，不装配引擎）",
    }
    if command not in LEGACY_COMMANDS:
        raise ValueError(f"Unknown legacy command: {command}")
    parser = argparse.ArgumentParser(prog=f"lfl {command}", description=descriptions[command])
    if command == "list":
        parser.add_argument("--archived", action="store_true", help="同时显示已归档会话")
    elif command == "delete":
        parser.add_argument("session_id", help="要删除的会话 ID")
        parser.add_argument("--yes", action="store_true", help="跳过交互确认")
    elif command in {"archive", "unarchive", "extract"}:
        parser.add_argument("session_id", help="目标会话 ID")
    elif command == "search":
        parser.add_argument("query", nargs="+", help="搜索关键词；多个未加引号的词会合并")
    elif command == "fork":
        parser.add_argument("session_id", help="源会话 ID")
        parser.add_argument("--at", type=int, default=None, help="分叉点消息索引；缺省为会话末尾")
        parser.add_argument("--summary", default="", help="分支摘要；缺省自动提炼")
    elif command == "rename":
        parser.add_argument("session_id", help="要重命名的会话 ID")
        parser.add_argument("new_title", nargs="+", help="新标题；多个词会合并")
    elif command == "evolve-list":
        parser.add_argument("status", nargs="?", help="可选状态筛选")
    elif command == "evolve-review":
        parser.add_argument("suggestion_id", help="演进建议 ID")
        parser.add_argument("decision", choices=("accepted", "rejected"), help="审阅决定")
        parser.add_argument("--authorize-exec", action="store_true", help="允许后续执行已接受的建议")
    elif command == "evolve-complete":
        parser.add_argument("suggestion_id", help="演进建议 ID")
        parser.add_argument("result", nargs="+", help="执行结果说明")
    elif command == "evolve-verify":
        parser.add_argument("suggestion_id", help="演进建议 ID")
        parser.add_argument("note", nargs="+", help="核验说明")
    elif command == "export-distill":
        data = Path(legacy_env_snapshot().get("DATA_DIR") or "data")
        default_input = str(data / "sessions") + os.sep
        parser.add_argument("--input-dir", default=default_input,
                            help=f"会话输入目录（默认 {default_input}）")
        parser.add_argument("--output", default="",
                            help="JSONL 输出路径（默认生成带时间戳的文件）")
        parser.add_argument("--report", default="",
                            help="统计报告路径（默认与输出文件放在同一目录）")
        parser.add_argument("--force", action="store_true", help="覆盖既有输出文件")
    elif command == "export-serve-mcp":
        parser.add_argument("--experiences-dir", help="覆盖经验库目录（缺省读 Settings）")
        parser.add_argument("--methods-dir", help="覆盖方法库目录")
        parser.add_argument("--method-seed-dir", help="覆盖方法 seed 目录")
        parser.add_argument("--evidence-root", help="覆盖证据 ledger 根目录")
        parser.add_argument("--evidence-owner", help="workspace_id/session_id；缺省读 LFL_EXPORT_EVIDENCE_OWNER")
    elif command in {"event-inventory", "archive-index"}:
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
    elif command == "event-migrate":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--force", action="store_true", help="跳过幂等检查强制迁移")
    elif command == "event-verify":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--session", default="", help="只核验指定会话")
        group.add_argument("--all", action="store_true", help="核验全部会话")
    elif command == "event-rollback":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--session", default="", help="单会话回滚（默认全部备份）")
        parser.add_argument("--remove-events", action="store_true",
                            help="同时清除对应事件日志（需操作者显式确认）")
    elif command == "session-fork":
        parser.add_argument("--session", required=True, help="源会话 ID")
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--fork-point", type=int, default=None, help="fork 点（保留前 N 条消息；缺省=全部）")
        parser.add_argument("--summary", default="", help="分支摘要（缺省自动提炼）")
    elif command == "event-retire":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--force", action="store_true", help="跳过幂等检查强制退役")
    elif command == "event-retire-rollback":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--backup-dir", required=True, help="备份区目录")
    elif command == "event-rotate-status":
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--session", default="", help="单会话段清单（缺省列出全部多段会话）")
    elif command == "event-hooks":
        parser.add_argument("subcommand", choices=("list", "test"), help="子命令")
        parser.add_argument("--event", default="", help="测试事件 JSON（test 子命令）")
    elif command == "faults":
        parser.add_argument("--limit", type=int, default=15, help="最多显示条数（默认 15）")
        parser.add_argument("--data-dir", help="数据目录；缺省使用配置目录")
    elif command == "archive-stale":
        parser.add_argument("--days", type=int, default=5,
                            help="过期阈值天数（默认 5；updated_at 严格早于 锚点-days 视为过期）")
        parser.add_argument("--dry-run", action="store_true",
                            help="只列候选并写报告，不执行归档")
        parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or DEFAULT_DATA_DIR,
                            help="数据目录（默认 ./data）")
        parser.add_argument("--report", default="",
                            help="jsonl 报告路径（默认 data/reports/archive_stale/<ts>.jsonl）")
    return parser
