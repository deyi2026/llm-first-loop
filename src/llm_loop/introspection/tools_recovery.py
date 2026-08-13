"""recover_from_backup 工具实现（design §2.3.2.3 / spec §5.3.1）.

参数校验 → 调 RecoveryChannel.recover → 如实回执（fail-open 不阻断主循环）。
程序仅提供恢复通道；恢复决策（恢复哪条/是否覆盖冲突）归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.recovery.channel import RecoveryChannel


def _parse_backup_id(backup_id: str) -> tuple[str, str, str] | None:
    """解析 backup_id → (source_id, timestamp, target_type).

    格式: <source_id>.<YYYYMMDDHHMMSS>.<target_type>.pending.json
    """
    parts = backup_id.rsplit(".", 4)
    if len(parts) != 5:
        return None
    source_id, ts, target_type, suffix1, suffix2 = parts
    if suffix1 != "pending" or suffix2 != "json":
        return None
    return source_id, ts, target_type


def run_recover_from_backup(
    channel: RecoveryChannel,
    *,
    backup_id: str,
    on_conflict: str = "abort",
    sessions_dir: str | Path | None = None,
    memory_dir: str | Path | None = None,
) -> str:
    """recover_from_backup 工具逻辑：校验 → 恢复 → 如实回执.

    sessions_dir/memory_dir：正式位置目录（session 类型写 sessions_dir/<source_id>.json，
    memory_stats 类型写 memory_dir/index.json）。
    """
    if not backup_id:
        return "[参数错误] 缺失必填字段: backup_id（未执行恢复）"
    if on_conflict not in ("abort", "overwrite"):
        return f"[参数错误] on_conflict 须为 abort/overwrite，收到: {on_conflict}"

    parsed = _parse_backup_id(backup_id)
    if parsed is None:
        return f"[参数错误] backup_id 格式无效: {backup_id}"
    source_id, _ts, target_type = parsed

    if target_type == "session":
        if sessions_dir is None:
            return "[程序异常] sessions_dir 未注入，无法恢复会话"
        target_path = Path(sessions_dir) / f"{source_id}.json"

        def target_write_fn(payload: bytes | str) -> None:
            content = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

        def target_exists_fn() -> bool:
            return target_path.exists()

    elif target_type == "memory_stats":
        if memory_dir is None:
            return "[程序异常] memory_dir 未注入，无法恢复记忆统计"
        target_path = Path(memory_dir) / "index.json"

        def target_write_fn(payload: bytes | str) -> None:
            content = payload.decode("utf-8") if isinstance(payload, bytes) else payload
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

        def target_exists_fn() -> bool:
            return target_path.exists()

    else:
        return f"[参数错误] 未知的 target_type: {target_type}"

    try:
        result = channel.recover(
            backup_id=backup_id,
            target_write_fn=target_write_fn,
            target_exists_fn=target_exists_fn,
            on_conflict=on_conflict,
        )
    except OSError as exc:
        return f"[程序异常] 恢复失败（{type(exc).__name__}: {exc}），备份保留"

    if result.status == "recovered":
        return f"[recover_from_backup] 已恢复 {result.affected}（备份 {backup_id} → {target_path}）"
    if result.status == "conflict":
        return (
            f"[recover_from_backup] 冲突：{target_path} 已存在数据，未覆盖"
            f"（on_conflict=abort，可显式 overwrite）"
        )
    if result.status == "not_found":
        return f"[未找到] {backup_id}"
    if result.status == "corrupt":
        return f"[备份损坏] {backup_id}：{result.error}"
    if result.status == "failed":
        return f"[程序异常] 恢复失败：{result.error}，备份保留"
    return f"[程序异常] 未知恢复状态: {result.status}"
