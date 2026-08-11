"""飞书会话映射测试（M42，用例 16-20）.

映射：同一飞书会话复用 session_id / 不同会话隔离（不串话）。
多轮上下文：同一会话第 2 条消息 FakeLLM 收到前轮上下文；不同会话隔离。
持久化：映射文件可查（feishu_key/session_id）+ 不含密钥。
并发：多线程各自映射（threading.Lock 保护，无串话）。
生命周期：remove 后重建新 session_id；映射文件损坏容错重建。
零真实飞书 API（构造消息 + 复用 SessionStore）。
"""

import json
import threading

from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap


def _msg(sender_id: str, chat_id: str, text: str, is_group: bool = False) -> FeishuMessage:
    return FeishuMessage(
        message_id=f"om_{sender_id}_{len(text)}",
        sender_id=sender_id,
        chat_id=chat_id,
        msg_type="text",
        text=text,
        is_group=is_group,
        sender_type="user",
    )


def _make_handler(build_test_engine, tmp_path, responses):
    engine, fake = build_test_engine(responses)
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_session_map.json"))
    replies: list[tuple[str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    return handler, engine, fake, session_map


def test_ses_map_create_reuse(build_test_engine, tmp_path):
    """用例 16：首次创建 / 同一会话复用 / 不同会话隔离（不串话）."""
    _, _, _, smap = _make_handler(build_test_engine, tmp_path, [{"content": "答"}])
    key_a = SessionMap.p2p_key("ou_a")
    key_b = SessionMap.p2p_key("ou_b")
    key_g = SessionMap.group_key("oc_group")

    sid1 = smap.get_or_create(key_a)
    assert sid1  # a) 首次 → 创建
    assert smap.get_or_create(key_a) == sid1  # b) 同一会话 → 复用
    sid2 = smap.get_or_create(key_b)
    assert sid2 != sid1  # c) 不同私聊 → 不同 session_id
    sid3 = smap.get_or_create(key_g)
    assert sid3 != sid1 and sid3 != sid2  # c) 群聊键 → 独立


def test_ses_multiround_context(build_test_engine, tmp_path):
    """用例 17：同一会话第 2 条消息收到前轮上下文；不同会话上下文隔离."""
    handler, _, fake, _ = _make_handler(
        build_test_engine, tmp_path, [{"content": "答一"}, {"content": "答二"}, {"content": "答三"}]
    )
    handler.handle(_msg("ou_a", "oc_a", "第一句"))
    handler.handle(_msg("ou_a", "oc_a", "第二句"))
    handler.handle(_msg("ou_b", "oc_b", "别家的话"))

    # a) 第 2 条（同一会话）FakeLLM 收到前轮上下文
    assert len(fake.calls) == 3
    second_msgs = json.dumps(fake.calls[1]["messages"], ensure_ascii=False)
    assert "第一句" in second_msgs
    # b) 不同会话上下文隔离（B 会话看不到 A 会话内容）
    third_msgs = json.dumps(fake.calls[2]["messages"], ensure_ascii=False)
    assert "第一句" not in third_msgs
    assert "第二句" not in third_msgs


def test_ses_map_persist(build_test_engine, tmp_path):
    """用例 18：映射持久化可查（feishu_key/session_id）+ 记录不含密钥."""
    _, _, _, smap = _make_handler(build_test_engine, tmp_path, [{"content": "答"}])
    key = SessionMap.p2p_key("ou_persist")
    sid = smap.get_or_create(key)

    # a) 重新实例化（同路径）→ 映射从文件加载保留
    reloaded = SessionMap(smap._store, path=str(tmp_path / "feishu_session_map.json"))
    assert reloaded.get(key) == sid

    # b) 记录含 feishu_key + session_id；不含密钥
    raw = (tmp_path / "feishu_session_map.json").read_text(encoding="utf-8")
    assert key in raw
    assert sid in raw
    assert "app_secret" not in raw
    assert "secret" not in raw.lower()


def test_ses_concurrent_isolate(build_test_engine, tmp_path):
    """用例 19：多线程并发各自映射（无串话 + 无异常，Lock 保护）."""
    _, _, _, smap = _make_handler(build_test_engine, tmp_path, [{"content": "答"}])
    keys = [SessionMap.p2p_key(f"ou_t{i}") for i in range(10)]
    results: dict[str, str] = {}
    lock = threading.Lock()
    errors: list[Exception] = []

    def worker(key: str) -> None:
        try:
            sid = smap.get_or_create(key)
            with lock:
                results[key] = sid
        except Exception as exc:  # noqa: BLE001 — 并发异常收集断言
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors  # 并发读写无异常
    assert set(results.keys()) == set(keys)
    assert len(set(results.values())) == len(keys)  # 各映射各自 session_id（无串话）


def test_ses_lifecycle(build_test_engine, tmp_path):
    """用例 20：remove 后重建新 session_id + 映射文件损坏容错重建."""
    _, _, _, smap = _make_handler(build_test_engine, tmp_path, [{"content": "答"}])
    key = SessionMap.p2p_key("ou_life")
    sid1 = smap.get_or_create(key)
    smap.remove(key)

    # a) remove 后 resolve 重建新 session_id（如实标注重建语义 = 新 id ≠ 旧）
    sid2 = smap.get_or_create(key)
    assert sid2 != sid1
    assert smap.get(key) == sid2

    # b) 映射文件损坏 → 重建映射（不抛异常，可继续使用）
    path = tmp_path / "feishu_session_map.json"
    path.write_text("{broken json!!", encoding="utf-8")
    reloaded = SessionMap(smap._store, path=str(path))
    sid3 = reloaded.get_or_create(key)
    assert sid3  # 损坏后重建可用
