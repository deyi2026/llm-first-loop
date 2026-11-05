"""L3 协助收件箱单测（help_inbox.py 存储 + tools_help.py 失败口径）.

覆盖: post→list→resolve 生命周期 / blocking 计数 / 损坏跳过与计数 /
非法 need / 多线程并发不丢 / need 与 to_session 过滤 / 工具层 reason_code。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.help_inbox import (
    HelpInbox,
    HelpInboxError,
    HelpInboxNotFoundError,
)
from llm_loop.introspection.tools_help import (
    run_help_inbox,
    run_help_request,
    run_help_resolve,
)


@pytest.fixture()
def inbox(tmp_path: Path) -> HelpInbox:
    return HelpInbox(tmp_path)  # tmp_path 即 data_dir，绝不触碰真实 data/interop


class _Host:
    """RegistryHost 最小替身: audit_dir = <data_dir>/audit（与真实装配同构）。"""

    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = str(audit_dir)
        self.ctx = None


@pytest.fixture()
def host(tmp_path: Path) -> _Host:
    return _Host(tmp_path / "audit")  # tools_help 经 audit_dir.parent 推回 data_dir


def _payload(**overrides) -> dict:
    payload = {"topic": "需要 main head 确认", "body": "rebase 后 tests 挂了", "need": "info"}
    payload.update(overrides)
    return payload


# ---------------- 存储: 生命周期 ----------------

def test_post_list_resolve_roundtrip(inbox: HelpInbox) -> None:
    msg = inbox.post(**_payload())
    assert msg["state"] == "pending"
    assert len(msg["id"]) == 12

    items = inbox.list_pending()
    assert [m["id"] for m in items] == [msg["id"]]
    assert items[0]["topic"] == msg["topic"]
    assert inbox.counts() == {"pending": 1, "blocking": 0}

    done = inbox.resolve(msg["id"], "已确认，用 main head=1da78393b", by_session="s2")
    assert done["state"] == "resolved"
    assert done["response"] == "已确认，用 main head=1da78393b"
    assert done["by_session"] == "s2"
    assert done["resolved_at"]
    assert done["topic"] == msg["topic"]  # 原字段保留

    assert inbox.list_pending() == []
    assert not inbox.pending_path(msg["id"]).exists()
    assert inbox.done_path(msg["id"]).exists()
    assert json.loads(inbox.done_path(msg["id"]).read_text(encoding="utf-8"))["state"] == "resolved"


def test_resolve_declined_and_idempotent(inbox: HelpInbox) -> None:
    msg = inbox.post(**_payload())
    first = inbox.resolve(msg["id"], "不接", by_session="s2", decision="declined")
    assert first["state"] == "declined"
    # 幂等: 重复应答返回既有终态，不覆写历史
    again = inbox.resolve(msg["id"], "再答一次", by_session="s3", decision="resolved")
    assert again["state"] == "declined"


def test_resolve_missing_raises(inbox: HelpInbox) -> None:
    with pytest.raises(HelpInboxNotFoundError):
        inbox.resolve("no-such-id", "resp")


# ---------------- 存储: 计数与损坏 ----------------

def test_blocking_counts_only_block_pending(inbox: HelpInbox) -> None:
    inbox.post(**_payload(need="block"))
    inbox.post(**_payload(need="info"))
    assert inbox.counts() == {"pending": 2, "blocking": 1}

    blocked = inbox.list_pending(need="block")[0]
    inbox.resolve(blocked["id"], "解除", by_session="s2")
    assert inbox.counts() == {"pending": 1, "blocking": 0}  # 应答后不再阻塞


def test_corrupted_json_skipped_and_counted(inbox: HelpInbox) -> None:
    good = inbox.post(**_payload())
    bad = inbox.pending_path("deadbeef0000")
    bad.write_text("{not-json", encoding="utf-8")  # 故意损坏

    items = inbox.list_pending()
    assert [m["id"] for m in items] == [good["id"]]  # 跳过损坏、不整体失败
    assert inbox.corrupted_count() == 1
    assert inbox.counts() == {"pending": 1, "blocking": 0}

    # resolve 对损坏文件 fail-closed: 不删原文、不改 state
    with pytest.raises(HelpInboxError):
        inbox.resolve("deadbeef0000", "resp")
    assert bad.exists()


def test_invalid_need_raises(inbox: HelpInbox) -> None:
    with pytest.raises(HelpInboxError, match="need"):
        inbox.post(**_payload(need="decision"))  # 设计文档旧口径，现按非法处理
    with pytest.raises(HelpInboxError, match="topic"):
        inbox.post(**_payload(topic="   "))  # 空白 topic 等价缺失


# ---------------- 存储: 并发 ----------------

def test_concurrent_posts_no_loss(inbox: HelpInbox) -> None:
    posted: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        msg = inbox.post(**_payload(topic=f"并发协助请求 {i}", need="block"))
        with lock:
            posted.append(msg["id"])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items = inbox.list_pending()
    assert len(items) == 10  # 不丢
    assert {m["id"] for m in items} == set(posted)
    assert inbox.counts() == {"pending": 10, "blocking": 10}
    assert sorted(m["ts"] for m in items) == [m["ts"] for m in items]  # ts 升序


# ---------------- 存储: 过滤 ----------------

def test_need_and_to_session_filters(inbox: HelpInbox) -> None:
    a = inbox.post(**_payload(topic="a", need="info", to_session="s2"))
    b = inbox.post(**_payload(topic="b", need="block", to_session="s3"))
    c = inbox.post(**_payload(topic="c", need="review"))  # 广播（to_session 空）

    assert [m["id"] for m in inbox.list_pending(need="block")] == [b["id"]]
    assert [m["id"] for m in inbox.list_pending(need="info")] == [a["id"]]

    to_s2 = [m["id"] for m in inbox.list_pending(to_session="s2")]
    assert to_s2 == [a["id"], c["id"]]  # 精确命中 + 广播
    to_s4 = [m["id"] for m in inbox.list_pending(to_session="s4")]
    assert to_s4 == [c["id"]]  # 只有广播可见
    assert len(inbox.list_pending()) == 3  # 无过滤 = 全量


# ---------------- 工具层: 失败口径（不抛宿主） ----------------

def test_tool_request_and_roundtrip_via_audit_dir(host: _Host, tmp_path: Path) -> None:
    result = run_help_request(None, host, {"topic": "借 main head", "body": "rebase 用", "need": "info"})
    assert result.status is ToolResultStatus.SUCCESS
    payload = json.loads(result.content.split("\n", 1)[1])
    msg_id, path = payload["id"], payload["path"]
    # data_dir 推导: audit_dir.parent/interop/session/pending/<id>.json
    assert Path(path) == tmp_path / "interop" / "session" / "pending" / f"{msg_id}.json"
    assert Path(path).exists()

    listing = run_help_inbox(None, host, {})
    assert listing.status is ToolResultStatus.SUCCESS
    data = json.loads(listing.content.split("\n", 1)[1])
    assert data["counts"] == {"pending": 1, "blocking": 0}
    assert data["corrupted"] == 0
    assert [m["id"] for m in data["items"]] == [msg_id]

    resolved = run_help_resolve(None, host, {"id": msg_id, "response": "head=1da78393b"})
    assert resolved.status is ToolResultStatus.SUCCESS
    assert json.loads(resolved.content.split("\n", 1)[1]) == {"id": msg_id, "state": "resolved"}


def test_tool_failure_reason_codes(host: _Host) -> None:
    # 参数缺失 → missing_param
    r1 = run_help_request(None, host, {"topic": "t"})
    assert r1.status is ToolResultStatus.FAILURE and "missing_param" in r1.content
    # 非法 need → bad_param（显式空串同样按非法，不静默取默认）
    r2 = run_help_request(None, host, {"topic": "t", "body": "b", "need": ""})
    assert r2.status is ToolResultStatus.FAILURE and "bad_param" in r2.content
    # 非法 decision → bad_param
    run_help_request(None, host, {"topic": "t", "body": "b"})
    listing = run_help_inbox(None, host, {})
    mid = json.loads(listing.content.split("\n", 1)[1])["items"][0]["id"]
    r3 = run_help_resolve(None, host, {"id": mid, "response": "r", "decision": "maybe"})
    assert r3.status is ToolResultStatus.FAILURE and "bad_param" in r3.content
    # id 不存在 → not_found
    r4 = run_help_resolve(None, host, {"id": "ghost0000000", "response": "r"})
    assert r4.status is ToolResultStatus.FAILURE and "not_found" in r4.content
    # help_inbox 非法 need 过滤 → bad_param
    r5 = run_help_inbox(None, host, {"need": "urgent"})
    assert r5.status is ToolResultStatus.FAILURE and "bad_param" in r5.content


def test_tool_inbox_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import llm_loop.introspection.tools_help as tools_help

    def _boom(data_dir):  # noqa: ANN001 — 构造即 OSError
        raise OSError("read-only filesystem")

    monkeypatch.setattr(tools_help, "HelpInbox", _boom)
    host = _Host(Path("/tmp/audit"))
    for runner, args in (
        (run_help_request, {"topic": "t", "body": "b"}),
        (run_help_inbox, {}),
        (run_help_resolve, {"id": "x", "response": "r"}),
    ):
        result = runner(None, host, args)
        assert result.status is ToolResultStatus.FAILURE
        assert "inbox_unavailable" in result.content
