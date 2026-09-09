def test_double_brace_memory_auto_fix():
    """EVO-20260812-2bd55cf3: {{ }} 双大括号自动纠错为 { }（AI 照抄 Jinja2 模板陷阱）."""
    from llm_loop.memory.extract import extract_memory_blocks

    # 双大括号 → 自动纠错成功
    blocks = extract_memory_blocks(
        '[[memory]] {{"type": "fact", "content": "测试", "keywords": ["k"]}} [[/memory]]'
    )
    assert len(blocks) == 1
    assert blocks[0].get("content") == "测试"
    # 真坏 JSON（双大括号纠错后仍失败）→ 如实报错 + 特征提示
    bad = extract_memory_blocks('[[memory]] {{"type": [ [[/memory]]')
    assert bad and "_parse_error" in bad[0]
    assert "双大括号" in bad[0]["_parse_error"]
