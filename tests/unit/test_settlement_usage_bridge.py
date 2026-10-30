"""settlement→usage 桥接契约测试（GOAL-20261030-fc31abda 授权例外的落地核查）.

调研结论（2026-10-31，本文件落地前的核实）：
委派背景称「结算回执（settlement 库）与 usage 账本是两套互不相通的写入」——
与代码事实不符。桥接自 TASK-ac085ab1-001/004（commit c72a615c0 起，2026-10-16
前后）即存在且在生产使用：

- settlement_submit 的 kind=method 条目经 ``_run_settlement_submit`` →
  ``submit_settlement_batch`` → ``_submit_one`` → ``MethodStore.record_use``
  直写 store 级 usage 账本（``data/methods/usage.jsonl``）；
- 生产账本（2026-10-30 实测 89 行）中 53 行带 ``run_id``/``attribution``
  溯源字段——method_manage 的 record_use 不传这些字段，只能来自结算通道；
- 「0 条 rejected」是模型行为事实（从未提交过 rejected 结算），不是代码断链。

因此本任务不新增桥接代码（会造成同一条目双写），而是把委派验收标准钉在
**账本级**——既有测试（test_settlement_receipts.py / test_settlement_tools.py）
断言回执字段与幂等回执，本文件补齐：

1. 正常桥接：kind=method committed ⇒ usage 账本恰好 +1 行，decision 1:1，
   evidence_refs/work_unit/session/episode 溯源进 v2 原生字段（不硬造字段）；
2. 幂等重放（硬性）：同一 settlement 提交两次，usage 账本仍然只有一行
   （(slot_id, submission_hash) 在 flock 内先扫后写去重）；unresolved 退化
   slot（无 work_unit/episode）同样只落一行；
3. 四种 decision（applied/adapted/not_applicable/rejected）逐一 1:1 映射；
4. 桥接失败不阻塞：record_use 抛非预期异常 ⇒ 该条目 failed 留原因、
   其余条目照常 committed、事后可补账（可观测痕迹 = failed 回执 reason）；
5. 范围：experience/rule 条目各自落自己的账（experiences/usage.jsonl、
   EventStore rule.feedback），不触碰 method usage 账本；
6. 生命周期收益（治理文档 R3-bis 关切的真正断点）：两个不同 episode 的
   settlement rejected 声明自动喂开 ``_update_status_locked`` 的处置门禁
   （≥2 个不同 episode 的 rejected ⇒ retire/invalidate 获得独立依据）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.event_log.store import EventStore
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.corrections import CorrectionContext, CorrectionToolRegistry
from llm_loop.introspection.rule_index import RuleIndex
from llm_loop.introspection.settlement import (
    RULE_FEEDBACK_EVENT_TYPE,
    SettlementChannel,
    SettlementItem,
    submit_settlement_batch,
)
from llm_loop.methods.store import MethodStore

_CONTRACT_BODY = (
    "## Trigger\nneed the known-good path\n\n"
    "## Discriminator\ntask matches the recorded scenario\n\n"
    "## Short path\nread -> apply -> verify\n\n"
    "## Stop conditions\nverification fails or evidence missing\n\n"
    "## Verification\npytest green\n\n"
    "## Counterexamples\nSSR page\n"
)

_RULES_MD = (
    "# Rules\n\n"
    "## RULE-AI-18 检索留痕\n\n"
    "检索知识库须留痕并按稳定 ref 读取。\n"
)

_EPISODE = "episode:bridge-ep:1:aa"


def _method_store(tmp_path: Path) -> tuple[MethodStore, str]:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="settlement usage bridge fixture", description="bridge fixture",
        body=_CONTRACT_BODY,
    )
    return store, record.method_ref


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "桥接夹具经验",
        "scenario": "场景",
        "root_cause": "",
        "solution": "解法（当前性验证：先 grep -n 解法关键字 src/ 确认仍适用）",
        "evidence": "",
        "tags": [],
        "source": {},
    }
    fields.update(overrides)
    return ExperienceDocument(**fields)


def _experience_store(tmp_path: Path) -> tuple[ExperienceStore, str]:
    store = ExperienceStore(tmp_path / "experiences")
    filename = store.save(_make_doc())
    return store, filename.removesuffix(".md")


def _rule_lookup(tmp_path: Path):
    path = tmp_path / "ai_rules.md"
    path.write_text(_RULES_MD, encoding="utf-8")
    index = RuleIndex(path)
    return lambda ref: bool(index.search(str(ref), 1))


def _host(tmp_path: Path, *, rules: bool = False):
    """构造带结算通道与 episode 溯源解析器的工具面 host."""
    ctx = CorrectionContext()
    ctx.session_id = "sess-1"
    ctx.current_episode_ref_resolver = lambda sid: _EPISODE
    events = EventStore(tmp_path / "events")
    method_store, method_ref = _method_store(tmp_path)
    experience_store, exp_stem = _experience_store(tmp_path)
    ctx.settlement = SettlementChannel(
        event_store=events,
        method_store=method_store,
        experience_store=experience_store,
        rule_lookup=_rule_lookup(tmp_path) if rules else None,
        event_logs_dir=tmp_path / "events",
    )
    host = CorrectionToolRegistry(ctx)
    return host, method_store, method_ref, experience_store, exp_stem, events


def _payload(result) -> dict:
    """回执正文 = header 行 + JSON 载荷（末行）."""
    return json.loads(str(result.content).rsplit("\n", 1)[1])


def _raw_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


# ── 1. 正常桥接：committed ⇒ usage 账本恰好 +1 行，字段原生落位 ──


def test_settlement_method_item_lands_in_usage_ledger_with_native_fields(tmp_path):
    host, method_store, ref, *_ = _host(tmp_path)
    version = method_store.get(ref).content_hash
    args = {
        "work_unit_id": "TASK-A",
        "items": [
            {
                "kind": "method", "ref": ref, "decision": "applied",
                "benefit": "helped", "evidence_level": "observation_linked",
                "evidence_refs": ["run:demo", "file:src/x.py"],
                "read_version": version, "note": "桥接验证",
            }
        ],
    }

    result = host.execute("settlement_submit", args)
    assert result.status == ToolResultStatus.SUCCESS
    receipt = _payload(result)
    assert receipt["counts"]["committed"] == 1

    ledger = tmp_path / "methods" / "usage.jsonl"
    assert _raw_lines(ledger) == 1  # 桥接恰好补一条使用记录
    entries = method_store.usage_entries(ref)
    assert len(entries) == 1
    entry = entries[0]
    # decision 1:1 映射（settlement decision == usage decision，同词表）
    assert entry["decision"] == "applied"
    # 溯源进 v2 原生字段，不硬造结构外字段
    assert entry["evidence_refs"] == ["run:demo", "file:src/x.py"]
    assert entry["work_unit_id"] == "TASK-A"
    assert entry["session_id"] == "sess-1"
    assert entry["episode_ref"] == _EPISODE
    assert entry["read_version"] == version
    assert entry["schema"] == "method-use/v2"
    assert entry["attribution"] == "task(TASK-A)"
    assert entry["slot_id"] and entry["submission_hash"]
    assert receipt["receipts"][0]["submission_hash"] == entry["submission_hash"]


# ── 2. 幂等（硬性）：同一提交两次，usage 只多一条 ──


def test_same_submission_twice_writes_usage_ledger_exactly_once(tmp_path):
    host, method_store, ref, *_ = _host(tmp_path)
    args = {
        "work_unit_id": "TASK-A",
        "items": [{"kind": "method", "ref": ref, "decision": "rejected",
                    "note": "重放我", "evidence_refs": ["run:1"]}],
    }

    first = _payload(host.execute("settlement_submit", args))
    second = _payload(host.execute("settlement_submit", args))

    assert first["counts"]["committed"] == 1
    assert second["receipts"][0]["status"] == "committed"
    assert second["receipts"][0]["idempotent"] is True
    assert second["receipts"][0]["submission_hash"] == first["receipts"][0]["submission_hash"]

    ledger = tmp_path / "methods" / "usage.jsonl"
    assert _raw_lines(ledger) == 1  # 硬性要求：重放不重复写 usage
    assert len(method_store.usage_entries(ref)) == 1


def test_unresolved_replay_without_work_unit_is_also_single_line(tmp_path):
    """unresolved 退化 slot（无 work_unit/episode，slot_id=''）的去重边界.

    resolve_submission 对 slot='' 只折叠 slot='' 的未归属行；本测试证明
    settlement 的 unresolved 幂等在账本级同样成立。
    """
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")
    items = [SettlementItem(kind="method", ref=ref, decision="not_applicable",
                            note="无归属重放")]

    first = submit_settlement_batch(
        items=items, method_store=method_store, event_store=events,
        session_id="sess-1", work_unit_id="", episode_ref="", model="m",
    )
    second = submit_settlement_batch(
        items=items, method_store=method_store, event_store=events,
        session_id="sess-1", work_unit_id="", episode_ref="", model="m",
    )
    assert first["counts"]["committed"] == 1
    assert second["receipts"][0]["idempotent"] is True
    ledger = tmp_path / "methods" / "usage.jsonl"
    assert _raw_lines(ledger) == 1


# ── 3. 四种 decision 逐一 1:1 映射 ──


@pytest.mark.parametrize(
    "decision,proven",
    [
        ("applied", True),
        ("adapted", True),
        ("not_applicable", False),
        ("rejected", False),
    ],
)
def test_each_decision_maps_one_to_one(tmp_path, decision, proven):
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")

    receipt = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=ref, decision=decision)],
        method_store=method_store, event_store=events,
        session_id="sess-1", work_unit_id=f"TASK-{decision}", episode_ref=_EPISODE,
    )
    assert receipt["counts"]["committed"] == 1
    entries = method_store.usage_entries(ref)
    assert len(entries) == 1
    assert entries[0]["decision"] == decision  # 词表一致，原样落账
    assert entries[0]["application_proven"] is proven  # 派生语义随动


# ── 4. 桥接失败不阻塞：坏条目 failed 留原因，其余照常落账，可事后补账 ──


class _LedgerOutageStore(MethodStore):
    """record_use 对指定 ref 抛非预期异常（模拟 usage 账本写入通道故障）."""

    def __init__(self, directory: Path, poison_ref: str) -> None:
        super().__init__(directory)
        self._poison_ref = poison_ref

    def record_use(self, method_ref: str, **kwargs):
        if method_ref == self._poison_ref:
            raise RuntimeError("simulated usage-ledger outage")
        return super().record_use(method_ref, **kwargs)


def test_bridge_failure_fails_item_alone_and_allows_later_repair(tmp_path):
    store = _LedgerOutageStore(tmp_path / "methods", poison_ref="")
    good = store.save_candidate(
        name="good card", description="ok", body=_CONTRACT_BODY,
    )
    poison = store.save_candidate(
        name="poison card", description="will fail", body=_CONTRACT_BODY,
    )
    store._poison_ref = poison.method_ref
    events = EventStore(tmp_path / "events")

    receipt = submit_settlement_batch(
        items=[
            SettlementItem(kind="method", ref=good.method_ref, decision="applied"),
            SettlementItem(kind="method", ref=poison.method_ref, decision="rejected"),
        ],
        method_store=store, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A", episode_ref=_EPISODE,
    )
    # 桥接失败不阻塞批量：好条目 committed，坏条目 failed 带可观测原因
    assert receipt["counts"] == {"committed": 1, "pending": 0, "failed": 1}
    assert "simulated usage-ledger outage" in receipt["receipts"][1]["reason"]
    ledger = tmp_path / "methods" / "usage.jsonl"
    assert _raw_lines(ledger) == 1  # 只有好条目落账

    # 事后补账：通道恢复（去掉毒丸）后重提同一内容 → committed，账本 +1
    store._poison_ref = ""
    repair = submit_settlement_batch(
        items=[SettlementItem(kind="method", ref=poison.method_ref, decision="rejected")],
        method_store=store, event_store=events,
        session_id="sess-1", work_unit_id="TASK-A", episode_ref=_EPISODE,
    )
    assert repair["counts"]["committed"] == 1
    assert _raw_lines(ledger) == 2


# ── 5. 范围：experience/rule 条目不触碰 method usage 账本 ──


def test_experience_and_rule_items_never_touch_method_usage_ledger(tmp_path):
    host, _method_store, _ref, experience_store, exp_stem, events = _host(
        tmp_path, rules=True
    )
    result = host.execute(
        "settlement_submit",
        {
            "work_unit_id": "TASK-A",
            "items": [
                {"kind": "experience", "ref": f"experience:{exp_stem}",
                 "decision": "not_applicable", "benefit": "neutral"},
                {"kind": "rule", "ref": "RULE-AI-18", "decision": "applied",
                 "benefit": "helped", "read_version": "v1"},
            ],
        },
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert _payload(result)["counts"]["committed"] == 2

    # method usage 账本零写入（桥接范围只 method 池）
    assert not (tmp_path / "methods" / "usage.jsonl").exists()
    # 各自落自己的账：experience → 经验使用账本；rule → EventStore rule.feedback
    assert (tmp_path / "experiences" / "usage.jsonl").is_file()
    assert _raw_lines(tmp_path / "experiences" / "usage.jsonl") == 1
    rule_events = [
        e for e in events.read("sess-1") if e.type == RULE_FEEDBACK_EVENT_TYPE
    ]
    assert len(rule_events) == 1


# ── 6. 生命周期收益：两个不同 episode 的 settlement rejected 喂开处置门禁 ──


def test_settlement_rejected_from_two_episodes_opens_disposition_gate(tmp_path):
    """治理关切（card-lifecycle R3-bis 修订）：rejected 信号要能到生命周期.

    前提：桥接存在 ⇒ settlement 的 rejected 声明落 usage 账本（带 episode_ref）；
    本测试端到端证明：两条不同 episode 的 rejected 结算自动构成
    _update_status_locked 认可的独立处置依据（≥2 个不同 episode）。
    """
    method_store, ref = _method_store(tmp_path)
    events = EventStore(tmp_path / "events")

    # 门禁前置：无独立依据时 retire 被拒
    with pytest.raises(ValueError, match="independent factual basis"):
        method_store.update_status(ref, "retired")

    for ep, wu in (
        ("episode:alpha-task:1:aa", "TASK-R1"),
        ("episode:beta-task:2:bb", "TASK-R2"),
    ):
        receipt = submit_settlement_batch(
            items=[SettlementItem(kind="method", ref=ref, decision="rejected",
                                    benefit="hindered", note="不适用",
                                    evidence_refs=["run:x"])],
            method_store=method_store, event_store=events,
            session_id="sess-1", work_unit_id=wu, episode_ref=ep,
        )
        assert receipt["counts"]["committed"] == 1

    entries = method_store.usage_entries(ref)
    assert len(entries) == 2  # 不同 slot（不同工作单元）：两条都是新账
    assert {e["decision"] for e in entries} == {"rejected"}
    assert {e["episode_ref"] for e in entries} == {"episode:alpha-task:1:aa",
                                                    "episode:beta-task:2:bb"}

    # 桥接后的 rejected 信号自动喂开处置门禁
    retired = method_store.update_status(ref, "retired")
    assert retired.status == "retired"
