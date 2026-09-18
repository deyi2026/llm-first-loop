"""EVO-20260917-27cd77ed: 完整句单元 + 叙事豁免 + 匹配面扩容 + 窗口 3→8 回归锁定.

实证来源（2026-09-17 declaration_check.jsonl 667 条 false 抽样）:
- 观点句"生产执行层永远是最没议价权的环节"被 ±40 片段误抽 → 叙事豁免
- 决策句"批准执行"（授权语境）被误抽 → 批准/决策豁免
- 早于 3 轮建立的事实无法补证（DC-20260917T105728591696-f08ab5）→ 窗口 8
- 证据出现在回执 120 字之后必然 miss → 匹配面 ≥512
真阳性守护: 含完成标志的真完成声明（含身份幻觉句）不得被任何叙事词豁免。
"""

from llm_loop.feedback.validator import (
    _RECEIPT_DISPLAY_CHARS,
    _RECEIPT_MATCH_CHARS,
    DeclarationValidator,
    ToolResultStatus,
)


def _v(audit_dir=None, recent_window=None):
    kw = {"semantic_matcher": None}
    if audit_dir is not None:
        kw["audit_dir"] = audit_dir
    if recent_window is not None:
        kw["recent_window"] = recent_window
    return DeclarationValidator(**kw)


# ── A: 叙事句豁免（历史 false 实证形态）──


def test_opinion_sentence_exempt():
    v = _v()
    assert v._extract_declarations("生产执行层永远是最没议价权的环节") == []


def test_approval_sentence_exempt():
    v = _v()
    assert v._extract_declarations("批准执行 27cd77ed 落地") == []
    assert v._extract_declarations("等你确认后执行") == []


def test_conclusion_sentence_exempt():
    v = _v()
    # 结论/评估句（含动词"执行"于"执行路径"名词复合中）非完成声明
    assert v._extract_declarations("评估结果：方案B正确，执行路径最优") == []


def test_uncommitted_state_clause_exempt():
    v = _v()
    assert v._extract_declarations("镜像目录也是 git 仓库且带未提交修改") == []


def test_third_party_passive_exempt():
    v = _v()
    assert v._extract_declarations("文章已被作者删除、下线，或链接本身有误") == []


def test_metric_noun_exempt():
    v = _v()
    assert v._extract_declarations("该包月下载 30,031，未见第三方评测") == []


def test_cognitive_object_exempt():
    v = _v()
    assert v._extract_declarations("以严格评审者身份对方案执行实质拷问") == []


def test_enum_options_exempt():
    v = _v()
    assert v._extract_declarations("决策选项：① 从 schema 删除 ② 实现消费") == []


def test_noun_compound_exempt():
    v = _v()
    assert v._extract_declarations("execute_command 的执行环境残留与设计声明不符") == []


# ── A: 完整句单元（路径点号不劈句）──


def test_sentence_split_keeps_path_tokens():
    v = _v()
    decls = v._extract_declarations("已写入 src/a.py 并执行了 git commit。")
    assert len(decls) == 1
    assert "src/a.py" in decls[0]
    assert "git commit" in decls[0]


def test_full_sentence_unit_not_fragment():
    v = _v()
    # 完整句作为校验单元（±40 片段仅可用于高亮）
    decls = v._extract_declarations("核对完成，本轮实际已写入补丁到 docs/report.md 文件末尾。")
    assert len(decls) == 1
    assert decls[0].endswith("文件末尾")


# ── 真阳性守护: 完成标志压倒一切叙事词（防豁免通道被滥用为逃逸路径）──


def test_completion_marker_overrides_narrative_markers():
    v = _v()
    # 含"已"的真完成声明即便携带观点/批准/结论词也必须被抽取
    decls = v._extract_declarations("永远不要怀疑，我已写入 src/real.py，批准人是你。")
    assert any("已写入" in d for d in decls)


def test_self_agent_blocks_third_party_passive():
    v = _v()
    decls = v._extract_declarations("文件 src/a.py 已被我删除。")
    assert any("删除" in d for d in decls)


def test_identity_hallucination_still_extracted():
    v = _v()
    decls = v._extract_declarations("我是 Qwythos，由 Empero AI 创建")
    assert len(decls) == 1  # 无句读符 = 单句整句


# ── C: 跨轮窗口 3 → 8 ──


class _TM:
    def __init__(self, name, content, status=ToolResultStatus.SUCCESS, meta=None):
        self.tool_name, self.content, self.status = name, content, status
        self.metadata = meta


def test_window_eight_recovers_4_round_old_fact():
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        v = _v(audit_dir=pathlib.Path(td))
        # r1: 证据回执（含路径 token）；r2-r4: 淹没轮（把证据推出旧 3 轮窗口）
        v.check("读到了", [_TM("read_file", "读取 data/audit/evolution_suggestions.jsonl 完成 121 行")])
        for i in range(2, 5):
            v.check(f"搜了 {i}", [_TM("web_search", f"无关结果 {i}")])
        # r5: 引用 r1 的事实（旧窗口 3 会 miss；窗口 8 命中 cross_round）
        r = v.check("登记成功了 EVO-20260917-45863aeb → executed，依据是此前已读取 data/audit/evolution_suggestions.jsonl 的内容", [])
        assert r.consistent is True
        assert any("data/audit/evolution_suggestions.jsonl" in h for h in r.cross_round_hits)


def test_window_configurable_back_to_3():
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        v = _v(audit_dir=pathlib.Path(td), recent_window=3)
        v.check("ok", [_TM("read_file", "读取 data/x/y.jsonl 完成")])
        for i in range(2, 5):
            v.check(f"ok {i}", [_TM("web_search", f"无关 {i}")])
        r = v.check("此前已读取 data/x/y.jsonl 的内容，EVO-20260917-45863aeb → executed", [])
        assert r.consistent is False  # 窗口 3 时早轮事实不可补证（旧行为可复现）


# ── B: 匹配面 ≥512（证据在 120 字之后也能命中）──


def test_match_surface_beyond_display_chars():
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        v = _v(audit_dir=pathlib.Path(td))
        long_receipt = "x" * (_RECEIPT_DISPLAY_CHARS + 200) + "写入完成 src/deep/path.py 全部 94854 字节"
        assert "src/deep/path.py" not in long_receipt[:_RECEIPT_DISPLAY_CHARS]
        r = v.check("已写入 src/deep/path.py", [_TM("edit_file", long_receipt)])
        assert r.consistent is True
        # 审计/人读摘要仍为短面（体积与消费方不变）
        assert all(len(s) <= _RECEIPT_DISPLAY_CHARS + 60 for s in r.receipt_summary)


def test_match_surface_constant_at_least_512():
    assert _RECEIPT_MATCH_CHARS >= 512  # 提案下限


# ── 防漏网: 台账状态引用不得被豁免（必须走 B/C 补证，真幻觉可判 false）──


def test_ledger_status_not_exempted_without_evidence():
    v = _v()
    # 无任何证据语境下，"→ executed" 声明必须保持可抽取（否则真幻觉漏网）
    decls = v._extract_declarations("EVO-20260917-45863aeb → executed（此前已登记完成）")
    assert len(decls) == 1
