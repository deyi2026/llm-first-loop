"""M64 测试环境污染全局防御 验证.

conftest 顶层 patch: 任何指向项目真实 data 目录的 SessionStore 写盘请求被自动
重定向到临时目录——即使测试硬编码 data_dir="./data"，也不污染真实 data/sessions。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore


def test_hardcoded_relative_data_dir_is_isolated(tmp_path, monkeypatch):
    """硬编码 data_dir="./data" 被重定向到临时目录（真实 ./data 不新增会话文件）."""
    real_data = Path(__file__).resolve().parent.parent.parent / "data"
    real_sessions = real_data / "sessions"
    before = set(real_sessions.glob("*.json")) if real_sessions.exists() else set()

    store = SessionStore("./data")
    sid = store.create()
    store.append(sid, Message(role="user", content="M64 test", source=MessageSource.USER))

    # 隔离目录可正常读写
    assert store.load(sid).messages[-1].content == "M64 test"
    # 真实 data/sessions 未被触碰
    after = set(real_sessions.glob("*.json")) if real_sessions.exists() else set()
    assert after == before, "真实 data/sessions 不应新增文件"


def test_absolute_real_data_dir_is_isolated():
    """绝对路径指向真实 data 也被重定向."""

    real_data = Path(__file__).resolve().parent.parent.parent / "data"
    store = SessionStore(str(real_data))
    sid = store.create()
    assert store.exists(sid)  # 在隔离临时目录中正常工作
    # 真实 data/sessions 不包含该 sid
    real = real_data / "sessions"
    assert not (real / f"{sid}.json").exists()


def test_tmp_path_data_dir_kept():
    """非真实 data 目录（tmp_path）原样保留，不影响测试预期."""
    store = SessionStore(str(Path("/tmp/nonexistent-llm-test-xyz")))
    assert store._dir == Path("/tmp/nonexistent-llm-test-xyz")  # noqa: SLF001
