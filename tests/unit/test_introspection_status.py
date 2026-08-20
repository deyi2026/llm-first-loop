

# ── 2026-08-20: 维度参数鲁棒归一化（EVO-20260820-6857bf41 修复）──

def test_normalize_dimensions_handles_malformed_inputs():
    """模型传残缺 JSON 字符串/垃圾维度名 → 过滤到合法集或回落全量（不假错误）."""
    from llm_loop.introspection.status import _normalize_dimensions

    known = {"architecture_config", "exception_log", "recovery", "pending_actions", "context_usage"}
    # 残缺 JSON 数组字符串（实测形态）→ 提取合法项
    assert _normalize_dimensions('["architecture_config", "recovery"', known) == [
        "architecture_config", "recovery",
    ]
    # 垃圾前缀 + 合法项 → 保留合法项
    assert _normalize_dimensions('item["evolution_summary", "recovery"', known) == ["recovery"]
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
