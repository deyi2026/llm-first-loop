"""knowledge_score（独立打分器接入）单测——全 mock，不打真实服务。

覆盖: 协议构造 / 解析校验（缺键/概率和/越界/超时/非JSON）/ state_builder
（经验卡+方法卡+多条使用记录展开）/ --all-pending slot 去重 / ledger 原子追加
+ torn-tail 防护 + 重启读取 / 写回 adopted 与否 + 幂等 / CLI dry-run 零写入 /
逐卡隔离与退出码。
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

from llm_loop.knowledge_score.card_writeback import sidecar_path, write_sidecard
from llm_loop.knowledge_score.client import (
    LEVELS,
    ScoreResult,
    ScorerResponseError,
    ScorerTransportError,
    build_request_body,
    parse_response,
    score_state,
)
from llm_loop.knowledge_score.ledger import (
    SCHEMA_KNOWLEDGE_SCORE,
    KnowledgeScoreLedger,
    build_success_entry,
)
from llm_loop.knowledge_score.pending import scan_pending
from llm_loop.knowledge_score.state_builder import (
    CardParseError,
    build_state,
    find_card,
    parse_front_matter,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "knowledge_score.py"

# bench_scoring.py LEVELS 逐字对照（协议常量不被无声漂移）
EXPECTED_LEVELS = [
    "无帮助: 条目与任务不对题,或使用后无效果",
    "轻微帮助: 仅个别细节被参考,整体路径不受其影响",
    "中等帮助: 部分思路被采纳,需较大改造后起作用",
    "显著帮助: 主要路径按条目执行,明显减少试错",
    "决定性帮助: 条目直接命中问题,照做即解决",
]

EXPERIENCE_MD = """---
title: 工具参数完整度分层修复
scenario: "本地部署模型工具调用参数完整度只有58%"
root_cause: 检查器假阳性与模型真实漏参混在一起，无法定位
solution: "程序层做precheck required校验兜底，提示层做schema description强化，分层实施"
evidence: 实施后参数完整度从58%提升
tags: [tools, precheck, llm]
source:
  session: s-20260101
  agent: tester
status: active
created_at: "2026-01-01T10:00:00+08:00"
record_kind: experience
---

分层实施正文。
"""

METHOD_MD = """---
name: method-root-cause
method_id: method-root-cause
description: 根因分析：先冻结真实 baseline，再单变量实验区分变量
status: active
---

# Root Cause Analysis

