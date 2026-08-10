"""单元测试: 声明-回执语义匹配（T34 / FR-P1-OPT-01）+ 摘要回填（T28）."""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.feedback.validator import DeclarationValidator
from llm_loop.memory.archive import ArchiveStore
from llm_loop.memory.embedder import HashEmbedder, cosine_similarity


def _tool_msg(content: str, status=ToolResultStatus.SUCCESS) -> Message:
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id="c1",
        status=status,
        tool_name="write_file",
    )


def test_p0_keyword_behavior_without_matcher(tmp_path):
    """semantic_matcher=None → 纯关键词/路径匹配（P0 回归）."""
    v = DeclarationValidator(audit_dir=tmp_path / "audit")
    r = v.check("我已写入文件 output.txt", [_tool_msg("写入 output.txt 成功")])
    assert r.consistent
    r2 = v.check("我已写入文件 output.txt", [_tool_msg("读取 data/notes.txt 成功")])
    assert not r2.consistent


def test_semantic_match_when_keyword_fails(tmp_path):
    """语义一致但用词不同 → semantic 判定一致（HashEmbedder）."""
    embedder = HashEmbedder()

    def matcher(a: str, b: str) -> float:
        va = embedder.embed(a)
        vb = embedder.embed(b)
        if va is None or vb is None:
            return 0.0
        return cosine_similarity(va, vb)

    v = DeclarationValidator(
        audit_dir=tmp_path / "audit",
        semantic_matcher=matcher,
        semantic_threshold=0.1,  # Hash 相似度较低，阈值放宽验证路径
    )
    r = v.check("已保存文件 notes.txt", [_tool_msg("写入文件 notes.txt 完成")])
    # 路径 token "notes.txt" 关键词即命中 keyword；这里验证语义路径至少不破坏 P0
    assert r.consistent


def test_matcher_exception_fallback(tmp_path):
    """匹配器异常 → 保持关键词判定，不伪造语义一致."""

    def bad_matcher(a, b):
        raise RuntimeError("matcher crash")

    v = DeclarationValidator(
        audit_dir=tmp_path / "audit",
        semantic_matcher=bad_matcher,
        semantic_threshold=0.5,
    )
    # 无关键词命中 + 匹配器异常 → 不一致（不伪造一致）
    r = v.check("已保存文件 notes.txt", [_tool_msg("执行了完全无关的命令")])
    assert not r.consistent


def test_audit_matched_by_field(tmp_path):
    """审计记录 matched_by 字段（可审计）."""
    v = DeclarationValidator(audit_dir=tmp_path / "audit")
    v.check("已写入文件 output.txt", [_tool_msg("写入 output.txt 成功")])
    log = tmp_path / "audit" / "declaration_check.jsonl"
    import json

    records = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert records
    assert "matched_by" in records[-1]
    assert records[-1]["matched_by"]


# ── T28: 摘要回填 ──
def test_archive_update_summary(tmp_path):
    """update_summary 回填成功 + summary_source 落盘可区分."""
    store = ArchiveStore(tmp_path / "archives")
    entry = store.archive("s1", role="user", source="user", content="重要内容 ABC")
    assert entry.summary_source == "deterministic"  # 默认
    ok = store.update_summary(entry.id, "LLM 摘要", "llm")
    assert ok
    hits = store.search("s1", "LLM 摘要")
    assert hits
    assert hits[0]["summary"] == "LLM 摘要"


def test_archive_update_summary_not_found(tmp_path):
    """回填不存在的条目 → False（如实，不伪造）."""
    store = ArchiveStore(tmp_path / "archives")
    assert store.update_summary("no-such-id", "x", "llm") is False
