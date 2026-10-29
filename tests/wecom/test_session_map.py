"""企微会话映射测试（M0-6）.

同一 userid 两次对话同一 session；p:/g: 前缀正确；持久化文件独立于飞书
（默认文件名不同 + 不同路径互不干扰）。零真实依赖（FakeStore）。
"""

import threading

from llm_loop.wecom.session_map import WeComSessionMap


class FakeStore:
    """SessionStore 测试替身（WeComSessionMap 用到的最小面）."""

    def __init__(self) -> None:
        self.sessions: list[str] = []
        self._shared: str | None = None
        self.channels: dict[str, str] = {}
        self._seq = 0

    def create(self, model_override=None) -> str:  # noqa: ARG002 — 签名对齐
        self._seq += 1  # 递增计数：删除后不复用 id（对齐真实 SessionStore 语义）
        sid = f"sid_{self._seq}"
        self.sessions.append(sid)
        return sid

    def exists(self, sid: str) -> bool:
        return sid in self.sessions

    def get_shared_current(self) -> str | None:
        return self._shared

    def set_shared_current(self, sid: str) -> None:
        self._shared = sid

    def set_channel(self, sid: str, channel: str) -> bool:
        self.channels.setdefault(sid, channel)
        return True


def test_map_same_userid_same_session(tmp_path):
    """同一 userid 两次对话 → 同一 session_id（多轮连续）."""
    store = FakeStore()
    smap = WeComSessionMap(store, path=str(tmp_path / "wecom_session_map.json"))
    key = WeComSessionMap.p2p_key("u_alice")
    sid1 = smap.get_or_create(key)
    sid2 = smap.get_or_create(key)
    assert sid1 and sid2 == sid1


def test_map_prefix_and_isolation(tmp_path):
    """p:/g: 前缀正确；单聊/群聊/不同用户互不串话."""
    store = FakeStore()
    smap = WeComSessionMap(store, path=str(tmp_path / "wecom_session_map.json"))
    assert WeComSessionMap.p2p_key("u1") == "p:u1"
    assert WeComSessionMap.group_key("g1") == "g:g1"
    sid_p = smap.get_or_create("p:u1")
    sid_p2 = smap.get_or_create("p:u2")
    sid_g = smap.get_or_create("g:group1")
    sid_g2 = smap.get_or_create("g:group2")
    assert len({sid_p, sid_p2, sid_g, sid_g2}) == 4  # 各自独立


def test_map_persist_and_reload(tmp_path):
    """持久化：同路径重载保留映射；channel 标记 wecom:*（非 feishu:*）."""
    store = FakeStore()
    path = tmp_path / "wecom_session_map.json"
    smap = WeComSessionMap(store, path=str(path))
    key = WeComSessionMap.p2p_key("u_persist")
    sid = smap.get_or_create(key)
    raw = path.read_text(encoding="utf-8")
    assert key in raw and sid in raw
    assert "secret" not in raw.lower()  # 不含凭据

    reloaded = WeComSessionMap(FakeStore(), path=str(path))
    assert reloaded.get(key) == sid
    assert store.channels.get(sid, "").startswith("wecom:p2p:")  # 企微通道标记


def test_map_independent_from_feishu(tmp_path):
    """映射文件与飞书分离：默认文件名不同；两个 map 各写各的文件互不污染."""
    from llm_loop.feishu.session_map import SessionMap as FeishuSessionMap
    from llm_loop.wecom.config import DEFAULT_SESSION_MAP_FILENAME

    # a) 默认文件名不同（跨通道不共用一个文件）
    assert DEFAULT_SESSION_MAP_FILENAME == "wecom_session_map.json"
    assert DEFAULT_SESSION_MAP_FILENAME != "feishu_session_map.json"

    # b) 同目录下企微/飞书各自映射，键空间互不污染
    wecom_path = tmp_path / DEFAULT_SESSION_MAP_FILENAME
    feishu_path = tmp_path / "feishu_session_map.json"
    wsmap = WeComSessionMap(FakeStore(), path=str(wecom_path))
    fsmap = FeishuSessionMap(FakeStore(), path=str(feishu_path))
    w_key = WeComSessionMap.p2p_key("u_same")  # 企微 userid
    f_key = FeishuSessionMap.p2p_key("ou_same")  # 飞书 open_id（真实场景本就不同）
    w_sid = wsmap.get_or_create(w_key)
    f_sid = fsmap.get_or_create(f_key)
    assert w_sid and f_sid  # 各自建出
    # 文件级分离：各自文件只含各自通道的键，互不包含对方键
    assert fsmap.get(w_key) is None  # 飞书 map 查不到企微键
    assert wsmap.get(f_key) is None  # 企微 map 查不到飞书键
    assert w_key not in feishu_path.read_text(encoding="utf-8")
    assert f_key not in wecom_path.read_text(encoding="utf-8")
    assert wecom_path.exists() and feishu_path.exists()


def test_map_owner_shared_current(tmp_path):
    """跨端共享：owner 单聊复用/设置共享当前会话（Web/企微同一上下文）."""
    store = FakeStore()
    smap = WeComSessionMap(store, path=str(tmp_path / "wecom_session_map.json"))
    smap._owner = "u_owner"  # noqa: SLF001 — 测试注入 owner
    sid1 = smap.get_or_create(WeComSessionMap.p2p_key("u_owner"))
    sid2 = smap.get_or_create(WeComSessionMap.p2p_key("u_owner"))
    assert sid2 == sid1
    assert store.get_shared_current() == sid1
    # Web 先建共享当前 → owner 复用
    web_sid = FakeStore.create(store)
    store.set_shared_current(web_sid)
    assert smap.get_or_create(WeComSessionMap.p2p_key("u_owner")) == web_sid


def test_map_concurrent_isolate(tmp_path):
    """多线程并发各自映射（RLock 保护，无串话无异常）."""
    store = FakeStore()
    smap = WeComSessionMap(store, path=str(tmp_path / "wecom_session_map.json"))
    keys = [WeComSessionMap.p2p_key(f"u_t{i}") for i in range(10)]
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
    assert not errors
    assert len(set(results.values())) == len(keys)  # 无串话


def test_map_removed_session_rebuild(tmp_path):
    """映射的会话被删 → 重建新 session（生命周期管理）."""
    store = FakeStore()
    smap = WeComSessionMap(store, path=str(tmp_path / "wecom_session_map.json"))
    key = WeComSessionMap.p2p_key("u_life")
    sid1 = smap.get_or_create(key)
    store.sessions.remove(sid1)  # 会话被删除
    sid2 = smap.get_or_create(key)
    assert sid2 != sid1
