"""CLI 最小启动入口（design.md §2.4.2 / P1 批次1 多会话管理 T26）.

- 单条消息: python -m llm_loop.cli "消息"
- 交互模式: python -m llm_loop.cli --interactive
- 会话管理（T26）: list / delete / archive / unarchive / search / --session <id> 复用
"""

from __future__ import annotations

import argparse
import sys

from llm_loop.config import load_settings
from llm_loop.core.session import SessionStore


def _run_single(engine, text: str, session_id: str | None = None) -> None:
    """单条消息跑通最小闭环并打印真诚回答（可复用既有会话）."""
    session_store: SessionStore = engine.session
    if session_id:
        if not session_store.exists(session_id):
            from llm_loop.feedback.honesty import session_not_found_message

            print(session_not_found_message(session_id))
            return
        sid = session_id
    else:
        sid = session_store.create()
    result = engine.run(sid, text)
    print("\n" + "─" * 60)
    print(f"[会话 {sid[:8]}] 轮数={result.rounds} 工具调用={len(result.tool_calls)}")
    if result.truncated:
        print("[提示] 本次发生上下文截断")
    if result.verification_note:
        print(f"[校验] {result.verification_note.splitlines()[0][:100]}")
    print(result.final_answer)
    print("─" * 60)


def _run_interactive(engine, session_id: str | None = None) -> None:
    """交互模式（连续会话，验证记忆贯穿；可复用既有会话）."""
    session_store: SessionStore = engine.session
    if session_id and not session_store.exists(session_id):
        from llm_loop.feedback.honesty import session_not_found_message

        print(session_not_found_message(session_id))
        return
    sid = session_id or session_store.create()
    print(f"LLM-First Core Loop 交互模式（会话 {sid[:8]}，输入 exit 退出）")
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit", "退出"}:
            break
        result = engine.run(sid, text)
        print(f"\nAI> {result.final_answer}")
        if result.verification_note:
            print(f"[校验提示] {result.verification_note}")


# ── P1 会话管理命令（T26）──
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
    if engine.session.delete(session_id):
        print(session_deleted_message(session_id))
        return 0
    print("[删除失败] 事实: 无法删除会话。原因: 文件不存在或 IO 异常。建议: 检查后重试。")
    return 1


def _cmd_archive(engine, session_id: str, archived: bool) -> int:
    from llm_loop.feedback.honesty import session_archived_message

    ok = engine.session.archive(session_id) if archived else engine.session.unarchive(session_id)
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


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else list(sys.argv[1:])
    # 手动分派子命令（避免 subparsers 吃掉位置参数 message）
    _cmds = {
        "list",
        "delete",
        "archive",
        "unarchive",
        "search",
        "extract",
        "evolve-list",
        "evolve-review",
        "evolve-complete",  # M17 FR-REVIEW-AI-01: 人工完成登记（涉边界演进）
    }
    if argv and argv[0] in _cmds:
        return _dispatch_command(argv)

    parser = argparse.ArgumentParser(prog="llm_loop", description="LLM-First Core Loop")
    parser.add_argument("message", nargs="?", help="单条消息（不填则进入交互模式）")
    parser.add_argument("--interactive", action="store_true", help="交互模式")
    parser.add_argument("--session", help="复用指定会话（单条/交互）")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    from llm_loop.factory import build_engine

    engine = build_engine(settings)

    if args.message:
        _run_single(engine, args.message, session_id=args.session)
        return 0
    _run_interactive(engine, session_id=args.session)
    return 0


def _dispatch_command(argv: list[str]) -> int:
    """子命令分派（list/delete/archive/unarchive/search/extract）."""
    cmd = argv[0]
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    from llm_loop.factory import build_engine

    engine = build_engine(settings)

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
    if cmd == "evolve-list":
        return _cmd_evolve_list(engine, argv[1] if len(argv) > 1 else None)
    if cmd == "evolve-review":
        if len(argv) < 3:
            print("用法: llm_loop evolve-review <suggestion_id> <accepted|rejected>")
            return 2
        return _cmd_evolve_review(engine, argv[1], argv[2])
    if cmd == "evolve-complete":
        if len(argv) < 3:
            print('用法: llm_loop evolve-complete <suggestion_id> "<执行结果说明>"')
            return 2
        return _cmd_evolve_complete(engine, argv[1], " ".join(argv[2:]))
    return 2


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
        print(
            f"  {it['id']} | {it['status']} | {it.get('priority')} | {it.get('content', '')[:50]}{human}"
        )
    return 0


def _cmd_evolve_review(engine, suggestion_id: str, decision: str) -> int:
    """人工审阅演进建议（accepted/rejected，EVOLVE-05 闭环；T60: accepted 自动触发执行）."""
    store = getattr(engine.correction_ctx, "evolution_store", None)
    if store is None:
        print("[演进建议不可用] EVOLVE_ENABLED=0")
        return 1
    try:
        target = store.review(suggestion_id, decision)
    except ValueError as exc:
        print(f"[参数错误] {exc}")
        return 2
    if target is None:
        print(f"[建议不存在] 未找到 {suggestion_id}")
        return 1
    print(f"[审阅完成] {suggestion_id} → {target['status']}: {target.get('content', '')[:80]}")
    # T60: accepted 且权限允许 → 自动触发执行（EXEC-02）
    if decision == "accepted":
        _maybe_auto_execute(engine, store, target)
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
    """accepted 后按权限分级自动执行（can_auto_exec → EvolutionExecutor，T60）."""
    from llm_loop.introspection.evolution import EvolutionSuggestion
    from llm_loop.introspection.evolution_exec import EvolutionExecutor

    level = int(getattr(engine.correction_ctx, "evolve_local_exec", 0) or 0)
    if level == 0:
        print(
            f"[等待人工执行] 当前为仅建议模式（EVOLVE_LOCAL_EXEC=0），{target['id']} 由人工执行。"
        )
        return
    whitelist_raw = getattr(engine.correction_ctx, "evolve_exec_whitelist", "") or ""
    whitelist = (
        tuple(w.strip() for w in whitelist_raw.split(",") if w.strip()) if whitelist_raw else ()
    )
    suggestion = EvolutionSuggestion(**target)
    executor = EvolutionExecutor(
        exec_level=level,
        whitelist=whitelist,
        store=store,
        audit_dir=getattr(engine.settings, "audit_dir", None),
    )
    outcome = executor.maybe_auto_execute(suggestion)
    if outcome is None:
        print(f"[等待人工执行] {target['id']} 不满足自动执行条件（边界/权限/白名单），由人工执行。")
    else:
        print(
            f"[自动执行] {target['id']} → {outcome.status}（executor={outcome.executor} "
            f"verify={outcome.verify_result} rollback={outcome.rollback_result}）: {outcome.note[:120]}"
        )


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


if __name__ == "__main__":
    raise SystemExit(main())
