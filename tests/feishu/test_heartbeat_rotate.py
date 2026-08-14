"""T3a(2026-08-14) 心跳历史轮转测试（零真实飞书，纯函数 + 模块 env 解析）.

覆盖: 轮转纯函数（未配置/未超限/超限/旧 .1 覆盖/不存在/OSError fail-open）+ env 解析。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.feishu.bridge import (
    _heartbeat_history_max_bytes,
    rotate_heartbeat_history,
)


def test_max_bytes_unset_returns_none(monkeypatch):
    """未配置 FEISHU_HEARTBEAT_HISTORY_MAX_MB → None（不限制，零回归）."""
    monkeypatch.delenv("FEISHU_HEARTBEAT_HISTORY_MAX_MB", raising=False)
    assert _heartbeat_history_max_bytes() is None


def test_max_bytes_parsed_mb(monkeypatch):
    """配置 "10" → 10MB 字节数."""
    monkeypatch.setenv("FEISHU_HEARTBEAT_HISTORY_MAX_MB", "10")
    assert _heartbeat_history_max_bytes() == 10 * 1024 * 1024


def test_max_bytes_invalid_fail_open(monkeypatch):
    """非法值（如 "abc"）→ None（fail-open 不限制）."""
    monkeypatch.setenv("FEISHU_HEARTBEAT_HISTORY_MAX_MB", "abc")
    assert _heartbeat_history_max_bytes() is None


def test_rotate_unconfigured_noop(tmp_path):
    """未配置（None）→ 文件原样不动，返回 False."""
    p = tmp_path / "hist.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert rotate_heartbeat_history(str(p), None) is False
    assert p.exists()
    assert not Path(str(p) + ".1").exists()


def test_rotate_below_threshold_noop(tmp_path):
    """未超阈值 → 不轮转."""
    p = tmp_path / "hist.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert rotate_heartbeat_history(p, 1024 * 1024) is False
    assert p.exists()
    assert not Path(str(p) + ".1").exists()


def test_rotate_at_threshold_rotates(tmp_path):
    """达到阈值 → 当前文件轮转为 .1，原路径不再存在."""
    p = tmp_path / "hist.jsonl"
    p.write_text('{"a": 1}\n' * 100, encoding="utf-8")  # ~700B
    assert rotate_heartbeat_history(p, 500) is True
    assert not p.exists()
    bak = Path(str(p) + ".1")
    assert bak.exists()
    assert '{"a": 1}' in bak.read_text(encoding="utf-8")


def test_rotate_overwrites_old_bak(tmp_path):
    """已有 .1 时先删旧再轮转（只保留最近 1 份）."""
    p = tmp_path / "hist.jsonl"
    p.write_text('{"new": 2}\n' * 100, encoding="utf-8")
    bak = Path(str(p) + ".1")
    bak.write_text("OLD", encoding="utf-8")
    assert rotate_heartbeat_history(p, 500) is True
    assert bak.exists()
    assert "OLD" not in bak.read_text(encoding="utf-8")
    assert '{"new": 2}' in bak.read_text(encoding="utf-8")


def test_rotate_missing_file_noop(tmp_path):
    """文件不存在 → False 不报错."""
    p = tmp_path / "nope.jsonl"
    assert rotate_heartbeat_history(p, 500) is False


def test_rotate_directory_fail_open(tmp_path, monkeypatch):
    """stat 失败（OSError，如权限拒绝）→ fail-open False 不抛（平台无关模拟）."""
    from pathlib import Path

    p = tmp_path / "dirlike.jsonl"
    p.write_text("x" * 600, encoding="utf-8")

    def _boom_stat(self, *args, **kwargs):
        raise OSError("模拟 stat 失败")

    monkeypatch.setattr(Path, "stat", _boom_stat)
    assert rotate_heartbeat_history(p, 500) is False
