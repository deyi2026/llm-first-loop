"""CLI 最小启动入口（design.md §2.4.2 / P1 批次1 多会话管理 T26）.

- 单条消息: python -m llm_loop.cli "消息"
- 交互模式: python -m llm_loop.cli --interactive
- 会话管理（T26）: list / delete / archive / unarchive / search / --session <id> 复用
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

from llm_loop.config import load_env_file, load_settings
from llm_loop.core.session import (
    SessionExternalResourceBusyError,
    SessionMutationBusyError,
    SessionStore,
)
from llm_loop.runtime.installation import bundle_root
from llm_loop.runtime.resolver import apply_to_environ, legacy_env_snapshot
from llm_loop.terminal.approval import ApprovalBridge
from llm_loop.terminal.execution import run_turn
from llm_loop.terminal.presentation import Presenter
from llm_loop.terminal.queries import HELP, dispatch_query
from llm_loop.terminal.shell import interactive_session
from llm_loop.timekeeping import system_local_now


def _run_single(engine, text: str, session_id: str | None = None) -> int:
    """Run once through the native stream; preserve the selected stdout protocol."""
    view = Presenter(
        getattr(engine, "_cli_output", "text"),
        stream=not getattr(engine, "_cli_no_stream", False),
        plain=getattr(engine, "_cli_plain", False),
    )
    store = engine.session
    if session_id and not store.exists(session_id):
        return view.error(f"Session not found: {session_id}", "session_not_found")
    sid = session_id or store.create()
    model = getattr(engine, "_cli_startup_model", None)
    if model and not _apply_cli_startup_model(engine, store, sid, model):
        if session_id is None:
            store.delete(sid)  # No run began; do not leave a new empty session.
        return view.error("Explicit startup model was not applied; no user run started.", "startup_model_failed")
    return run_turn(engine, sid, text, view)


def _apply_cli_startup_model(engine, session_store, session_id: str, model_ref: str) -> bool:
    """M50 启动参数 `--model` 落地: 复用 M48 切换路径, 写会话 override + 持久化.

    显式选模失败时不得继续以其他模型运行；调用者负责终止本次启动。
    """
    from llm_loop.introspection.model_command import handle_model_command

    ctx = getattr(engine, "correction_ctx", None)
    if ctx is None:
        print("[--model 启动失败] correction_ctx 缺失; 请改用 /model 交互指令切换。", file=sys.stderr)
        return False
    sess = session_store.load(session_id)
    session_store.save(sess)  # 确保会话 JSON 落盘存在
    # 强制 reload (load 一次后若 start 内已写入，需拿到 in-memory sess 引用)
    sess = session_store.load(session_id)
    result = handle_model_command(
        f"/model {model_ref}", ctx, sess, session_store, audit=None
    )
    if result is not None:
        print(result.reply, file=sys.stderr)
    return result is not None and result.success


def _cli_approval_prompt(tool_name: str, args_summary: str) -> bool:
    """T5a: 人工审批一次性 prompt（终端 y/N；无终端/异常 → 拒绝 fail-closed）."""
    if not sys.stdin.isatty():
        return False
    try:
        print(
            f"\n[人工审批] AI 请求执行被 EXEC_MODE 限制的操作:\n"
            f"  工具: {tool_name}\n  参数: {args_summary[:200]}"
        )
        answer = input("批准执行? [y/N]: ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False  # 无终端（重定向等）→ 拒绝


def _run_interactive(engine, session_id: str | None = None) -> int:
    """Interactive shell owns input and presentation; the core owns execution."""
    store = engine.session
    if session_id and not store.exists(session_id):
        print(f"Session not found: {session_id}", file=sys.stderr)
        return 1
    sid = session_id or store.create()
    model = getattr(engine, "_cli_startup_model", None)
    if model and not _apply_cli_startup_model(engine, store, sid, model):
        if session_id is None:
            store.delete(sid)  # Preserve existing sessions; clean up only this new one.
        return 1
    return interactive_session(engine, sid)


def _cmd_list(engine, include_archived: bool) -> int:
    metas = engine.session.list_sessions(include_archived=include_archived)
    if not metas:
        print("（暂无会话）")
        return 0
    print(f"{'ID':<12} {'标题':<32} {'消息数':<6} {'状态':<8} 更新时间")
    for m in metas:
        flag = " [归档]" if m.status == "archived" else ""
        print(
            f"{m.session_id[:10]:<12} {m.title[:30]:<32} {m.message_count:<6} {m.status:<8} {m.updated_at[:19]}{flag}"
        )
    return 0


def _cmd_delete(engine, session_id: str, yes: bool) -> int:
    from llm_loop.feedback.honesty import session_deleted_message

    meta = engine.session.get_meta(session_id)
    if meta is None:
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return 1
    # 展示待删元数据 + 交互确认（FR-P1-SES-04 禁止未确认删除）
    print(
        f"待删除会话: {session_id[:10]} | 标题: {meta.title} | 消息数: {meta.message_count} | 创建: {meta.created_at[:19]}"
    )
    if not yes:
        try:
            answer = input("确认删除该会话？此操作不可恢复 [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("已取消删除")
            return 1
        if answer != "y":
            print("已取消删除（输入非 y，未执行删除）")
            return 1
    try:
        deleted = engine.session.delete(session_id)
    except SessionExternalResourceBusyError as exc:
        print(f"[外部资源繁忙] {exc}")
        return 1
    except SessionMutationBusyError as exc:
        print(f"[会话繁忙] {exc}")
        return 1
    if deleted:
        print(session_deleted_message(session_id))
        return 0
    print("[删除失败] 事实: 无法删除会话。原因: 文件不存在或 IO 异常。建议: 检查后重试。")
    return 1


def _cmd_archive(engine, session_id: str, archived: bool) -> int:
    from llm_loop.feedback.honesty import session_archived_message

    try:
        ok = engine.session.archive(session_id) if archived else engine.session.unarchive(session_id)
    except SessionMutationBusyError as exc:
        print(f"[会话繁忙] {exc}")
        return 1
    if not ok:
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return 1
    print(session_archived_message(session_id, archived))
    return 0


def _cmd_search(engine, query: str) -> int:
    hits = engine.session.search(query)
    if not hits:
        print(f"[会话检索] 未找到匹配 '{query}' 的会话（如实返回，不伪造）")
        return 0
    print(f"[会话检索] 命中 {len(hits)} 个会话:")
    for h in hits:
        meta = h["meta"]
        print(
            f"  {meta.session_id[:10]} | {meta.title[:30]} | 命中: {h['location']} | {h['summary'][:60]}"
        )
    return 0


def _cmd_faults(args: list[str]) -> int:
    """faults: 工具回执故障台账聚合查询（A-⑤，EVO-20260924-40755734）.

    用法: llm_loop faults [--limit N] [--data-dir DIR]
    只读 exception_log.jsonl：按 (phase, error_type) 签名聚合 + 最近明细。
    """
    parser = argparse.ArgumentParser(prog="llm_loop faults")
    parser.add_argument("--limit", type=int, default=15, help="最近明细条数（默认 15）")
    parser.add_argument("--data-dir", help="数据目录（默认取项目配置 audit_dir）")
    ns = parser.parse_args(args)

    if ns.data_dir:
        ledger = Path(ns.data_dir) / "exception_log.jsonl"
    else:
        ledger = load_settings().audit_dir / "exception_log.jsonl"
    if not ledger.exists():
        print(f"[faults] {ledger} 不存在——尚无工具故障记录（如实返回）")
        return 0
    rows = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    if not rows:
        print("[faults] 台账为空——尚无工具故障记录")
        return 0
    sigs = Counter((str(r.get("phase", "?")), str(r.get("error_type", "?"))) for r in rows)
    print(f"[faults] 共 {len(rows)} 条（{ledger}）")
    print("按形态聚合 top:")
    for (phase, etype), n in sigs.most_common(10):
        print(f"  {n:>5}  {phase} · {etype}")
    print(f"最近 {min(ns.limit, len(rows))} 条:")
    for r in rows[-ns.limit :]:
        ts = str(r.get("ts", ""))
        print(
            f"  [{ts[11:19]}] {r.get('phase', '?')} {r.get('error_type', '?')}: "
            f"{str(r.get('error_message', ''))[:120]}"
        )
    return 0


def main(argv: list[str] | None = None, *, workspace_root: str | None = None) -> int:
    argv = list(argv) if argv is not None else list(sys.argv[1:])
    query_root = default_home() if bundle_root() else Path(__file__).resolve().parents[2]
    query = dispatch_query(argv, argparse.Namespace(
        config=None, data_dir=None, workspace=workspace_root, _query_home=query_root,
    ))
    if query is not None:
        return query
    # 手动分派子命令（避免 subparsers 吃掉位置参数 message）
    _cmds = {
        "list",
        "delete",
        "archive",
        "unarchive",
        "search",
        "extract",
        "fork",
        "rename",
        "evolve-list",
        "evolve-review",
        "evolve-complete",  # M17 FR-REVIEW-AI-01: 人工完成登记（涉边界演进）
        "evolve-verify",  # EVO-20260813-8279507f: 人工核验确认（executed → verified_at 标记）
        "export-distill",  # export_distill: 蒸馏数据集导出（薄壳只读，不装配 engine）
        "export-serve-mcp",  # P0-2: 只读导出 MCP server（stdio，不装配 engine）
        "event-inventory",  # D1: 存量存储盘点（只读，不装配 engine）
        "archive-index",  # R3: 压缩档案存量段索引重建（纯存储操作，不装配 engine）
        "event-migrate",  # D1: 存量迁移为事件日志（纯存储操作，不装配 engine）
        "event-verify",  # D1: 事件重放 vs 源逐字段校验（只读，不装配 engine）
        "event-rollback",  # D1: 从备份恢复源数据（纯存储操作，不装配 engine）
        "session-fork",  # D3: 会话 fork（事件日志物理复制 + session JSON 双轨，不装配 engine）
        "event-retire",  # D1后续批次2: 三套存储退役（对账+归档+读路径切换）
        "event-retire-rollback",  # D1后续批次2: 退役回滚
        "event-rotate-status",  # D1后续批次3:, 事件日志滚动段清单
        "event-hooks",  # D1后续批次4: pre-step 过滤钩子管理
        "faults",  # A-⑤（EVO-20260924-40755734）: 工具故障台账聚合查询（只读，不装配 engine）
    }
    if argv and argv[0] in _cmds:
        _prepare_cli_process()
        return _dispatch_command(argv, workspace_root=workspace_root)

    parser = argparse.ArgumentParser(prog="llm_loop", description="LLM-First Core Loop")
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
        "--model",
        dest="model",
        default="",
        help="M50: 启动时为会话装配模型（provider/model 或裸模型名；与 Web /model 一致, 复用同一 session override）",
    )
    args = parser.parse_args(argv)
    inputs = int(args.message is not None) + int(args.stdin) + int(args.message_file is not None)
    if inputs > 1 or (args.interactive and inputs):
        print("请选择一种输入方式：消息、--stdin、--message-file 或 --interactive。", file=sys.stderr)
        return 2
    interactive = inputs == 0
    if interactive and args.output != "text":
        print("Structured output requires an explicit message, --stdin or --message-file.", file=sys.stderr)
        return 2
    if interactive and not (sys.stdin and sys.stdin.isatty()):
        print("交互模式需要终端；管道输入请使用 --stdin。", file=sys.stderr)
        return 2
    try:
        message = args.message
        if args.stdin:
            message = _read_stdin_exact()
        elif args.message_file is not None:
            with Path(args.message_file).open(encoding="utf-8", newline="") as source:
                message = source.read()
    except (OSError, UnicodeError) as exc:
        print(f"无法读取消息输入（{type(exc).__name__}）；请检查文件和编码。", file=sys.stderr)
        return 2
    if not interactive and (message is None or not message.strip()):
        print("消息输入为空，未启动运行。", file=sys.stderr)
        return 2

    _prepare_cli_process()

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    from llm_loop.factory import build_engine

    engine: Any = build_engine(settings) if workspace_root is None else build_engine(settings, workspace_root=workspace_root)
    # P2-4(2026-08-15): 主返回路径 try/finally 保证 engine.close()（释放 LLM httpx 连接，
    # fail-open 幂等，见 LoopEngine.close）。覆盖 main() 全部 return 出口
    # （单条消息模式 / 交互模式退出）。
    try:
        # M50: 启动参数 --model 转入引擎属性, 由 _run_single / _run_interactive 落地
        if args.model:
            engine._cli_startup_model = args.model  # noqa: SLF001 — 私有装配通道

        # T5a: 交互模式注入人工审批回调（EXEC_MODE 拦截项可经终端确认放行；
        # 单条消息模式/web/feishu 不注入 → 拦截即拒绝 fail-closed）
        engine._cli_output = args.output
        engine._cli_plain = args.plain
        engine._cli_no_stream = args.no_stream
        engine._cli_theme = args.theme
        engine._cli_workspace = workspace_root or str(Path.cwd())
        if interactive:
            bridge = ApprovalBridge()
            engine._cli_approval_bridge = bridge
            engine.registry.set_approval_callback(bridge)

        if not interactive:
            assert message is not None
            return _run_single(engine, message, session_id=args.session)
        return _run_interactive(engine, session_id=args.session)
    finally:
        # P2-4(2026-08-15): 关闭引擎（含 LLM httpx 连接；fail-open 幂等，不遮蔽返回值）
        engine.close()


def _read_stdin_exact() -> str:
    """Read one UTF-8 stdin message without universal-newline rewriting."""
    stream = sys.stdin
    binary = getattr(stream, "buffer", None)
    if binary is None:
        # In-memory streams used by embedders/tests are already text and have no
        # newline translation unless their owner explicitly applied it.
        return stream.read()
    return binary.read().decode("utf-8")


def _prepare_cli_process() -> None:
    """Load selected config and register identity only after input validation."""
    from llm_loop.config import load_env_file
    from llm_loop.introspection.proc_version import record_process_start

    env_file = legacy_env_snapshot().get("LFL_ENV_FILE")
    load_env_file(env_file) if env_file else load_env_file()
    record_process_start("cli")


def _dispatch_command(argv: list[str], *, workspace_root: str | None = None) -> int:
    """子命令分派（list/delete/archive/unarchive/search/extract）."""
    cmd = argv[0]
    # export_distill: 薄壳纯读命令，入口特判（早于 build_engine，避免无谓 engine 装配）
    if cmd == "export-distill":
        return _cmd_export_distill(argv[1:])
    # P0-2: 只读导出 MCP server（stdio），薄壳特判（不装配 engine，无 LLM 凭证依赖）
    if cmd == "export-serve-mcp":
        from llm_loop.export.mcp_server import main as _serve_export_main

        return _serve_export_main(argv[1:])
    # D1: event-* 纯存储/只读命令，入口特判（早于 build_engine，避免无谓 LLM 装配）
    if cmd == "event-inventory":
        return _cmd_event_inventory(argv[1:])
    if cmd == "archive-index":
        return _cmd_archive_index(argv[1:])
    if cmd == "event-migrate":
        return _cmd_event_migrate(argv[1:])
    if cmd == "event-verify":
        return _cmd_event_verify(argv[1:])
    if cmd == "event-rollback":
        return _cmd_event_rollback(argv[1:])
    if cmd == "session-fork":
        return _cmd_session_fork(argv[1:])
    if cmd == "event-retire":
        return _cmd_event_retire(argv[1:])
    if cmd == "event-retire-rollback":
        return _cmd_event_retire_rollback(argv[1:])
    if cmd == "event-rotate-status":
        return _cmd_event_rotate_status(argv[1:])
    if cmd == "event-hooks":
        return _cmd_event_hooks(argv[1:])
    if cmd == "faults":
        return _cmd_faults(argv[1:])
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    from llm_loop.factory import build_engine

    engine = build_engine(settings) if workspace_root is None else build_engine(settings, workspace_root=workspace_root)
    # P2-4(2026-08-15): 子命令分派同样装配 engine（持有 LLM httpx 连接），
    # 统一 try/finally 在退出前 close（fail-open 幂等）——覆盖本分派全部 return 出口。
    def _dispatch() -> int:
        if cmd == "list":
            return _cmd_list(engine, "--archived" in argv)
        if cmd == "delete":
            if len(argv) < 2:
                print("用法: llm_loop delete <session_id> [--yes]")
                return 2
            return _cmd_delete(engine, argv[1], "--yes" in argv)
        if cmd == "archive":
            if len(argv) < 2:
                print("用法: llm_loop archive <session_id>")
                return 2
            return _cmd_archive(engine, argv[1], True)
        if cmd == "unarchive":
            if len(argv) < 2:
                print("用法: llm_loop unarchive <session_id>")
                return 2
            return _cmd_archive(engine, argv[1], False)
        if cmd == "search":
            if len(argv) < 2:
                print("用法: llm_loop search <query>")
                return 2
            return _cmd_search(engine, " ".join(argv[1:]))
        if cmd == "extract":
            if len(argv) < 2:
                print("用法: llm_loop extract <session_id>")
                return 2
            return _cmd_extract(engine, argv[1])
        if cmd == "rename":
            if len(argv) < 3:
                print("用法: llm_loop rename <session_id> \"<新标题>\"")
                return 2
            return _cmd_rename(engine, argv[1], " ".join(argv[2:]))
        if cmd == "fork":
            if len(argv) < 2:
                print("用法: llm_loop fork <session_id> [--at <索引>] [--summary \"<摘要>\"]")
                return 2
            at = None
            summary = ""
            rest = argv[2:]
            for i, tok in enumerate(rest):
                if tok == "--at" and i + 1 < len(rest):
                    try:
                        at = int(rest[i + 1])
                    except ValueError:
                        print("❌ --at 需为整数", file=sys.stderr)
                        return 2
                elif tok == "--summary" and i + 1 < len(rest):
                    summary = rest[i + 1]
            return _cmd_fork(engine, argv[1], at=at, summary=summary)
        if cmd == "evolve-list":
            return _cmd_evolve_list(engine, argv[1] if len(argv) > 1 else None)
        if cmd == "evolve-review":
            extra = [a for a in argv[3:] if a]
            authorize = "--authorize-exec" in extra
            unknown = [a for a in extra if a != "--authorize-exec"]
            if len(argv) < 3 or unknown:
                print("用法: llm_loop evolve-review <suggestion_id> <accepted|rejected> [--authorize-exec]")
                return 2
            return _cmd_evolve_review(engine, argv[1], argv[2], authorize)
        if cmd == "evolve-complete":
            if len(argv) < 3:
                print('用法: llm_loop evolve-complete <suggestion_id> "<执行结果说明>"')
                return 2
            return _cmd_evolve_complete(engine, argv[1], " ".join(argv[2:]))
        if cmd == "evolve-verify":
            if len(argv) < 3:
                print('用法: llm_loop evolve-verify <suggestion_id> "<核验说明>"')
                return 2
            return _cmd_evolve_verify(engine, argv[1], " ".join(argv[2:]))
        return 2

    try:
        return _dispatch()
    finally:
        # P2-4(2026-08-15): 子命令分派退出前统一关闭引擎（fail-open 幂等，不遮蔽返回值）
        engine.close()


def _cmd_evolve_list(engine, status: str | None) -> int:
    """列出演进建议（人工审阅入口，M12 T52）."""
    store = getattr(engine.correction_ctx, "evolution_store", None)
    if store is None:
        print("[演进建议不可用] EVOLVE_ENABLED=0")
        return 1
    items = store.list(status=status)
    if not items:
        print("（暂无演进建议）")
        return 0
    for it in items:
        human = " [需人工决策]" if it.get("requires_human") else ""
        scope = it.get("scope", "global")
        scope_mark = " [session级]" if scope == "session" else ""
        verify_mark = ""
        if it.get("status") == "executed":
            verify_mark = " [已核验]" if it.get("verified_at") else " [待核验]"
        print(
            f"  {it['id']} | {it['status']} | {it.get('priority')} | {it.get('content', '')[:50]}{human}{scope_mark}{verify_mark}"
        )
    return 0


def _cmd_evolve_review(engine, suggestion_id: str, decision: str, authorize_exec: bool = False) -> int:
    """人工审阅演进建议（accepted/rejected，EVOLVE-05 闭环；T60: accepted 自动触发执行）.

    --authorize-exec（方案A EVO-20260929）: accepted 时显式授权自动执行（越过
    requires_human/_touches_boundary 边界拦截，仍过权限级别门禁）；对已 accepted
    条目可补授权（幂等重审 accepted + 落 human_exec_override 审计字段）。
    """
    store = getattr(engine.correction_ctx, "evolution_store", None)
    if store is None:
        print("[演进建议不可用] EVOLVE_ENABLED=0")
        return 1
    try:
        target = store.review(suggestion_id, decision, exec_override=authorize_exec)
    except ValueError as exc:
        print(f"[参数错误] {exc}")
        return 2
    if target is None:
        print(f"[建议不存在] 未找到 {suggestion_id}")
        return 1
    suffix = "（已显式授权自动执行）" if (authorize_exec and decision == "accepted") else ""
    print(f"[审阅完成] {suggestion_id} → {target['status']}{suffix}: {target.get('content', '')[:80]}")
    # T60: accepted 且权限允许 → 自动触发执行（EXEC-02）
    if decision == "accepted":
        _maybe_auto_execute(engine, store, target)
    return 0


def _cmd_evolve_verify(engine, suggestion_id: str, note: str) -> int:
    """人工核验确认（EVO-20260813-8279507f）: executed → verified_at + verify_note.

    幂等: 已核验则跳过（不重复覆盖）。仅 executed 状态可核验（未执行完的不核验）。
    实现: 保持 executed 终态不变，附加 verified_at/verify_note 字段（最小侵入，不破坏状态机）。
    """
    store = getattr(engine.correction_ctx, "evolution_store", None)
    if store is None:
        print("[演进建议不可用] EVOLVE_ENABLED=0")
        return 1
    entry = next((it for it in store.list() if it.get("id") == suggestion_id), None)
    if entry is None:
        print(f"[建议不存在] 未找到 {suggestion_id}")
        return 1
    if entry.get("status") != "executed":
        print(f"[不可核验] {suggestion_id} 当前状态 {entry.get('status')}，仅 executed 可核验")
        return 2
    if entry.get("verified_at"):
        print(f"[已核验（幂等跳过）] {suggestion_id} 已于 {entry['verified_at']} 核验")
        return 0

    now = system_local_now().isoformat(timespec="seconds")
    store.transition(suggestion_id, status="executed", verified_at=now, verify_note=note)
    print(f"[核验完成] {suggestion_id} → executed（verified_at={now}）: {note}")
    return 0


def _cmd_export_distill(argv: list[str]) -> int:
    """export-distill 子命令入口（薄壳只读，不装配 engine）.

    导出带思考链的 ReAct 蒸馏数据集（`data/sessions/*.json` → JSONL + 统计报告）。
    用法: llm_loop export-distill [--input-dir DIR] [--output FILE] [--report FILE] [--force]
    """

    from llm_loop.introspection.export_distill import run_export

    data = Path(legacy_env_snapshot().get("DATA_DIR") or "data")
    default_input = str(data / "sessions") + os.sep

    parser = argparse.ArgumentParser(
        prog="llm_loop export-distill",
        description="导出带思考链的 ReAct 蒸馏数据集（薄壳只读，不装配 engine）",
    )
    parser.add_argument(
        "--input-dir",
        default=default_input,
        help=f"会话输入目录（默认 {default_input}）",
    )
    parser.add_argument(
        "--output",
        default="",
        help="JSONL 输出路径（默认 data/export_distill/distill_<YYYYmmdd-HHMMSS>.jsonl）",
    )
    parser.add_argument(
        "--report",
        default="",
        help="统计报告路径（默认同输出目录 report_<YYYYmmdd-HHMMSS>.json）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖既有输出文件（默认拒绝已存在的输出，杜绝静默追加）",
    )
    args = parser.parse_args(argv)

    ts = system_local_now().strftime("%Y%m%d-%H%M%S")
    output = args.output or str(data / "export_distill" / f"distill_{ts}.jsonl")
    report_path = args.report or str(data / "export_distill" / f"report_{ts}.json")

    try:
        report = run_export(args.input_dir, output, report_path, force=args.force)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — 内部异常如实反馈
        print(f"❌ 导出失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print(report.render_text())
    print(f"[数据集] {output}")
    print(f"[报告] {report_path}")
    return 0


# ── D1 事件源化 CLI 子命令（event-*，纯存储/只读操作，不装配 engine）──

_DEFAULT_DATA_DIR = "./data"


def _cmd_archive_index(argv: list[str]) -> int:
    """R3: 压缩档案存量段 sidecar 索引重建（幂等；不装配 engine）.

    用法: llm_loop archive-index [--data-dir DIR]
    为 archives/ 下全部段文件（含存量无索引段）重建 .idx，检索从全文扫描提速到索引路径。
    """
    from llm_loop.memory.archive import ArchiveStore

    parser = argparse.ArgumentParser(
        prog="llm_loop archive-index",
        description="压缩档案存量段索引重建（幂等，可重复执行）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    args = parser.parse_args(argv)

    try:
        store = ArchiveStore(
            Path(args.data_dir) / "archives",
            segment_bytes=getattr(load_settings(), "archive_segment_bytes", 0),
        )
        report = store.rebuild_all_indexes()
    except Exception as exc:  # noqa: BLE001 — 重建异常如实反馈
        print(f"❌ 索引重建失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print(
        f"✅ 档案索引重建完成: {report['segments']} 段 / {report['entries']} 条目"
        + (f"（{report['failed']} 段失败）" if report["failed"] else "")
    )
    return 0


def _cmd_event_inventory(argv: list[str]) -> int:
    """event-inventory: 三套存量存储只读盘点（spec §5.1）.

    用法: llm_loop event-inventory [--data-dir DIR]
    """
    from llm_loop.event_log.inventory import run_inventory

    parser = argparse.ArgumentParser(
        prog="llm_loop event-inventory",
        description="存量存储只读盘点（sessions/archives/compressed_archive/action_trace）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    args = parser.parse_args(argv)

    try:
        report = run_inventory(args.data_dir)
    except Exception as exc:  # noqa: BLE001 — 盘点异常如实反馈
        print(f"❌ 盘点失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print(report.render_text())
    return 0


def _cmd_event_migrate(argv: list[str]) -> int:
    """event-migrate: 存量会话迁移为事件日志（备份→迁移→校验闭环，幂等）.

    用法: llm_loop event-migrate [--data-dir DIR] [--force]
    """
    from llm_loop.event_log.migrate import run_migration

    parser = argparse.ArgumentParser(
        prog="llm_loop event-migrate",
        description="存量会话 → 事件日志迁移（备份先行、幂等、迁移后校验闭环）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument(
        "--force", action="store_true", help="跳过幂等检查强制重建既有事件日志（修复不一致）"
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    try:
        report = run_migration(
            f"{data_dir}/sessions",
            f"{data_dir}/event_logs",
            force=args.force,
        )
    except Exception as exc:  # noqa: BLE001 — 迁移异常如实反馈
        print(f"❌ 迁移失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print(report.render_text())
    return 0 if len(report.failed) == 0 else 1


def _cmd_event_verify(argv: list[str]) -> int:
    """event-verify: 事件重放 vs 源 session 逐字段校验（只读，闭环对账）.

    用法: llm_loop event-verify [--data-dir DIR] [--session <sid>|--all]
    """
    from llm_loop.event_log.reconcile import reconcile
    from llm_loop.event_log.replay import replay_session
    from llm_loop.event_log.store import EventStore, _validate_session_id

    parser = argparse.ArgumentParser(
        prog="llm_loop event-verify",
        description="事件重放 vs 源 session 逐字段校验（通过+失败=总数闭环）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--session", default="", help="单会话校验（默认全部）")
    group.add_argument("--all", action="store_true", help="全量校验（默认行为）")
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    sessions_dir = f"{data_dir}/sessions"
    store = EventStore(f"{data_dir}/event_logs")
    passed = 0
    failed: list[dict] = []
    import json
    import time

    targets: list[str] = []
    if args.session:
        try:
            _validate_session_id(args.session)
        except ValueError as exc:
            print(f"❌ 参数错误: {exc}", file=sys.stderr)
            return 2
        targets = [args.session]
    else:
        targets = sorted(p.stem for p in Path(sessions_dir).glob("*.json")) if Path(
            sessions_dir
        ).is_dir() else []

    if not targets:
        print(f"❌ 无会话可校验（目录: {sessions_dir}）", file=sys.stderr)
        return 1

    for sid in targets:
        src_path = Path(sessions_dir) / f"{sid}.json"
        if not src_path.is_file():
            failed.append({"session_id": sid, "reason": "源会话不存在"})
            continue
        try:
            source = json.loads(src_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            failed.append({"session_id": sid, "reason": f"源解析失败: {exc}"})
            continue
        try:
            start = time.monotonic()
            events = store.read(sid)
            derived = replay_session(events)
            if derived.get("exists") is False:
                failed.append({"session_id": sid, "reason": "事件日志不存在（未迁移）"})
                continue
            report = reconcile(derived, source, replay_ms=(time.monotonic() - start) * 1000)
        except Exception as exc:  # noqa: BLE001 — 单会话校验异常如实标注，不中断整体（fail-open）
            failed.append({"session_id": sid, "reason": f"校验异常: {type(exc).__name__}: {exc}"})
            continue
        if report.passed:
            passed += 1
        else:
            failed.append(
                {
                    "session_id": sid,
                    "reason": (
                        f"不一致: 顶层差异 {len(report.top_level_diffs)} / 消息差异 "
                        f"{len(report.message_diffs)} / 缺口 {report.gap_count} / "
                        f"未知类型 {report.unknown_events}"
                    ),
                }
            )

    print("【事件日志校验报告】")
    print(f"- 通过: {passed} / 失败: {len(failed)}（总数 {len(targets)}，闭环对账）")
    for f in failed:
        print(f"    - {f.get('session_id')}: {f.get('reason')}")
    return 0 if not failed else 1


def _cmd_event_rollback(argv: list[str]) -> int:
    """event-rollback: 从备份区恢复源数据（可选项清除迁移事件日志）.

    用法: llm_loop event-rollback [--data-dir DIR] [--session <sid>|--all] [--remove-events]
    """
    from llm_loop.event_log.migrate import run_rollback

    parser = argparse.ArgumentParser(
        prog="llm_loop event-rollback",
        description="从备份区恢复源 session JSON（--remove-events 时清除迁移事件日志）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument("--session", default="", help="单会话回滚（默认全部备份）")
    parser.add_argument(
        "--remove-events", action="store_true", help="同时清除对应事件日志（需操作者显式确认）"
    )
    args = parser.parse_args(argv)

    data_dir = args.data_dir
    event_logs_dir = Path(f"{data_dir}/event_logs")
    backups = sorted((event_logs_dir / "_backup").glob("*")) if (event_logs_dir / "_backup").is_dir() else []
    if not backups:
        print("❌ 无备份区可回滚", file=sys.stderr)
        return 1
    backup_dir = backups[-1]  # 默认最近一次迁移备份
    session_ids = [args.session] if args.session else None

    try:
        result = run_rollback(
            backup_dir,
            event_logs_dir,
            session_ids=session_ids,
            remove_events=args.remove_events,
        )
    except Exception as exc:  # noqa: BLE001 — 回滚异常如实反馈
        print(f"❌ 回滚失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print("【事件日志回滚报告】")
    print(f"- 备份区: {backup_dir}")
    print(f"- 恢复会话: {len(result['restored'])}（{', '.join(result['restored'][:5])}{'…' if len(result['restored']) > 5 else ''}）")
    print(f"- 清除事件: {len(result['events_removed'])}")
    if result["errors"]:
        print(f"- 错误（如实标注）: {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")
    return 0 if not result["errors"] else 1


def _cmd_session_fork(argv: list[str]) -> int:
    """session-fork: 会话 fork（事件日志物理复制 + session JSON 双轨，不装配 engine）.

    用法: llm_loop session-fork --session <sid> [--data-dir DIR] [--fork-point N] [--summary "..."]
    """
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.fork import fork_session
    from llm_loop.event_log.store import EventStore

    parser = argparse.ArgumentParser(
        prog="llm_loop session-fork",
        description="会话 fork（事件日志物理复制继承 + session JSON 双轨）",
    )
    parser.add_argument("--session", required=True, help="源会话 ID")
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument("--fork-point", type=int, default=None, help="fork 点（保留前 N 条消息；缺省=全部）")
    parser.add_argument("--summary", default="", help="分支摘要（缺省自动提炼）")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    data_dir = args.data_dir
    event_store = EventStore(
        Path(f"{data_dir}/event_logs"),
        enabled=settings.event_log_enabled,
    )
    session_store = SessionStore(
        Path(f"{data_dir}/sessions"),
        event_store=event_store,
    )

    try:
        report = fork_session(
            event_store,
            session_store,
            args.session,
            fork_point=args.fork_point,
            branch_summary=args.summary,
        )
    except Exception as exc:  # noqa: BLE001 — fork 异常如实反馈
        print(f"❌ fork 失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1

    if not report.success:
        print(f"❌ {report.error}", file=sys.stderr)
        return 1
    print(f"✅ 已从会话 {args.session[:10]}… fork 出新分支: {report.new_session_id}")
    print(f"   继承事件数: {report.inherited_event_count}")
    print(f"   fork 点: {report.fork_point}")
    print(f"   耗时: {report.elapsed_ms}ms")
    print(f"   继续使用: llm_loop --session {report.new_session_id} <消息>")
    return 0


def _cmd_event_retire(argv: list[str]) -> int:
    """event-retire: 三套存储退役（对账+归档+读路径切换）.

    用法: llm_loop event-retire [--data-dir DIR] [--force]
    """
    from llm_loop.event_log.retire import run_retire

    parser = argparse.ArgumentParser(
        prog="llm_loop event-retire",
        description="三套存储退役（双轨对账前置 + 归档 + 读路径切换）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument("--force", action="store_true", help="跳过幂等检查强制退役")
    args = parser.parse_args(argv)

    try:
        report = run_retire(args.data_dir, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 退役失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    if report.error:
        print(f"❌ {report.error}", file=sys.stderr)
        return 1
    print("【三套存储退役报告】")
    print(f"- 退役步骤: {' → '.join(report.retired_steps)}")
    print(f"- 双轨对账: {'通过' if report.reconcile_passed else '失败'}")
    if report.reconcile_diffs:
        print(f"  对账差异（{len(report.reconcile_diffs)} 项）:")
        for d in report.reconcile_diffs[:5]:
            print(f"    - {d}")
    print(f"- 读路径切换就绪: {'是' if report.read_path_ready_to_switch else '否'}")
    if report.switch_instructions:
        print("- 人工切换指引（程序不替改 .env，切换需人工+重启）:")
        for s in report.switch_instructions:
            print(f"    {s}")
    print(f"- 归档清单: {', '.join(report.archived_files) or '无'}")
    print(f"- 备份区: {report.backup_dir}")
    print(f"- 耗时: {report.elapsed_s}s")
    print(f"- 回滚入口: llm_loop event-retire-rollback --data-dir {args.data_dir} --backup-dir {report.backup_dir}")
    return 0


def _cmd_event_retire_rollback(argv: list[str]) -> int:
    """event-retire-rollback: 从备份区恢复源文件 + 读路径切回.

    用法: llm_loop event-retire-rollback --data-dir DIR --backup-dir <dir>
    """
    from llm_loop.event_log.retire import run_retire_rollback

    parser = argparse.ArgumentParser(
        prog="llm_loop event-retire-rollback",
        description="从备份区恢复源 session JSON + action_trace",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument("--backup-dir", required=True, help="备份区目录")
    args = parser.parse_args(argv)

    try:
        result = run_retire_rollback(args.backup_dir, args.data_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 回滚失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 1
    print("【退役回滚报告】")
    print(f"- 恢复项: {', '.join(result['restored']) or '无'}")
    if result["errors"]:
        print(f"- 错误: {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")
    print("- 读路径回退（程序不替改 .env，需人工操作）:")
    print("    1. 编辑 .env：设置 READ_PATH_SOURCE=session_json")
    print("    2. 重启服务：bash scripts/restart_system.sh restart")
    return 0 if not result["errors"] else 1


def _cmd_event_rotate_status(argv: list[str]) -> int:
    """event-rotate-status: 事件日志滚动段清单.

    用法: llm_loop event-rotate-status [--data-dir DIR] [--session <sid>]
    """
    from llm_loop.event_log.rotate import RotateManager

    parser = argparse.ArgumentParser(
        prog="llm_loop event-rotate-status",
        description="事件日志滚动段清单（序号/事件数/时间范围/大小/活跃状态）",
    )
    parser.add_argument("--data-dir", default=legacy_env_snapshot().get("DATA_DIR") or _DEFAULT_DATA_DIR, help="数据目录（默认 ./data）")
    parser.add_argument("--session", default="", help="单会话段清单（缺省列出全部多段会话）")
    args = parser.parse_args(argv)

    event_logs_dir = Path(f"{args.data_dir}/event_logs")
    if args.session:
        segments = RotateManager.list_segments(event_logs_dir, args.session)
        if not segments:
            print(f"会话 {args.session} 无多段事件日志（单文件或不存在）")
            return 0
        print(f"【会话 {args.session} 段清单】")
        for s in segments:
            active = "活跃" if s.is_active else "归档"
            print(f"  段 {s.segment_seq}: {s.event_count} 事件, {s.size_bytes}B, {active}")
        return 0
    multi_sessions = [p.name for p in event_logs_dir.iterdir() if p.is_dir() and not p.name.startswith("_")]
    if not multi_sessions:
        print("无多段事件日志会话")
        return 0
    print(f"【多段会话清单】（{len(multi_sessions)} 个）")
    for sid in sorted(multi_sessions):
        segments = RotateManager.list_segments(event_logs_dir, sid)
        total = sum(s.event_count for s in segments)
        print(f"  {sid}: {len(segments)} 段, {total} 事件")
    return 0


def _cmd_event_hooks(argv: list[str]) -> int:
    """event-hooks: pre-step 过滤钩子管理.

    用法: llm_loop event-hooks {list,test} [--event <json>]
    """
    parser = argparse.ArgumentParser(
        prog="llm_loop event-hooks",
        description="pre-step 过滤钩子管理（list/test）",
    )
    parser.add_argument("subcommand", choices=["list", "test"], help="子命令")
    parser.add_argument("--event", default="", help="测试事件 JSON（test 子命令）")
    args = parser.parse_args(argv)

    if args.subcommand == "list":
        print("【已注册钩子】")
        print("（钩子注册通过 EVENT_HOOKS_CONFIG 配置文件或代码内 HookRegistry.register）")
        return 0
    if args.subcommand == "test":
        if not args.event:
            print("❌ 缺少 --event 参数", file=sys.stderr)
            return 2
        import json as _json

        try:
            data = _json.loads(args.event)
        except _json.JSONDecodeError as exc:
            print(f"❌ 事件 JSON 解析失败: {exc}", file=sys.stderr)
            return 2
        from llm_loop.event_log.hooks import HookChain
        from llm_loop.event_log.model import Event

        event = Event(
            event_id=data.get("event_id", "test"),
            session_id=data.get("session_id", "test"),
            seq=data.get("seq", 1),
            type=data.get("type", ""),
            ts=data.get("ts", ""),
            payload=data.get("payload", {}),
        )
        chain = HookChain([])  # 空链测试
        processed, audits = chain.process(event)
        print(f"处理结果: {'被过滤' if processed is None else '保留'}")
        print(f"审计记录: {len(audits)}")
        return 0
    return 0


def _cmd_evolve_complete(engine, suggestion_id: str, result: str) -> int:
    """人工完成演进执行标记（M17 FR-REVIEW-AI-01: 涉边界 accepted/executing 演进 → executed, executor=human）."""
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    store = getattr(engine.correction_ctx, "evolution_store", None)
    if store is None:
        print("[演进建议不可用] EVOLVE_ENABLED=0")
        return 1
    if not result.strip():
        print('[参数错误] 请提供执行结果说明（evolve-complete <id> "<执行结果说明>"）')
        return 2
    executor = EvolutionExecutor(
        exec_level=int(getattr(engine.correction_ctx, "evolve_local_exec", 0) or 0),
        store=store,
        audit_dir=getattr(engine.settings, "audit_dir", None),
    )
    outcome = executor.manual_complete(suggestion_id, result)
    print(
        f"[执行完成登记] {suggestion_id} → {outcome.status}（executor={outcome.executor} "
        f"verify={outcome.verify_result}）: {outcome.note[:120]}"
    )
    return 0


def _maybe_auto_execute(engine, store, target: dict) -> None:
    """accepted 后按权限分级自动执行（can_auto_exec → EvolutionExecutor，T60）.

    薄包装：逻辑已提取公共函数 maybe_auto_execute_from_engine（EVO 飞书审批 UX，
    CLI/飞书共用防分叉）。"""
    from llm_loop.introspection.evolution_exec import maybe_auto_execute_from_engine

    print(maybe_auto_execute_from_engine(engine, store, target))


def _cmd_extract(engine, session_id: str) -> int:
    """手动触发独立记忆提取（T33 实现后接线）."""
    extractor = getattr(engine, "extractor", None)
    if extractor is None:
        print(
            "[独立提取不可用] 事实: 独立记忆提取未装配。原因: EXTRACT_ENABLED=0。建议: 检查配置。"
        )
        return 1
    if not engine.session.exists(session_id):
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return 1
    result = extractor.extract_session(session_id, trigger="manual")
    print(
        f"[独立提取完成] 触发=manual 条目={len(result.entries)} 跳过重复={result.skipped_duplicates} 失败={len(result.records and result.records[-1].failures or [])}"
    )
    return 0


# ── EVO-20260810-3188682f: 会话分支 ──
def _cmd_fork(engine, session_id: str, *, at: int | None, summary: str) -> int:
    """分叉会话：从指定会话创建新分支（旧会话不覆盖不删除）.

    用法: llm_loop fork <session_id> [--at <索引>] [--summary "<摘要>"]
    - --at: 分叉点（消息索引，新分支仅保留此前消息）；缺省=父会话末尾（克隆当前状态）
    - --summary: 分支摘要；缺省自动提炼（分叉点后最近 assistant 消息）
    """
    store: SessionStore = engine.session
    if not store.exists(session_id):
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return 2
    try:
        new_id = store.fork(session_id, branch_point_index=at, branch_summary=summary)
    except Exception as exc:  # noqa: BLE001 — 分叉失败如实反馈
        print(f"❌ 分叉失败（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2
    sess = store.load(new_id)
    print(f"✅ 已从会话 {session_id[:10]} 分叉出新分支: {new_id}")
    print(f"   标题: {sess.title or '未命名'}")
    print(f"   消息数: {len(sess.messages)}")
    if sess.branch_summary:
        print(f"   分支摘要: {sess.branch_summary[:80]}")
    print(f"   继续使用: llm_loop --session {new_id} <消息>")
    return 0





# ── 管理完善: 会话重命名 ──
def _cmd_rename(engine, session_id: str, new_title: str) -> int:
    """重命名会话标题（web 列表可识别，减少"未命名"混乱）.

    用法: llm_loop rename <session_id> "<新标题>"
    """
    store: SessionStore = engine.session
    try:
        renamed = store.rename(session_id, new_title)
    except SessionMutationBusyError as exc:
        print(f"[会话繁忙] {exc}", file=sys.stderr)
        return 2
    if renamed:
        meta = store.get_meta(session_id)
        print(f"✅ 已重命名: {session_id[:10]} → {meta.title if meta else new_title}")
        return 0
    if not store.exists(session_id):
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return 2
    print("❌ 重命名失败（新标题为空）", file=sys.stderr)
    return 2

def default_home() -> Path:
    values = legacy_env_snapshot()
    if raw := values.get("LFL_HOME", "").strip():
        return Path(raw).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LFL"
    if sys.platform == "win32":
        return Path(values.get("LOCALAPPDATA") or Path.home() / "AppData/Local") / "LFL"
    raw = values.get("XDG_DATA_HOME", "")
    base = Path(raw).expanduser() if raw else Path.home() / ".local/share"
    return (base if base.is_absolute() else Path.home() / ".local/share") / "lfl"


def prepare_environment(args: argparse.Namespace) -> dict[str, str]:
    """Bind installed state/resources explicitly; never copy credentials into a bundle."""
    bundle = bundle_root()
    values = legacy_env_snapshot()
    root = default_home() if bundle else Path(__file__).resolve().parents[2]
    config = Path(args.config or values.get("LFL_ENV_FILE") or root / ".env").expanduser().resolve()
    if args.config and not config.is_file():
        raise ValueError(f"Configuration file does not exist: {config}")
    existing_keys = set(values)
    existing_data = values.get("DATA_DIR") or values.get("LFL_DATA_DIR")
    load_env_file(config)
    values = legacy_env_snapshot()
    normalized = {}
    for key in (
        "DATA_DIR", "LFL_DATA_DIR", "LFL_RUNTIME_ROOT", "LFL_WORKSPACE_ROOT",
        "SKILLS_DIR", "METHOD_SEED_DIR", "DOCS_DIR", "UI_V2_DIR",
        "EXPERIENCES_DIR", "METHODS_DIR",
    ):
        raw = values.get(key, "")
        if key not in existing_keys and raw and not Path(raw).expanduser().is_absolute():
            values[key] = str((config.parent / raw).expanduser().resolve())
            normalized[key] = values[key]
    data_raw = args.data_dir or existing_data or values.get("DATA_DIR") or values.get("LFL_DATA_DIR")
    data = Path(data_raw or root / "data").expanduser().resolve()
    workspace = Path(args.workspace or values.get("LFL_WORKSPACE_ROOT") or Path.cwd()).expanduser().resolve()
    bindings = {
        "DATA_DIR": str(data),
        "LFL_DATA_DIR": str(data),
        "LFL_ENV_FILE": str(config),
        "LFL_RUNTIME_ROOT": str(Path(values.get("LFL_RUNTIME_ROOT") or root).expanduser().resolve()),
        "LFL_WORKSPACE_ROOT": str(workspace),
    }
    if bundle:
        bindings.update({
            key: str(Path(values.get(key) or bundle / suffix).expanduser().resolve())
            for key, suffix in {
                "SKILLS_DIR": "skills", "METHOD_SEED_DIR": "methods",
                "DOCS_DIR": "docs", "UI_V2_DIR": "webui/dist",
            }.items()
        })
    apply_to_environ(normalized | bindings)
    return bindings


def check_install() -> dict:
    root = bundle_root()
    if root is None:
        return {"ok": False, "mode": "source", "error": "Not an installed application bundle"}
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Bundle manifest must be an object")
        if manifest.get("schema") != "lfl.application-bundle/v1" or manifest.get("version") != version("llm-first-loop"):
            raise ValueError("Bundle schema/version does not match installed distribution")
        files = manifest["files"]
        required = {"docs/ai_rules.md", "webui/dist/index.html"}
        if not isinstance(files, dict) or not required.issubset(files):
            raise ValueError("Bundle is missing required resources")
        failed = []
        for name, digest in files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                failed.append(name)
        return {"ok": not failed, "mode": "installed", "version": manifest["version"],
                "checked_files": len(files), "failed_files": failed}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "mode": "installed", "error": str(exc)}


def application_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lfl", add_help=False)
    parser.add_argument("--data-dir")
    parser.add_argument("--workspace")
    parser.add_argument("--config")
    parser.add_argument("--version", action="store_true")
    argv = list(sys.argv[1:] if argv is None else argv)
    # Global options precede COMMAND. Preserve subcommand options verbatim.
    boundary = 0
    path_options = ("--data-dir", "--workspace", "--config")
    while boundary < len(argv):
        token = argv[boundary]
        if token == "--version" or any(token.startswith(option + "=") for option in path_options):
            boundary += 1
        elif token in path_options:
            boundary += 2
        else:
            break
    args = parser.parse_args(argv[:boundary])
    args._query_home = default_home() if bundle_root() else Path(__file__).resolve().parents[2]
    remaining = argv[boundary:]
    if args.version:
        print(version("llm-first-loop"))
        return 0
    if remaining == ["--help"] or remaining == ["-h"]:
        print(HELP)
        return 0
    query = dispatch_query(remaining, args)
    if query is not None:
        return query
    if remaining[:1] == ["chat"] and remaining[1:] in (["--help"], ["-h"]):
        return main(remaining[1:])
    if remaining == ["check-install"]:
        report = check_install()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if remaining and remaining[0] in ("upgrade", "backup", "rollback"):
        # Installed recovery and planning never enter stateful Engine/bootstrap,
        # provider clients, package manager, or service_control mutation.
        from llm_loop.runtime.install_recovery import run_backup, run_rollback, run_upgrade

        subcommand = remaining[0]
        if subcommand == "upgrade":
            upgrade_parser = argparse.ArgumentParser(prog="lfl upgrade")
            upgrade_parser.add_argument("--plan", action="store_true")
            upgrade_parser.add_argument("--json", action="store_true")
            upgrade_parser.add_argument("--candidate")
            upgrade_parser.add_argument("--expected-sha256")
            upgrade_parser.add_argument("--require-trust", action="store_true")
            upgrade_parser.add_argument("--require-data-compatibility", action="store_true")
            upgrade_parser.add_argument("--stage", action="store_true", help="仅隔离保存经摘要校验的候选包")
            upgrade_parser.add_argument("--verify-stage", action="store_true", help="只读复核先前隔离的候选包")
            upgrade_parser.add_argument("--prepare", action="store_true", help="受控升级事务：缺少真实停机资格时安全拒绝")
            upgrade_parser.add_argument("--commit", action="store_true", help="生产切换：无权威事务资格时安全拒绝")
            upgrade_parser.add_argument("--abort", action="store_true", help="仅撤销已核验的本应用隔离候选")
            upgrade_parser.add_argument("--id", help="隔离候选的短 ID，不接受文件路径")
            upgrade_parser.add_argument("--receipt", help="受控事务回执（不等同隔离候选 ID）")
            upgrade_parser.add_argument("--snapshot")
            upgrade_parser.add_argument("--into")
            upgrade_parser.add_argument("--confirm-services-stopped", action="store_true")
            upgrade_parser.add_argument("--confirm-cutover", action="store_true")
            try:
                options = upgrade_parser.parse_args(remaining[1:])
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 2
            actions = (options.stage, options.verify_stage, options.prepare,
                       options.commit, options.abort, options.plan)
            if sum(bool(value) for value in actions) > 1:
                return 2
            if any((options.stage, options.verify_stage, options.prepare,
                    options.commit, options.abort)):
                from llm_loop.runtime.upgrade_stage import inspect_stage, stage_candidate

                bundle = bundle_root()
                home = default_home() if bundle else Path(__file__).resolve().parents[2]
                if options.stage:
                    if (options.candidate is None or options.expected_sha256 is None
                            or len(options.expected_sha256) != 64
                            or any(c not in "0123456789abcdefABCDEF" for c in options.expected_sha256)
                            or any((options.id, options.receipt, options.snapshot,
                                    options.into, options.confirm_services_stopped,
                                    options.confirm_cutover))):
                        return 2
                    if options.require_trust or options.require_data_compatibility:
                        status, report = 1, {"staged": False, "reason": (
                            "candidate_trust_unknown" if options.require_trust
                            else "schema_compatibility_unknown")}
                    elif bundle is None:
                        status, report = 1, {"reason": "installed_bundle_required", "staged": False}
                    else:
                        status, report = stage_candidate(
                            home=home, candidate=options.candidate,
                            expected=options.expected_sha256,
                            current_version=version("llm-first-loop"),
                        )
                elif options.verify_stage or options.abort:
                    if (options.candidate or options.expected_sha256 or options.snapshot
                            or options.into or options.confirm_cutover
                            or options.confirm_services_stopped or options.require_trust
                            or options.require_data_compatibility):
                        return 2
                    if not options.id or options.receipt:
                        status, report = 1, {"reason": "unknown_transaction", "valid": False}
                    elif bundle is None:
                        status, report = 1, {"reason": "installed_bundle_required", "valid": False}
                    else:
                        status, report = inspect_stage(
                            home=home, stage_id=options.id, abort=options.abort,
                        )
                elif options.prepare:
                    # A cold-stop checkbox does not attest every service and
                    # JSONL/SQLite writer. Never stage or install here.
                    if options.snapshot:
                        from llm_loop.runtime.install_recovery import (
                            BackupRejectedError,
                            verify_backup,
                        )

                        try:
                            verified = verify_backup(options.snapshot)
                        except (BackupRejectedError, OSError, ValueError):
                            verified = {"valid": False}
                        reason = ("service_identity_unverified" if verified["valid"]
                                  else "snapshot_unverified")
                    else:
                        reason = "service_identity_unverified"
                    status, report = 1, {"reason": reason, "prepared": False,
                                         "active_version_changed": False}
                else:
                    status, report = 1, {"reason": "transaction_unverified",
                                         "committed": False, "active_version_changed": False}
                if options.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    if status == 0 and options.abort:
                        print("隔离候选已撤销；安装、备份与用户数据未改变。")
                    elif status == 0 and options.verify_stage:
                        print("隔离候选完整性通过；尚未安装或切换版本。")
                    elif status == 0:
                        print("候选 wheel 已隔离保存；尚未安装或切换版本。")
                    else:
                        print("升级操作已安全拒绝（" + report.get("reason", "") + "）")
                    if report.get("stage_id"):
                        print("候选 ID：" + report["stage_id"])
                return status
            if options.candidate is not None or options.expected_sha256 is not None or (
                options.require_trust or options.require_data_compatibility
            ):
                # Candidate inspection is deliberately not a version switch.
                # Do not initialize a provider, service controller, or installer.
                digest = options.expected_sha256 or ""
                if (not options.plan or options.candidate is None
                        or len(digest) != 64
                        or any(char not in "0123456789abcdefABCDEF" for char in digest)):
                    return 2
                from llm_loop.runtime.upgrade_preflight import candidate_preflight

                bundle = bundle_root()
                current = version("llm-first-loop") if bundle else None
                status, report = candidate_preflight(
                    candidate=options.candidate,
                    expected_sha256=digest,
                    current_version=current,
                    require_trust=options.require_trust,
                    require_data_compatibility=options.require_data_compatibility,
                )
                if options.json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    print("候选包内容完整性已核对；并不代表可信来源、数据兼容或允许安装。"
                          if status == 0 else f"候选包检查拒绝：{report['reason']}")
                return status
            return run_upgrade(bundle=bundle_root(), installed_version=version("llm-first-loop"),
                               preview=options.plan, as_json=options.json)
        if subcommand == "backup":
            backup_parser = argparse.ArgumentParser(prog="lfl backup")
            backup_parser.add_argument("--plan", action="store_true")
            backup_parser.add_argument("--json", action="store_true")
            backup_parser.add_argument("--to")
            backup_parser.add_argument("--confirm-services-stopped", action="store_true")
            backup_parser.add_argument("--from", dest="verify_from")
            try:
                suffix = remaining[1:]
                verify = bool(suffix and suffix[0] == "verify")
                options = backup_parser.parse_args(suffix[1:] if verify else suffix)
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 2
            if options.json and not (options.plan or verify or options.to):
                return 2
            if verify and (not options.verify_from or options.plan or options.to or options.confirm_services_stopped):
                return 2
            if not verify and options.verify_from:
                return 2
            if options.plan and (options.to or options.confirm_services_stopped):
                return 2
            bundle = bundle_root()
            root = default_home() if bundle else Path(__file__).resolve().parents[2]
            return run_backup(args=args, home=root, bundle=bundle, environment=legacy_env_snapshot(),
                              preview=options.plan, as_json=options.json, target=options.to,
                              verify=options.verify_from if verify else None,
                              confirmed=options.confirm_services_stopped)
        rollback_parser = argparse.ArgumentParser(prog="lfl rollback")
        rollback_parser.add_argument("--from", dest="backup_from")
        rollback_parser.add_argument("--into")
        rollback_parser.add_argument("--confirm-services-stopped", action="store_true")
        rollback_parser.add_argument("--json", action="store_true")
        try:
            options = rollback_parser.parse_args(remaining[1:])
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 2
        return run_rollback(source=options.backup_from, target=options.into,
                            confirmed=options.confirm_services_stopped, as_json=options.json)
    if remaining and remaining[0] == "extensions":
        from llm_loop.extensions.cli import run_extensions

        bundle = bundle_root()
        root = default_home() if bundle else Path(__file__).resolve().parents[2]
        return run_extensions(
            remaining[1:], args=args, home=root, environment=legacy_env_snapshot(),
        )
    if remaining and remaining[0] == "start":
        start_parser = argparse.ArgumentParser(prog="lfl start", description="首次配置、诊断并启动 Web")
        start_parser.add_argument("--plan", action="store_true", help="只读预览，不配置或启动服务")
        start_parser.add_argument("--json", action="store_true", help="仅搭配 --plan 使用")
        try:
            options = start_parser.parse_args(remaining[1:])
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 2
        from llm_loop.runtime.onboarding import run_start

        bundle = bundle_root()
        return run_start(
            args=args, root=default_home() if bundle else Path(__file__).resolve().parents[2],
            bundle=bundle, environment=legacy_env_snapshot(), check_install=check_install,
            preview=options.plan, as_json=options.json,
            launch_web=lambda: application_main([*argv[:boundary], "web"]),
        )
    if remaining and remaining[0] == "init":
        # Setup is a separate consent-bound workflow; never invoke the normal
        # stateful bootstrap, build an Engine, or open a provider connection.
        init_parser = argparse.ArgumentParser(prog="lfl init", description="离线首次使用配置向导")
        init_parser.add_argument("--plan", action="store_true", help="只读预览，不写配置")
        init_parser.add_argument("--json", action="store_true", help="仅用于 --plan 的脱敏 JSON 预览")
        try:
            init_args = init_parser.parse_args(remaining[1:])
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 2

        from llm_loop.runtime.first_use import run_first_use

        bundle = bundle_root()
        root = default_home() if bundle else Path(__file__).resolve().parents[2]
        return run_first_use(
            args=args, root=root, bundle=bundle, environment=legacy_env_snapshot(),
            check_install=check_install, preview=init_args.plan, as_json=init_args.json,
        )
    if remaining and remaining[0] == "doctor":
        # P1: diagnostics must not call prepare_environment (env mutations),
        # build_engine, network clients, or any managed service lifecycle code.
        doctor_parser = argparse.ArgumentParser(prog="lfl doctor", description="离线只读首用配置诊断")
        doctor_parser.add_argument("--json", action="store_true", help="输出机器可读且不含配置值的 JSON")
        try:
            doctor_args = doctor_parser.parse_args(remaining[1:])
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 2
        from llm_loop.runtime.doctor import human_report, inspect_first_use

        bundle = bundle_root()
        root = default_home() if bundle else Path(__file__).resolve().parents[2]
        report = inspect_first_use(
            args=args,
            root=root,
            bundle=bundle,
            environment=legacy_env_snapshot(),
            check_install=check_install,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2) if doctor_args.json else human_report(report))
        return 0 if report["ready"] else 1
    try:
        bindings = prepare_environment(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if remaining == ["paths"]:
        print(json.dumps(bindings, ensure_ascii=False, indent=2))
        return 0
    if remaining and remaining[0] == "web":
        if len(remaining) != 1:
            parser.error("web uses WEB_HOST/WEB_PORT configuration; unexpected arguments")
        from llm_loop.web import main as web_main  # r9-import-exempt: optional Web entry

        runtime = Path(bindings["LFL_RUNTIME_ROOT"])
        runtime.mkdir(parents=True, exist_ok=True)
        os.chdir(runtime)
        web_main(workspace_root=bindings["LFL_WORKSPACE_ROOT"])
        return 0
    return main(remaining[1:] if remaining[:1] == ["chat"] else remaining,
                workspace_root=bindings["LFL_WORKSPACE_ROOT"])


if __name__ == "__main__":
    raise SystemExit(main())

