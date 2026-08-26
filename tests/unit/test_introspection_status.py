

# ── 2026-08-20: 维度参数鲁棒归一化（EVO-20260820-6857bf41 修复）──

def test_normalize_dimensions_handles_malformed_inputs():
    """模型传残缺 JSON 字符串/垃圾维度名 → 过滤到合法集或回落全量（不假错误）."""
    from llm_loop.introspection.status import _normalize_dimensions

    known = {"architecture_config", "exception_log", "recovery", "pending_actions", "context_usage"}
    # 残缺 JSON 数组字符串（实测形态）→ 提取合法项
    assert _normalize_dimensions('["architecture_config", "recovery"', known) == [
        "architecture_config", "recovery",
    ]
    # 垃圾前缀 + 合法项 → 保留合法项（垃圾项清洗后由调用方标注 unavailable）
    out = _normalize_dimensions('item["evolution_summary", "recovery"', known)
    assert out is not None and "recovery" in out
    # 逗号/空白串
    assert _normalize_dimensions("architecture_config,recovery", known) == [
        "architecture_config", "recovery",
    ]
    # 全部非法 → None（回落全量，避免"维度 'garbage' 暂不可用"假错误）
    assert _normalize_dimensions("garbage", known) is None
    assert _normalize_dimensions(123, known) is None
    # 列表混合: 部分合法 → 保留全部清洗项（未知项由调用方标注 unavailable）
    assert _normalize_dimensions(["recovery", "bogus"], known) == ["recovery", "bogus"]
    # 部分合法时垃圾项被清洗（前导 [ 引号剥除）
    out = _normalize_dimensions('item["evolution_summary", "recovery"', known)
    assert out is not None and "recovery" in out


# ── 2026-08-26: EVO-20260826-3b2bd663 回归——dimensions 必须到达 snapshot 且不同维度输出不同 ──
# 背景：旧运行进程曾对 4 个不同 dimensions 调用返回字节级相同的全量摘要（8069 字符），
# 根因是进程加载的旧代码未把 dimensions 传入 snapshot 过滤层。本测试守护两层：
# ① run_status 参数归一化/透传；② 不同 dimensions 断言不同输出。

def test_run_status_dimensions_reach_snapshot_and_differ():
    """dimensions 数组必须原样到达 provider.snapshot，且不同维度产生不同回执."""
    from llm_loop.introspection.tools_status import run_status

    received: list = []

    class _Provider:
        def snapshot(self, dimensions=None):
            received.append(dimensions)
            if dimensions:
                return {
                    d: (
                        {"v": d}
                        if d in {"rules_version", "exception_log"}
                        else {"unavailable": f"维度 '{d}' 暂不可用"}
                    )
                    for d in dimensions
                }
            return {"current_phase": {"phase": "full"}, "action_trace": ["x" * 200] * 30}

    class _Ctx:
        session_id = "t-dims"

    r1 = run_status(_Ctx(), _Provider(), {"dimensions": ["rules_version"]})
    r2 = run_status(_Ctx(), _Provider(), {"dimensions": ["config"]})
    # ① 透传：两次调用的 dimensions 原样到达 snapshot（未被吞/未被改写为 None）
    assert received == [["rules_version"], ["config"]]
    # ② 差异：合法维度返回实值，非法维度如实标注 unavailable，两者内容必须不同
    assert "rules_version" in r1.content
    assert "暂不可用" in r2.content
    assert r1.content != r2.content, "不同 dimensions 返回相同输出（同回执 bug 回归）"


def test_run_status_dimensions_string_form_normalized():
    """字符串形态 dimensions（如 'rules_version'）归一化为列表后同样到达 snapshot."""
    from llm_loop.introspection.tools_status import run_status

    received: list = []

    class _Provider:
        def snapshot(self, dimensions=None):
            received.append(dimensions)
            return {"rules_version": "4"} if dimensions == ["rules_version"] else {}

    class _Ctx:
        session_id = "t-dims-str"

    r = run_status(_Ctx(), _Provider(), {"dimensions": "rules_version"})
    assert received == [["rules_version"]]
    assert "4" in r.content