正文。
"""

EXP_STEM = "EXPERIENCE-20260101-test-card"


def _exp_use(
    slot: str = "a" * 64,
    seq: int = 1,
    decision: str = "applied",
    benefit: str = "helped",
    note: str = "按该分层方法实施后参数完整度从58%提升，且区分假阳性步骤避免了误修检查器",
    slot_present: bool = True,
) -> dict:
    entry = {
        "schema": "experience-use/v2",
        "ts": f"2026-01-02T10:0{seq}:00+08:00",
        "experience_ref": f"experience:{EXP_STEM}",
        "use_decision": decision,
        "benefit": benefit,
        "note": note,
        "evidence_refs": [],
        "work_unit_id": "wu-001",
        "work_unit_binding": "explicit",
        "read_version": "f" * 64,
        "submission_hash": "5" * 64,
        "ledger_seq": seq,
    }
    if slot_present:
        entry["slot_id"] = slot
    return entry


def _method_use(slot: str = "b" * 64, seq: int = 1, decision: str = "adapted") -> dict:
    return {
        "schema": "method-use/v2",
        "ts": f"2026-01-03T09:0{seq}:00+08:00",
        "method_ref": "method:method-root-cause",
        "decision": decision,
        "benefit": "helped",
        "note": "先冻结 baseline 后定位到根因再修，未走盲目重试",
        "evidence_refs": ["evidence://v1/abc"],
        "work_unit_id": "wu-002",
        "read_version": "9" * 64,
        "submission_hash": "6" * 64,
        "slot_id": slot,
        "ledger_seq": seq,
    }


def make_root(tmp_path: Path, exp_uses=(), method_uses=()) -> Path:
    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir(parents=True)
    (exp_dir / f"{EXP_STEM}.md").write_text(EXPERIENCE_MD, encoding="utf-8")
    method_dir = tmp_path / "data" / "methods" / "method-root-cause"
    method_dir.mkdir(parents=True)
    (method_dir / "METHOD.md").write_text(METHOD_MD, encoding="utf-8")
    if exp_uses:
        (exp_dir / "usage.jsonl").write_text(
            "".join(json.dumps(u, ensure_ascii=False) + "\n" for u in exp_uses),
            encoding="utf-8",
        )
    if method_uses:
        (tmp_path / "data" / "methods" / "usage.jsonl").write_text(
            "".join(json.dumps(u, ensure_ascii=False) + "\n" for u in method_uses),
            encoding="utf-8",
        )
    return tmp_path


def _ok_payload(
    *, probs: dict | None = None, conf: float = 0.9, noul: float = 0.8
) -> dict:
    return {
        "answers": {
            "usefulness": {
                "probabilities": probs
                or {"0": 0.02, "1": 0.03, "2": 0.05, "3": 0.1, "4": 0.8},
                "confidence": conf,
            },
            "evidence_sufficient": {"noul": noul},
        },
        "timing_ms": {"wall": 700},
        "model": "27B-Instant-MLX-8bit",
    }


def _result(
    *, top: int = 4, conf: float = 0.9, noul: float = 0.8
) -> ScoreResult:
    return parse_response(_ok_payload(conf=conf, noul=noul))


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _load_cli():
    spec = importlib.util.spec_from_file_location("knowledge_score_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── 1. 协议构造 ──────────────────────────────────────────────────────────


def test_build_request_body_protocol():
    body = build_request_body("任务X")
    assert body["state"] == "任务X"
    assert body["return_details"] is True
    questions = body["questions"]
    assert set(questions) == {"usefulness", "evidence_sufficient"}
    usefulness = questions["usefulness"]
    assert usefulness["type"] == "score"
    assert usefulness["criteria"] == EXPECTED_LEVELS == LEVELS
    assert usefulness["instructions"] == "该经验条目在此任务中的实际帮助程度是哪一档?"
    evidence = questions["evidence_sufficient"]
    assert evidence["type"] == "noul"
    assert set(evidence["criteria"]) == {"true", "false"}
    assert evidence["instructions"] == "当前 state 提供的证据是否足以支撑判断?"


# ── 2. 解析校验 ──────────────────────────────────────────────────────────


def test_parse_response_valid():
    result = parse_response(_ok_payload())
    assert result.top_level == 4
    assert result.top_label == "决定性帮助"
    assert result.expected == pytest.approx(
        0 * 0.02 + 1 * 0.03 + 2 * 0.05 + 3 * 0.1 + 4 * 0.8
    )
    assert result.confidence == 0.9
    assert result.p_evidence_sufficient == 0.8
    assert result.model == "27B-Instant-MLX-8bit"
    assert set(result.probabilities) == {"0", "1", "2", "3", "4"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("answers"),
        lambda p: p["answers"].pop("usefulness"),
        lambda p: p["answers"].pop("evidence_sufficient"),
        lambda p: p["answers"]["usefulness"].pop("probabilities"),
        lambda p: p["answers"]["usefulness"].pop("confidence"),
        lambda p: p["answers"]["evidence_sufficient"].pop("noul"),
        lambda p: p["answers"]["usefulness"]["probabilities"].pop("3"),
    ],
)
def test_parse_response_missing_keys(mutate):
    payload = _ok_payload()
    mutate(payload)
    with pytest.raises(ScorerResponseError):
        parse_response(payload)


def test_parse_response_probability_sum_anomaly():
    payload = _ok_payload(
        probs={"0": 0.4, "1": 0.1, "2": 0.1, "3": 0.1, "4": 0.1}  # 和=0.8
    )
    with pytest.raises(ScorerResponseError, match="不 ≈1"):
        parse_response(payload)


@pytest.mark.parametrize(
    "field,value",
    [("confidence", 1.5), ("confidence", -0.1)],
)
def test_parse_response_out_of_range(field, value):
    payload = _ok_payload()
    if field == "confidence":
        payload["answers"]["usefulness"]["confidence"] = value
    with pytest.raises(ScorerResponseError):
        parse_response(payload)


def test_parse_response_non_dict():
    with pytest.raises(ScorerResponseError):
        parse_response([1, 2])


def test_score_state_ok(monkeypatch):
    from llm_loop.knowledge_score import client

    monkeypatch.setattr(
        client, "_urlopen", lambda req, timeout: _FakeResponse(
            json.dumps(_ok_payload()).encode("utf-8")
        )
    )
    result = score_state("任意 state")
    assert result.top_level == 4


def test_score_state_timeout(monkeypatch):
    from llm_loop.knowledge_score import client

    def raise_timeout(req, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(client, "_urlopen", raise_timeout)
    with pytest.raises(ScorerTransportError):
        score_state("state")


def test_score_state_urlerror(monkeypatch):
    from llm_loop.knowledge_score import client

    def raise_url(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client, "_urlopen", raise_url)
    with pytest.raises(ScorerTransportError):
        score_state("state")


def test_score_state_http_error(monkeypatch):
    from llm_loop.knowledge_score import client

    def raise_http(req, timeout):
        raise urllib.error.HTTPError(
            "u", 500, "server error", {}, None  # type: ignore[arg-type]
        )

    monkeypatch.setattr(client, "_urlopen", raise_http)
    with pytest.raises(ScorerTransportError):
        score_state("state")


def test_score_state_non_json(monkeypatch):
    from llm_loop.knowledge_score import client

    monkeypatch.setattr(
        client, "_urlopen", lambda req, timeout: _FakeResponse(b"<html>bad</html>")
    )
    with pytest.raises(ScorerResponseError):
        score_state("state")


# ── 3. state_builder ─────────────────────────────────────────────────────


def test_state_builder_experience_card(tmp_path):
    make_root(tmp_path, exp_uses=[_exp_use()])
    card = find_card(tmp_path, f"experience:{EXP_STEM}")
    assert card.kind == "experience"
    assert card.title == "工具参数完整度分层修复"
    assert card.tags == ("tools", "precheck", "llm")
    assert card.version and len(card.version) == 64
    state = build_state(card, _exp_use())
    assert state.startswith("任务: 工作单元 wu-001")
    assert "使用的经验条目" in state
    assert "工具参数完整度分层修复" in state
    assert "实际使用结果" in state
    assert "直接采用" in state
    assert "参数完整度从58%提升" in state


def test_state_builder_method_card(tmp_path):
    make_root(tmp_path, method_uses=[_method_use()])
    card = find_card(tmp_path, "method:method-root-cause")
    assert card.kind == "method"
    assert card.slug == "method-root-cause"
    state = build_state(card, _method_use())
    assert "使用的方法条目" in state
    assert "根因分析" in state
    assert "改造后采用" in state
    assert "evidence://v1/abc" in state


def test_state_builder_seed_dir_fallback(tmp_path):
    (tmp_path / "methods" / "method-seed-only").mkdir(parents=True)
    (tmp_path / "methods" / "method-seed-only" / "METHOD.md").write_text(
        METHOD_MD.replace("method-root-cause", "method-seed-only"), encoding="utf-8"
    )
    card = find_card(tmp_path, "method:method-seed-only")
    assert card.ref == "method:method-seed-only"


def test_state_builder_multi_use_expansion(tmp_path):
    """单卡多条使用记录：每条独立一个 state（一对多，不合并）。"""
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64, seq=1, decision="applied"),
            _exp_use(slot="c" * 64, seq=2, decision="not_applicable",
                     note="本次任务不对题，未采用"),
        ],
    )
    card = find_card(tmp_path, f"experience:{EXP_STEM}")
    states = [
        build_state(card, u)
        for u in (json.loads(ln) for ln in
                  (tmp_path / "experiences" / "usage.jsonl").read_text().splitlines())
    ]
    assert len(states) == 2
    assert states[0] != states[1]
    assert "直接采用" in states[0]
    assert "判定不适用" in states[1]


def test_state_builder_front_matter_errors():
    from llm_loop.knowledge_score import state_builder as sb

    with pytest.raises(CardParseError):
        sb.parse_front_matter("no front matter")
    with pytest.raises(CardParseError):
        sb.parse_front_matter("---\ntitle: x\n")


def test_find_card_ambiguous(tmp_path):
    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir()
    for name in ("EXPERIENCE-a-one.md", "EXPERIENCE-a-two.md"):
        (exp_dir / name).write_text(EXPERIENCE_MD, encoding="utf-8")
    with pytest.raises(ValueError):
        find_card(tmp_path, "experience:EXPERIENCE-a")


# ── 4. --all-pending slot 去重 ───────────────────────────────────────────


def test_scan_pending_groups_slot_revisions(tmp_path):
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64, seq=1, note="第一次提交"),
            _exp_use(slot="a" * 64, seq=2, note="修订提交"),
            _exp_use(slot="c" * 64, seq=3),
        ],
        method_uses=[_method_use()],
    )
    items = scan_pending(tmp_path)
    keys = [i.slot_key for i in items]
    assert keys.count("a" * 64) == 1  # 修订链折叠为链尾
    head = next(i for i in items if i.slot_key == "a" * 64)
    assert head.use_entry["note"] == "修订提交"
    assert len(items) == 3  # slotA + slotC + method


def test_scan_pending_excludes_covered_slots(tmp_path):
    make_root(
        tmp_path,
        exp_uses=[_exp_use(slot="a" * 64, seq=1), _exp_use(slot="c" * 64, seq=2)],
    )
    ledger = KnowledgeScoreLedger.for_root(tmp_path)
    ledger.append(
        build_success_entry(
            scorer_model="m", kind="experience", ref=f"experience:{EXP_STEM}",
            version="v", slot_id="a" * 64, slot_key="a" * 64,
            decision_reported="applied", top_level=3, top_label="显著帮助",
            expected=2.5, confidence=0.8, p_evidence_sufficient=0.7,
            probabilities={"0": 0.1, "1": 0.1, "2": 0.2, "3": 0.4, "4": 0.2},
            adopted=True, writeback_target="x",
        )
    )
    items = scan_pending(tmp_path)
    assert [i.slot_key for i in items] == ["c" * 64]


def test_scan_pending_error_row_allows_retry(tmp_path):
    """error 行不算已打分记录——允许重试。"""
    make_root(tmp_path, exp_uses=[_exp_use(slot="a" * 64)])
    from llm_loop.knowledge_score.ledger import build_error_entry

    KnowledgeScoreLedger.for_root(tmp_path).append(
        build_error_entry(
            scorer_model="", kind="experience", ref=f"experience:{EXP_STEM}",
            version="", slot_id="a" * 64, slot_key="a" * 64,
            decision_reported="applied", error="boom",
        )
    )
    assert [i.slot_key for i in scan_pending(tmp_path)] == ["a" * 64]


def test_scan_pending_limit(tmp_path):
    make_root(tmp_path, exp_uses=[_exp_use(slot=c * 64, seq=i + 1) for i, c in enumerate("ace")])
    assert len(scan_pending(tmp_path, limit=2)) == 2


def test_scan_pending_noslot_fallback_key(tmp_path):
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(seq=1, slot_present=False),
            _exp_use(seq=2, slot_present=False),
        ],
    )
    items = scan_pending(tmp_path)
    assert len(items) == 2
    assert all(i.slot_key.startswith("noslot:experience:") for i in items)
    assert len({i.slot_key for i in items}) == 2


# ── 5. ledger：原子追加 + torn-tail + 重启读取 ────────────────────────────


def _score_entry(seq_slot: str) -> dict:
    return build_success_entry(
        scorer_model="27B-Instant-MLX-8bit",
        kind="experience",
        ref=f"experience:{EXP_STEM}",
        version="f" * 64,
        slot_id=seq_slot,
        slot_key=seq_slot,
        decision_reported="applied",
        top_level=4,
        top_label="决定性帮助",
        expected=3.2,
        confidence=0.9,
        p_evidence_sufficient=0.8,
        probabilities={"0": 0.0, "1": 0.0, "2": 0.1, "3": 0.1, "4": 0.8},
        adopted=True,
        writeback_target="data/knowledge_scores/cards/x.json",
    )


def test_ledger_append_and_restart(tmp_path):
    ledger = KnowledgeScoreLedger(tmp_path / "data" / "knowledge_scores" / "ledger.jsonl")
    row1 = ledger.append(_score_entry("a" * 64))
    row2 = ledger.append(_score_entry("c" * 64))
    assert row1["schema"] == SCHEMA_KNOWLEDGE_SCORE
    assert [row1["ledger_seq"], row2["ledger_seq"]] == [1, 2]
    assert row1["integrity"] and row2["integrity"]
    # 重启读取：新实例读到同样内容
    restarted = KnowledgeScoreLedger(ledger.path)
    assert [r["slot_key"] for r in restarted.read()] == ["a" * 64, "c" * 64]
    assert restarted.covered_slot_keys() == {"a" * 64, "c" * 64}


def test_ledger_integrity_tamper_detected(tmp_path):
    ledger = KnowledgeScoreLedger.for_root(tmp_path)
    ledger.append(_score_entry("a" * 64))
    raw = ledger.path.read_text(encoding="utf-8")
    tampered = raw.replace('"expected":3.2', '"expected":9.9')
    ledger.path.write_text(tampered, encoding="utf-8")
    assert ledger.read() == []  # 完整性不匹配 → 不进完好条目


def test_ledger_torn_tail_quarantine(tmp_path):
    ledger = KnowledgeScoreLedger.for_root(tmp_path)
    ledger.append(_score_entry("a" * 64))
    ledger.append(_score_entry("c" * 64))
    # 模拟 torn tail：半行 JSON、无换行
    with ledger.path.open("a", encoding="utf-8") as fh:
        fh.write('{"schema": "knowledge-score/v1", "ts": "20')
    assert len(ledger.read()) == 2  # 坏尾不进完好条目
    # 追加前守卫：隔离坏尾再追加（重启安全）
    ledger.append(_score_entry("e" * 64))
    assert len(ledger.read()) == 3
    corrupt = ledger.path.with_name(ledger.path.name + ".corrupt")
    assert corrupt.is_file()
    assert b'"ts": "20' in corrupt.read_bytes()


def test_ledger_append_after_missing_trailing_newline(tmp_path):
    """外部重写导致末行缺换行：追加时先补换行，不粘连成坏行。"""
    ledger = KnowledgeScoreLedger.for_root(tmp_path)
    ledger.append(_score_entry("a" * 64))
    raw = ledger.path.read_text(encoding="utf-8")
    ledger.path.write_text(raw.rstrip("\n"), encoding="utf-8")
    ledger.append(_score_entry("c" * 64))
    assert len(ledger.read()) == 2


# ── 6. 写回：adopted / 不 adopted / 幂等 ─────────────────────────────────


def test_writeback_sidecard_fields(tmp_path):
    make_root(tmp_path, exp_uses=[_exp_use()])
    card = find_card(tmp_path, f"experience:{EXP_STEM}")
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    payload = write_sidecard(cards_dir, card=card, result=_result(),
                             slot_id="a" * 64, use_ts="2026-01-02T10:00:00+08:00")
    target = sidecar_path(cards_dir, card.slug)
    assert target.is_file()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk == payload
    assert on_disk["evidence_level"] == "independently_evaluated"
    assert on_disk["top_level"] == 4
    assert on_disk["top_label"] == "决定性帮助"
    assert on_disk["scorer_model"] == "27B-Instant-MLX-8bit"
    assert on_disk["card_version_at_scoring"] == card.version
    assert on_disk["kind"] == "experience"
    assert "last_scored_at" in on_disk


def test_writeback_idempotent_update_not_pileup(tmp_path):
    """重复打分：同卡更新而非堆积重复块。"""
    make_root(tmp_path, exp_uses=[_exp_use()])
    card = find_card(tmp_path, f"experience:{EXP_STEM}")
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    write_sidecard(cards_dir, card=card, result=_result(top=4),
                   slot_id="a" * 64, use_ts="t1")
    low = parse_response(_ok_payload(
        probs={"0": 0.05, "1": 0.75, "2": 0.1, "3": 0.05, "4": 0.05}))
    write_sidecard(cards_dir, card=card, result=low, slot_id="c" * 64, use_ts="t2")
    files = [p for p in cards_dir.iterdir() if p.suffix == ".json"]
    assert len(files) == 1  # 单文件单块，不堆积
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["top_level"] == 1  # 更新为最新结果
    assert data["top_label"] == "轻微帮助"
    assert len(data["history"]) == 2
    assert data["scored_slots"] == 2


# ── 7. CLI ───────────────────────────────────────────────────────────────


def _snapshot_tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_cli_dry_run_zero_writes(tmp_path, capsys):
    make_root(
        tmp_path,
        exp_uses=[_exp_use(slot="a" * 64)],
        method_uses=[_method_use()],
    )
    cli = _load_cli()
    before = _snapshot_tree(tmp_path)
    code = cli.main(["--root", str(tmp_path), "--all-pending", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "零写入" in out
    assert "-- state --" in out and "-- request body --" in out
    assert "使用的经验条目" in out
    body_line = [ln for ln in out.splitlines() if '"usefulness"' in ln]
    assert body_line
    assert _snapshot_tree(tmp_path) == before  # 文件集合与 mtime 均不变
    assert not (tmp_path / "data" / "knowledge_scores").exists()


def test_cli_all_pending_mocked_flow(tmp_path, capsys, monkeypatch):
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64, seq=1),
            _exp_use(slot="c" * 64, seq=2),
        ],
        method_uses=[_method_use()],
    )
    cli = _load_cli()
    monkeypatch.setattr(cli, "score_state", lambda state, **kw: _result())
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[scored]") == 3
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 3
    assert all(r["schema"] == SCHEMA_KNOWLEDGE_SCORE for r in rows)
    assert all(r["adopted"] is True for r in rows)
    assert {r["writeback_target"] for r in rows} == {
        "data/knowledge_scores/cards/method-root-cause.json",
        f"data/knowledge_scores/cards/{EXP_STEM}.json",
    }
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    assert (cards_dir / f"{EXP_STEM}.json").is_file()
    assert (cards_dir / "method-root-cause.json").is_file()
    # 摘要行内容
    assert "top=4(决定性帮助" in out
    assert "adopted=yes" in out


def test_cli_not_adopted_no_sidecar(tmp_path, capsys, monkeypatch):
    """低证据/低置信 → 只落 ledger，sidecar 不写。"""
    make_root(tmp_path, exp_uses=[_exp_use(slot="a" * 64)])
    cli = _load_cli()
    weak = parse_response(_ok_payload(conf=0.3, noul=0.2))
    monkeypatch.setattr(cli, "score_state", lambda state, **kw: weak)
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    out = capsys.readouterr().out
    assert code == 0
    assert "adopted=no" in out
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert rows[0]["adopted"] is False
    assert rows[0]["writeback_target"] == ""
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    assert not cards_dir.exists()


def test_cli_per_card_isolation_and_exit_codes(tmp_path, capsys, monkeypatch):
    """逐卡隔离：失败写 error 行后继续；部分成功退出码 0。"""
    make_root(
        tmp_path,
        exp_uses=[_exp_use(slot="a" * 64), _exp_use(slot="c" * 64)],
    )
    cli = _load_cli()
    calls = {"n": 0}

    def flaky(state, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScorerTransportError("connection refused")
        return _result()

    monkeypatch.setattr(cli, "score_state", flaky)
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    err = capsys.readouterr().err
    assert code == 0  # 部分成功
    assert "connection refused" in err
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 2
    error_rows = [r for r in rows if r["error"]]
    assert len(error_rows) == 1
    assert error_rows[0]["adopted"] is False
    assert "connection refused" in error_rows[0]["error"]


def test_cli_all_fail_nonzero(tmp_path, capsys, monkeypatch):
    make_root(tmp_path, exp_uses=[_exp_use(slot="a" * 64)])
    cli = _load_cli()

    def dead(state, **kw):
        raise ScorerTransportError("down")

    monkeypatch.setattr(cli, "score_state", dead)
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    assert code == 1
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 1 and rows[0]["error"]


def test_cli_circuit_breaker_stops_after_consecutive_failures(tmp_path, capsys, monkeypatch):
    """服务持续失败时按阈值熔断，避免每卡 120s 拖死调度轮次；仍逐卡写 error 行。"""
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64, seq=1),
            _exp_use(slot="c" * 64, seq=2),
            _exp_use(slot="e" * 64, seq=3),
        ],
    )
    cli = _load_cli()
    calls = {"n": 0}

    def dead(state, **kw):
        calls["n"] += 1
        raise ScorerTransportError("down")

    monkeypatch.setattr(cli, "score_state", dead)
    code = cli.main(
        [
            "--root",
            str(tmp_path),
            "--all-pending",
            "--max-consecutive-failures",
            "2",
        ]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert calls["n"] == 2
    assert "circuit-break" in err
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 2 and all(r["error"] for r in rows)


def test_scan_pending_error_cooldown_skips_recent_failure(tmp_path, capsys, monkeypatch):
    """error 行在冷却期内不再返回，避免永久坏卡每次巡检都追加 error。"""
    make_root(tmp_path, exp_uses=[_exp_use(slot="a" * 64, seq=1)])
    cli = _load_cli()
    monkeypatch.setattr(
        cli,
        "score_state",
        lambda *a, **kw: (_ for _ in ()).throw(ScorerTransportError("down")),
    )
    assert cli.main(["--root", str(tmp_path), "--all-pending", "--max-consecutive-failures", "1"]) == 1
    capsys.readouterr()
    assert len(scan_pending(tmp_path)) == 1
    assert scan_pending(tmp_path, error_cooldown_s=1800) == []


def test_cli_run_lock_blocks_second_process(tmp_path):
    """同一 root 的第二个打分进程在 .run.lock 上拿不到锁。"""
    cli = _load_cli()
    first = cli._acquire_run_lock(tmp_path)
    assert first is not None
    try:
        assert cli._acquire_run_lock(tmp_path) is None
    finally:
        cli._release_run_lock(first)
    again = cli._acquire_run_lock(tmp_path)
    assert again is not None
    cli._release_run_lock(again)


def test_cli_single_ref_multiple_uses(tmp_path, capsys, monkeypatch):
    """--ref 单卡：多条使用记录逐条打分（一对多）。"""
    make_root(
        tmp_path,
        exp_uses=[_exp_use(slot="a" * 64, seq=1), _exp_use(slot="c" * 64, seq=2)],
    )
    cli = _load_cli()
    monkeypatch.setattr(cli, "score_state", lambda state, **kw: _result())
    code = cli.main(["--root", str(tmp_path), "--ref", f"experience:{EXP_STEM}"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[scored]") == 2


def test_cli_ref_without_uses(tmp_path, capsys):
    make_root(tmp_path)  # 有卡无使用回执
    cli = _load_cli()
    code = cli.main(["--root", str(tmp_path), "--ref", f"experience:{EXP_STEM}"])
    err = capsys.readouterr().err
    assert code == 1
    assert "无该卡的使用回执" in err


def test_state_builder_block_scalar_front_matter(tmp_path):
    """真实语料存在 key: | 块标量（如 solution: |）——必须可解析且进 state。"""
    md = """---
