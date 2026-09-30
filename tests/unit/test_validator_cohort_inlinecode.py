"""EVO-20260930: cohort 分层 + 引用内容二次抽取修复 + 跨轮 telemetry 回归锁定.

实证来源:
- DC-20260930T080447006508: 回答引用历史审计文本（inline code bullet，动词全在
  `...` span 内）被重新抽为完成声明 → 引用豁免（动词在 span 外不豁免，防漏网）
- 全量 declaration_check cross_round_hits=0 但单测路径可达 → 先加 eligible
  telemetry；持续 eligible>0 且 hit=0 才有退役讨论依据
- 历史 cohort（2026-09-03 前 1119 行无 id 匿名段）≠ 当前代次 → 审计记录带
  validator_version，precision/误报归因按代次切分
"""

from __future__ import annotations

import json
import pathlib
import tempfile

from llm_loop.feedback.validator import (
    VALIDATOR_VERSION,
    DeclarationValidator,
    ToolResultStatus,
)


class _TM:
    def __init__(self, name, content, status=ToolResultStatus.SUCCESS, meta=None):
        self.tool_name, self.content, self.status = name, content, status
        self.metadata = meta


def _v(audit_dir=None):
    kw = {"semantic_matcher": None}
    if audit_dir is not None:
        kw["audit_dir"] = audit_dir
    return DeclarationValidator(**kw)


# ── 引用豁免: inline code 内容不被二次抽为自身完成声明 ──


def test_quoted_inline_code_bullets_not_extracted():
    """实证回归（DC-20260930T080447006508）: 引用历史审计/证据文本 → 引用内容，不抽取."""
    v = _v()
    text = "\n".join(
        [
            "- `✅ RULE-AI-19 已落地理解，**不重复执行**——lite v3 + SoT + en + 测试都已在镜像 5117923`",
            "- `【方法层执行报告】— L0 六条逐项证据`",
            "- `/solution/evidence/tags/status=active 全部写入完整`",
        ]
    )
    assert v._extract_declarations(text) == []


def test_quoted_inline_code_does_not_exempt_own_claim():
    """防漏网: 动词在 span 外（'已写入 `src/a.py`'）仍是自身完成声明，路径 token 保留."""
    v = _v()
    decls = v._extract_declarations("已写入 `src/a.py`，回归测试通过")
    assert len(decls) == 1
    assert "src/a.py" in decls[0]


def test_mixed_quote_and_claim_keeps_claim():
    """混合句: 引用内容 + 真声明同句 → 整句保留（宁误报不漏网，不因含引用豁免真声明）."""
    v = _v()
    decls = v._extract_declarations("GPT 说 `已执行命令 X`，我也已写入 out.txt")
    assert len(decls) == 1
    assert "out.txt" in decls[0]


# ── cohort 分层: 审计记录携带 validator_version / session 可见性 ──


def test_audit_record_carries_validator_version():
    with tempfile.TemporaryDirectory() as td:
        audit = pathlib.Path(td)
        v = _v(audit_dir=audit)
        v.check("读到了", [_TM("read_file", "读取 data/x.jsonl 完成")])
        row = json.loads((audit / "declaration_check.jsonl").read_text().splitlines()[-1])
        assert row["validator_version"] == VALIDATOR_VERSION
        # contextvar 未设 → "" 共享缓冲串扰风险在审计可见（不静默）
        assert row["session_untracked"] is True


# ── 跨轮 telemetry: eligible 基数可见（先量化，再谈退役）──


def test_cross_round_eligible_telemetry_recorded():
    with tempfile.TemporaryDirectory() as td:
        audit = pathlib.Path(td)
        v = _v(audit_dir=audit)
        # r1: 滚入回执；r2: 无声明（eligible=0）；r3: 本轮 miss → eligible=1 且历史命中
        v.check("读到了", [_TM("read_file", "读取 data/audit/evolution_suggestions.jsonl 完成 121 行")])
        v.check("ok", [_TM("web_search", "无关结果")])
        r = v.check(
            "登记成功了 EVO-20260917-45863aeb → executed，依据是此前已读取 data/audit/evolution_suggestions.jsonl 的内容",
            [],
        )
        assert r.consistent is True
        rows = (audit / "declaration_check.jsonl").read_text().splitlines()
        last = json.loads(rows[-1])
        assert last["cross_round_eligible"] >= 1
        assert last["cross_round_hits"]
        # r1/r2 无 miss → eligible=0
        assert json.loads(rows[0])["cross_round_eligible"] == 0
        assert json.loads(rows[1])["cross_round_eligible"] == 0