title: 块标量卡
scenario: 场景行
root_cause: |
  第一行根因
  第二行根因
solution: >-
  折叠的
  解决方案文本
evidence: "带 \\"转义\\" 引号的证据"
tags: [a, b]
source: {}
status: active
record_kind: lesson
---

正文。
"""
    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir(parents=True)
    (exp_dir / "EXPERIENCE-block.md").write_text(md, encoding="utf-8")
    card = find_card(tmp_path, "experience:EXPERIENCE-block")
    assert "第一行根因\n第二行根因" in card.root_cause
    assert "折叠的 解决方案文本" in card.solution
    assert '带 "转义" 引号的证据' in card.evidence
    meta, _body = parse_front_matter(md)
    assert meta["source"] == {}
    state = build_state(card, _exp_use())
    assert "第一行根因" in state and "使用的教训条目" in state


# ── 8. 独立审查修复回归（P1 / P2-1 / P2-2 / P2-5）─────────────────────────


def test_cli_endpoint_env_precedence(tmp_path, capsys, monkeypatch):
    """P1: 未显式 --endpoint 时 argparse 不得架空 env——请求实际打到 env 端点。"""
    from llm_loop.knowledge_score import client

    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64, seq=1),
            _exp_use(slot="c" * 64, seq=2),
        ],
    )
    cli = _load_cli()
    env_url = "http://env-scorer.example:9527/v1/systemone"
    monkeypatch.setenv("LFL_INDEPENDENT_SCORER_URL", env_url)
    seen: dict[str, str] = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return _FakeResponse(json.dumps(_ok_payload()).encode("utf-8"))

    monkeypatch.setattr(client, "_urlopen", fake_urlopen)
    # 第一跑（--limit 1 → slot a）：不传 --endpoint，应打到 env 端点
    code = cli.main(["--root", str(tmp_path), "--all-pending", "--limit", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[scored]") == 1
    assert seen["url"] == env_url
    # 第二跑（slot c）：显式 --endpoint 仍最高优先
    code = cli.main(
        [
            "--root", str(tmp_path), "--all-pending", "--limit", "1",
            "--endpoint", "http://explicit-scorer.example:1/v1/systemone",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[scored]") == 1
    assert seen["url"] == "http://explicit-scorer.example:1/v1/systemone"


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: http.client.IncompleteRead(b"partial", 4096),
        lambda: http.client.HTTPException("bad status line"),
    ],
    ids=["incomplete-read", "http-exception"],
)
def test_score_state_http_exception_is_transport(monkeypatch, make_exc):
    """P2-1: HTTPException 族（含 IncompleteRead，非 OSError）→ ScorerTransportError。"""
    from llm_loop.knowledge_score import client

    class _DyingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            raise make_exc()

    monkeypatch.setattr(client, "_urlopen", lambda req, timeout: _DyingResponse())
    with pytest.raises(ScorerTransportError):
        score_state("state")


def test_cli_unexpected_exception_per_card_isolation(tmp_path, capsys, monkeypatch):
    """P2-2: 非 ScorerError（RuntimeError）→ 写 error 行后继续，后续卡仍被打分。"""
    make_root(
        tmp_path,
        exp_uses=[
            _exp_use(slot="a" * 64),
            _exp_use(slot="c" * 64, seq=2),
        ],
    )
    cli = _load_cli()
    calls = {"n": 0}

    def flaky(state, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("unexpected kaboom")
        return _result()

    monkeypatch.setattr(cli, "score_state", flaky)
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    captured = capsys.readouterr()
    assert code == 0  # 部分成功，整跑不崩溃
    assert captured.out.count("[scored]") == 1  # 后续卡仍被打分
    assert "unexpected kaboom" in captured.err
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 2
    error_rows = [r for r in rows if r["error"]]
    assert len(error_rows) == 1
    assert error_rows[0]["adopted"] is False
    assert "unexpected:" in error_rows[0]["error"]  # 标注为非预期异常
    assert "unexpected kaboom" in error_rows[0]["error"]


def test_ledger_latest_writeback_failed_latest_row_semantics(tmp_path):
    """P2-5(a) 判据：只有「同 slot 最新行 = 打分成功仅写回失败」才需补写回。"""
    from llm_loop.knowledge_score.ledger import WRITEBACK_FAILED_PREFIX

    ledger = KnowledgeScoreLedger.for_root(tmp_path)
    failed = _score_entry("a" * 64)
    failed["adopted"] = False
    failed["writeback_target"] = ""
    failed["error"] = f"{WRITEBACK_FAILED_PREFIX}: disk full"
    ledger.append(failed)
    assert set(ledger.latest_writeback_failed()) == {"a" * 64}
    # 同 slot 后续出现成功行 → 最新行为干净行，不再需要补写回
    ledger.append(_score_entry("a" * 64))
    assert ledger.latest_writeback_failed() == {}
    # 纯 error 行（打分本身失败、无结果）不属于补写回范畴
    from llm_loop.knowledge_score.ledger import build_error_entry

    ledger.append(
        build_error_entry(
            scorer_model="", kind="experience", ref=f"experience:{EXP_STEM}",
            version="", slot_id="c" * 64, slot_key="c" * 64,
            decision_reported="applied", error="connection refused",
        )
    )
    assert ledger.latest_writeback_failed() == {}


def test_writeback_history_dedup_by_slot(tmp_path):
    """P2-5(b): 同 slot 重打分 history 去重更新而非追加；cap 仍为 8。"""
    from llm_loop.knowledge_score.card_writeback import HISTORY_CAP

    make_root(tmp_path, exp_uses=[_exp_use()])
    card = find_card(tmp_path, f"experience:{EXP_STEM}")
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    low = parse_response(
        _ok_payload(probs={"0": 0.05, "1": 0.75, "2": 0.1, "3": 0.05, "4": 0.05})
    )
    write_sidecard(cards_dir, card=card, result=_result(),
                   slot_id="a" * 64, use_ts="t1")
    write_sidecard(cards_dir, card=card, result=low,
                   slot_id="a" * 64, use_ts="t1-rev")  # 同 slot 重打分
    data = json.loads(sidecar_path(cards_dir, card.slug).read_text(encoding="utf-8"))
    same_slot = [h for h in data["history"] if h["slot_id"] == "a" * 64]
    assert len(same_slot) == 1  # 同 slot 只有一条记录
    assert same_slot[0]["top_level"] == 1  # 且更新为最新结果
    assert same_slot[0]["use_ts"] == "t1-rev"
    assert data["top_level"] == 1
    assert data["scored_slots"] == 1
    # 不同 slot 互不去重；总条目仍被 cap 截断（cap 不变）
    for i in range(HISTORY_CAP + 1):
        write_sidecard(cards_dir, card=card, result=_result(),
                       slot_id=f"slot-{i:02d}", use_ts=f"t{i}")
    data = json.loads(sidecar_path(cards_dir, card.slug).read_text(encoding="utf-8"))
    ids = [h["slot_id"] for h in data["history"]]
    assert len(ids) == HISTORY_CAP
    assert len(set(ids)) == HISTORY_CAP


def test_cli_writeback_retry_replays_from_ledger(tmp_path, capsys, monkeypatch):
    """P2-5(a): 打分成功仅写回失败 → 重跑只补写回，零新打分调用。"""
    make_root(tmp_path, exp_uses=[_exp_use(slot="a" * 64)])
    cli = _load_cli()
    scorer_calls = {"n": 0}

    def scorer(state, **kw):
        scorer_calls["n"] += 1
        return _result()

    monkeypatch.setattr(cli, "score_state", scorer)
    real_write = cli.write_sidecard
    writes = {"n": 0}

    def flaky_write(cards_dir, **kw):
        writes["n"] += 1
        if writes["n"] == 1:
            raise OSError("disk full")
        return real_write(cards_dir, **kw)

    monkeypatch.setattr(cli, "write_sidecard", flaky_write)

    # 第一跑：打分成功、写回失败 → ledger 落「打分成功仅写回失败」行
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    captured = capsys.readouterr()
    assert code == 0
    assert scorer_calls["n"] == 1
    cards_dir = tmp_path / "data" / "knowledge_scores" / "cards"
    assert not (cards_dir / f"{EXP_STEM}.json").exists()
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 1
    assert rows[0]["error"].startswith("writeback failed")
    assert rows[0]["top_level"] == 4  # 打分结果已落账

    # 第二跑：只从 ledger 已落账结果补写回 sidecar，不重打分
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    captured = capsys.readouterr()
    assert code == 0
    assert scorer_calls["n"] == 1  # 零新增 27B 调用
    assert "[writeback-repaired]" in captured.out
    sidecar = cards_dir / f"{EXP_STEM}.json"
    assert sidecar.is_file()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["top_level"] == 4
    assert len(data["history"]) == 1  # 补写回只产生该 slot 一条 history
    rows = KnowledgeScoreLedger.for_root(tmp_path).read()
    assert len(rows) == 2  # 仅追加一行写回补账行（复用原结果，非新打分行）
    repair = rows[1]
    assert repair["error"] == ""
    assert repair["writeback_replayed"] is True
    assert repair["adopted"] is True
    assert repair["top_level"] == rows[0]["top_level"]
    assert repair["probabilities"] == rows[0]["probabilities"]
    assert repair["scorer_model"] == rows[0]["scorer_model"]
    assert repair["writeback_target"].endswith(f"{EXP_STEM}.json")

    # 第三跑：slot 已覆盖 → 无待打分项，零调用、零新行
    code = cli.main(["--root", str(tmp_path), "--all-pending"])
    captured = capsys.readouterr()
    assert code == 0
    assert scorer_calls["n"] == 1
    assert len(KnowledgeScoreLedger.for_root(tmp_path).read()) == 2
    assert KnowledgeScoreLedger.for_root(tmp_path).latest_writeback_failed() == {}
