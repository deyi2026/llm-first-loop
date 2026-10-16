"""TASK-ac085ab1-001 P0 记录契约: 两层幂等键、supersedes 修订链、行级完整性凭据.

设计来源: docs/LFL 任务知识使用反馈与检索闭环设计草案.md v3（幂等键与重复结算 /
边界与失败模式决策表 / 最小实施顺序与验收 P0 行）。全部用 tmp 隔离夹具，不触碰
真实运行数据；双进程场景用 subprocess 夹具（不硬编码绝对路径，PYTHONPATH 取
仓库根的相对推导）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.methods.store import MethodStore
from llm_loop.use_ledger import (
    dedupe_slot_heads,
    derive_slot_id,
    derive_submission_hash,
    read_ledger_entries,
)

_CONTRACT_BODY = (
    "## Trigger\nneed the known-good path\n\n"
    "## Discriminator\ntask matches the recorded scenario\n\n"
    "## Short path\nread -> apply -> verify\n\n"
    "## Stop conditions\nverification fails or evidence missing\n\n"
    "## Verification\npytest green\n\n"
    "## Counterexamples\nSSR page\n"
)


def _method_store(tmp_path: Path) -> tuple[MethodStore, str]:
    store = MethodStore(tmp_path / "methods")
    record = store.save_candidate(
        name="slot identity method", description="contract fixture", body=_CONTRACT_BODY
    )
    return store, record.method_ref


def _make_doc(**overrides) -> ExperienceDocument:
    fields = {
        "title": "契约夹具经验",
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


# ── 两层键程序派生 ──


def test_slot_and_submission_hashes_are_program_derived_and_stable():
    slot_a = derive_slot_id(
        work_unit_id="TASK-A", kind="method", ref="method:m1", version="abc123"
    )
    slot_b = derive_slot_id(
        work_unit_id="TASK-B", kind="method", ref="method:m1", version="abc123"
    )
    slot_new_version = derive_slot_id(
        work_unit_id="TASK-A", kind="method", ref="method:m1", version="def456"
    )
    assert slot_a != slot_b  # 旧反馈不串任务：工作单元不同即不同 slot
    assert slot_a != slot_new_version  # 版本不同即不同 slot

    same = derive_submission_hash(
        decision="applied",
        benefit="helped",
        evidence_level="model_declared",
        evidence_refs=["evidence://v1/a"],
        note="n",
        suggestion="",
    )
    again = derive_submission_hash(
        decision="applied",
        benefit="helped",
        evidence_level="model_declared",
        evidence_refs=["evidence://v1/a"],
        note="n",
        suggestion="",
    )
    corrected = derive_submission_hash(
        decision="applied",
        benefit="hindered",
        evidence_level="model_declared",
        evidence_refs=["evidence://v1/a"],
        note="n",
        suggestion="",
    )
    assert same == again
    assert same != corrected  # 同决定、评价改变 → 不同提交（更正不被吞）


# ── 同内容重试幂等（四类隔离夹具场景 1）──


def test_method_same_content_retry_returns_same_receipt_without_duplicate(tmp_path):
    store, ref = _method_store(tmp_path)
    first = store.record_use(
        ref,
        episode_ref="episode:s1:1:aa",
        decision="applied",
        note="retry probe",
        work_unit_id="TASK-A",
        benefit="helped",
    )
    second = store.record_use(
        ref,
        episode_ref="episode:s1:1:aa",
        decision="applied",
        note="retry probe",
        work_unit_id="TASK-A",
        benefit="helped",
    )
    assert second.get("idempotent") is True
    assert second["submission_hash"] == first["submission_hash"]
    assert second["slot_id"] == first["slot_id"]
    assert second["ledger_seq"] == first["ledger_seq"]
    ledger = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert ledger.count("\n") == 1  # 不重复追加、不重复计数
    summary = store.usage_net(ref)
    assert summary is not None and summary["applied"] == 1


def test_experience_same_content_retry_returns_same_receipt_without_duplicate(tmp_path):
    store, stem = _experience_store(tmp_path)
    kwargs = dict(
        use_decision="adapted",
        note="same content",
        episode_ref="episode:s1:1:bb",
        work_unit_id="TASK-A",
        benefit="neutral",
    )
    first = store.record_use(stem, **kwargs)
    second = store.record_use(stem, **kwargs)
    assert second.get("idempotent") is True
    assert second["submission_hash"] == first["submission_hash"]
    lines = (tmp_path / "experiences" / "usage.jsonl").read_text(encoding="utf-8")
    assert lines.count("\n") == 1


def test_identical_content_for_different_work_units_is_not_folded(tmp_path):
    """同内容跨任务不是重试：submission 去重按 (slot, submission_hash) 收敛."""
    store, ref = _method_store(tmp_path)
    a = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied",
        note="same", work_unit_id="TASK-A",
    )
    b = store.record_use(
        ref, episode_ref="episode:s2:1:bb", decision="applied",
        note="same", work_unit_id="TASK-B",
    )
    assert b.get("idempotent") is not True
    assert a["slot_id"] != b["slot_id"]
    assert a["submission_hash"] == b["submission_hash"]
    summary = store.usage_net(ref)
    assert summary is not None and summary["applied"] == 2


# ── 同 slot 评价更正：supersedes 修订链（四类隔离夹具场景 2）──


def test_method_benefit_correction_appends_revision_and_stats_count_head_only(tmp_path):
    store, ref = _method_store(tmp_path)
    first = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied",
        note="initial", work_unit_id="TASK-A", benefit="unknown",
    )
    corrected = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied",
        note="initial", work_unit_id="TASK-A", benefit="hindered",
    )
    assert corrected.get("idempotent") is not True
    assert corrected["revision"] == 2
    assert corrected["supersedes"] == first["submission_hash"]
    assert corrected["slot_id"] == first["slot_id"]
    entries = store.usage_entries(ref)
    assert len(entries) == 2  # 不改写历史行
    summary = store.usage_net(ref)
    assert summary is not None
    assert summary["applied"] == 1  # 统计按 slot 取链头，修订不重复计数
    assert summary["benefit_counts"]["hindered"] == 1


def test_experience_correction_via_explicit_supersedes_parent_validation(tmp_path):
    store, stem = _experience_store(tmp_path)
    first = store.record_use(
        stem, use_decision="applied", note="v1", episode_ref="episode:s1:1:cc",
        work_unit_id="TASK-A", benefit="helped",
    )
    # 显式指向错误父（不存在）→ 回执 failed（ValueError），不产生断链
    with pytest.raises(ValueError, match="supersedes"):
        store.record_use(
            stem, use_decision="applied", note="v2", episode_ref="episode:s1:1:cc",
            work_unit_id="TASK-A", benefit="mixed", supersedes="deadbeef",
        )
    second = store.record_use(
        stem, use_decision="applied", note="v2", episode_ref="episode:s1:1:cc",
        work_unit_id="TASK-A", benefit="mixed", supersedes=first["submission_hash"],
    )
    assert second["revision"] == 2
    assert second["supersedes"] == first["submission_hash"]
    summary = store.usage_net(f"experience:{stem}")
    assert summary is not None and summary["applied"] == 1
    assert summary["benefit_counts"]["mixed"] == 1


def test_slot_head_dedupe_keeps_chain_head_and_legacy_entries():
    entries = [
        {"submission_hash": "h1", "slot_id": "s1", "revision": 1, "supersedes": ""},
        {"submission_hash": "h2", "slot_id": "s1", "revision": 2, "supersedes": "h1"},
        {"submission_hash": "h3", "slot_id": "s2", "revision": 1, "supersedes": ""},
        {"decision": "applied"},  # legacy：无 slot
    ]
    heads = dedupe_slot_heads(entries)
    hashes = [e.get("submission_hash") for e in heads if e.get("submission_hash")]
    assert set(hashes) == {"h2", "h3"}
    assert any("decision" in e for e in heads)  # legacy 保留


# ── 行级完整性凭据与 torn 尾部恢复（四类隔离夹具场景 3）──


def test_ledger_lines_carry_integrity_credential(tmp_path):
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="cred")
    raw = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    entry = json.loads(raw.strip())
    assert isinstance(entry.get("integrity"), str) and len(entry["integrity"]) == 64


def test_torn_tail_quarantined_to_sidecar_with_diagnostic_report(tmp_path):
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="one")
    store.record_use(ref, episode_ref="episode:s1:2:bb", decision="adapted", note="two")
    ledger = tmp_path / "methods" / "usage.jsonl"
    good_bytes = ledger.read_bytes()
    torn = b'{"ts": "2026-10-15T00:00:00", "method_ref": "method:xx", "decision": "app'
    with ledger.open("ab") as fh:
        fh.write(torn)  # 半行、无换行

    report = store.recover_usage_ledger()

    assert report["quarantined_count"] == 1
    sidecar = tmp_path / "methods" / "usage.jsonl.corrupt"
    assert sidecar.read_bytes() == torn  # 原始字节进隔离旁文件
    diag = json.loads(
        (tmp_path / "methods" / "usage.jsonl.corrupt.report.json").read_text(encoding="utf-8")
    )
    assert diag["quarantined"][0]["byte_start"] == len(good_bytes)
    assert diag["quarantined"][0]["byte_end"] == len(good_bytes) + len(torn)
    assert diag["quarantined"][0]["suspected_cause"]  # 疑似原因非空
    assert ledger.read_bytes() == good_bytes  # 主账本恢复到最后一条完好记录
    assert store.usage_entries(ref)  # 完好记录仍可读


def test_integrity_mismatch_on_last_line_is_quarantined_not_silently_kept(tmp_path):
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="kept")
    store.record_use(ref, episode_ref="episode:s1:2:bb", decision="rejected", note="tampered")
    ledger = tmp_path / "methods" / "usage.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    mutated = json.loads(lines[1])
    mutated["note"] = "rewritten after write"
    lines[1] = json.dumps(mutated, ensure_ascii=False, sort_keys=True)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = store.recover_usage_ledger()

    assert report["quarantined_count"] == 1
    assert report["quarantined"][0]["reason"] == "integrity_mismatch"
    remaining = store.usage_entries(ref)
    assert [e["note"] for e in remaining] == ["kept"]


def test_record_use_after_torn_tail_quarantines_then_appends(tmp_path):
    """append 前先隔离坏尾：绝不直接在坏行上追加."""
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="one")
    ledger = tmp_path / "methods" / "usage.jsonl"
    with ledger.open("ab") as fh:
        fh.write(b'{"partial": "to')

    entry = store.record_use(
        ref, episode_ref="episode:s1:2:bb", decision="adapted", note="after repair",
        work_unit_id="TASK-A",
    )

    assert entry["ledger_seq"] == 2  # 修复后追加，序号不踩坏行
    assert (tmp_path / "methods" / "usage.jsonl.corrupt").exists()
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["submission_hash"] == entry["submission_hash"]


def test_experience_ledger_torn_tail_recovery(tmp_path):
    store, stem = _experience_store(tmp_path)
    store.record_use(stem, use_decision="applied", note="one", episode_ref="episode:s1:1:dd")
    ledger = tmp_path / "experiences" / "usage.jsonl"
    with ledger.open("ab") as fh:
        fh.write(b'{"schema": "experience-use/v1", "exp')

    report = store.recover_usage_ledger()

    assert report["quarantined_count"] == 1
    assert (tmp_path / "experiences" / "usage.jsonl.corrupt").exists()


# ── 双进程并发写（四类隔离夹具场景 4）──

_CHILD = """
import json
import sys

from llm_loop.methods.store import MethodStore

root = sys.argv[1]
ref = sys.argv[2]
mode = sys.argv[3]
store = MethodStore(root)
if mode == "same":
    entry = store.record_use(
        ref, episode_ref="episode:conc:1:aa", decision="applied",
        note="concurrent same content", work_unit_id="TASK-CONC", benefit="helped",
    )
else:
    entry = store.record_use(
        ref, episode_ref="episode:conc:1:aa", decision="applied",
        note="concurrent variant " + sys.argv[4], work_unit_id="TASK-CONC",
        benefit=sys.argv[4],
    )
print(json.dumps({"submission_hash": entry["submission_hash"], "ledger_seq": entry["ledger_seq"], "revision": entry["revision"]}))
"""


def _spawn(root: Path, ref: str, mode: str, variant: str) -> subprocess.Popen:
    repo_root = Path(__file__).resolve().parents[2]
    # 子进程必须导入与父进程完全相同的被测代码：优先把父进程实际解析到的
    # llm_loop 包目录放进 PYTHONPATH（否则系统解释器可能命中 site-packages
    # 里的陈旧安装副本），再补仓库根（tests.* 导入需要）。
    import llm_loop

    src_dir = Path(llm_loop.__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src_dir), str(repo_root), env.get("PYTHONPATH", "")]
    )
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(root), ref, mode, variant],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(repo_root),
    )


def test_two_processes_same_submission_converge_to_one_line(tmp_path):
    store, ref = _method_store(tmp_path)
    root = tmp_path / "methods"
    procs = [_spawn(root, ref, "same", "x"), _spawn(root, ref, "same", "x")]
    outs = [p.communicate() for p in procs]
    for p in procs:
        assert p.returncode == 0, outs
    receipts = [json.loads(out) for out, _err in outs]
    assert receipts[0]["submission_hash"] == receipts[1]["submission_hash"]
    assert receipts[0]["ledger_seq"] == receipts[1]["ledger_seq"]  # 同一回执（同一水位）
    ledger = (root / "usage.jsonl").read_text(encoding="utf-8")
    assert ledger.count("\n") == 1  # flock 内先扫后写收敛为一条


def test_two_processes_distinct_submissions_both_appended_as_revisions(tmp_path):
    store, ref = _method_store(tmp_path)
    root = tmp_path / "methods"
    procs = [
        _spawn(root, ref, "diff", "helped"),
        _spawn(root, ref, "diff", "hindered"),
    ]
    outs = [p.communicate() for p in procs]
    for p in procs:
        assert p.returncode == 0, outs
    receipts = [json.loads(out) for out, _err in outs]
    assert len({r["submission_hash"] for r in receipts}) == 2
    assert sorted(r["ledger_seq"] for r in receipts) == [1, 2]
    ledger = (root / "usage.jsonl").read_text(encoding="utf-8")
    assert ledger.count("\n") == 2
    summary = store.usage_net(ref)
    assert summary is not None and summary["applied"] == 1  # 同 slot 只计链头


# ── schema 分层与 legacy 桶 ──


def test_v2_entry_carries_schema_task_and_version_binding(tmp_path):
    store, ref = _method_store(tmp_path)
    record = store.get(ref)
    entry = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied",
        work_unit_id="TASK-A", benefit="helped", evidence_level="observation_linked",
        suggestion="补充适用前提", run_id="run-9",
    )
    assert entry["schema"] == "method-use/v2"
    assert entry["work_unit_id"] == "TASK-A"
    assert entry["work_unit_binding"] == "explicit"
    assert entry["run_id"] == "run-9"
    assert entry["read_version"] == record.content_hash  # 版本绑定
    assert entry["slot_id"] and entry["submission_hash"]
    assert entry["benefit"] == "helped"
    assert entry["evidence_level"] == "observation_linked"
    assert entry["task_benefit"] == "not_evaluated"  # 独立评估语义保留


def test_experience_v2_binding_defaults_to_episode_fallback(tmp_path):
    store, stem = _experience_store(tmp_path)
    entry = store.record_use(
        stem, use_decision="applied", note="n", episode_ref="episode:s1:7:ee",
    )
    assert entry["schema"] == "experience-use/v2"
    assert entry["work_unit_binding"] == "episode_fallback"
    assert entry["work_unit_id"] == "episode:s1:7:ee"
    assert entry["slot_id"]
    assert entry["benefit"] == "unknown"  # 历史缺项标 unknown，不当失败或零收益


def test_legacy_bucket_participates_only_with_complete_fields(tmp_path):
    """legacy（无 schema/slot）条目：ref+决定计入总次数；需要自评/版本的分母不计入."""
    store, ref = _method_store(tmp_path)
    ledger = tmp_path / "methods" / "usage.jsonl"
    legacy = {
        "ts": "2026-01-01T00:00:00",
        "method_ref": ref,
        "method_status": "candidate",
        "episode_ref": "episode:old:1:00",
        "decision": "applied",
        "note": "",
        "model": "",
        "evidence_refs": [],
        "application_proven": True,
        "task_benefit": "not_evaluated",
        "promotion": "not_evaluated",
    }
    ledger.write_text(json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8")

    summary = store.usage_net(ref)

    assert summary is not None
    assert summary["applied"] == 1  # 字段齐全（ref+决定）→ 参与总次数
    assert summary["legacy_entries"] == 1
    assert summary["benefit_counts"]["helped"] == 0  # 缺自评 → 不进分层分母


def test_invalid_benefit_and_evidence_level_are_rejected(tmp_path):
    store, ref = _method_store(tmp_path)
    with pytest.raises(ValueError):
        store.record_use(
            ref, episode_ref="episode:s1:1:aa", decision="applied", benefit="great",
        )
    with pytest.raises(ValueError):
        store.record_use(
            ref, episode_ref="episode:s1:1:aa", decision="applied",
            evidence_level="guessed",
        )


def test_method_unresolved_attribution_requires_explicit_allow_and_stays_slotless(tmp_path):
    """P1-1（store 契约面）：空 episode 默认仍拒绝；显式 allow_unresolved 才走 slot=''.

    use_ledger.resolve_submission 定义的归属 unresolved 退化路径：binding=
    unresolved、slot_id=''；两条不同内容的无归属提交互不并链（同内容才按
    submission_hash 尽力去重）。
    """
    store, ref = _method_store(tmp_path)
    # 既有契约不变：未显式允许时，缺 episode 溯源直接拒绝
    with pytest.raises(ValueError, match="provenance"):
        store.record_use(ref, episode_ref="", decision="applied", note="no episode")

    first = store.record_use(
        ref, episode_ref="", decision="applied", note="无归属甲",
        allow_unresolved=True, benefit="helped",
    )
    second = store.record_use(
        ref, episode_ref="", decision="applied", note="无归属乙",
        allow_unresolved=True, benefit="hindered",
    )
    for entry in (first, second):
        assert entry["work_unit_binding"] == "unresolved"
        assert entry["work_unit_id"] == ""
        assert entry["episode_ref"] == ""
        assert entry["slot_id"] == ""
        assert entry["revision"] == 1
        assert entry["supersedes"] == ""
    assert second.get("idempotent") is not True
    heads = dedupe_slot_heads(store.usage_entries(ref))
    assert len(heads) == 2  # 两条无归属评价不并链、链头统计不塌缩


# ── P1 修复（Rule28 reviewer 20261015-ac085ab1）：slot='' 退化去重的对象边界 ──


def test_unresolved_default_submissions_across_method_refs_do_not_fold(tmp_path):
    """跨 ref 未归属碰撞：同账本两个不同 method 的全默认提交各自落账、互不折叠.

    submission_hash 材料不含对象 ref，同默认内容哈希恒等——退化去重必须由
    扫描侧限定 (kind, ref)，否则第二个对象吃第一个对象的回执且自身永不落账
    （回执 ref 串对象，违反「旧反馈不串任务」「每项可查持久 receipt」）。
    """
    store = MethodStore(tmp_path / "methods")
    m1 = store.save_candidate(
        name="collision method one", description="contract fixture", body=_CONTRACT_BODY
    )
    m2 = store.save_candidate(
        name="collision method two", description="contract fixture", body=_CONTRACT_BODY
    )
    first = store.record_use(
        m1.method_ref, episode_ref="", decision="applied", allow_unresolved=True,
    )
    second = store.record_use(
        m2.method_ref, episode_ref="", decision="applied", allow_unresolved=True,
    )

    assert first.get("idempotent") is not True
    assert second.get("idempotent") is not True  # 不同对象同默认内容：不是重试
    assert first["submission_hash"] == second["submission_hash"]  # 哈希恒等成立
    assert first["method_ref"] == m1.method_ref  # 每条回执 ref 正确
    assert second["method_ref"] == m2.method_ref
    assert second["ledger_seq"] != first["ledger_seq"]  # 各自落账（两条账本行）
    ledger = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert ledger.count("\n") == 2
    for ref in (m1.method_ref, m2.method_ref):  # 净分按对象独立
        summary = store.usage_net(ref)
        assert summary is not None and summary["applied"] == 1

    retry = store.record_use(
        m1.method_ref, episode_ref="", decision="applied", allow_unresolved=True,
    )
    assert retry.get("idempotent") is True  # 同对象同内容重试仍折叠为既有回执
    assert retry["method_ref"] == m1.method_ref
    assert retry["submission_hash"] == first["submission_hash"]
    again = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert again.count("\n") == 2  # 重试不重复追加


def test_unresolved_default_submission_for_experience_object_lands(tmp_path):
    """experience 侧同类碰撞：两个不同经验对象的全默认未归属提交互不折叠."""
    store = ExperienceStore(tmp_path / "experiences")
    stem_a = store.save(_make_doc()).removesuffix(".md")
    stem_b = store.save(_make_doc(title="契约夹具经验乙")).removesuffix(".md")
    first = store.record_use(stem_a, use_decision="applied")
    second = store.record_use(stem_b, use_decision="applied")

    assert second.get("idempotent") is not True
    assert first["submission_hash"] == second["submission_hash"]
    assert first["experience_ref"] == f"experience:{stem_a}"  # 回执 ref 正确
    assert second["experience_ref"] == f"experience:{stem_b}"
    lines = (tmp_path / "experiences" / "usage.jsonl").read_text(encoding="utf-8")
    assert lines.count("\n") == 2  # 各自落账


def test_unresolved_submission_does_not_fold_into_slotted_attribution(tmp_path):
    """未归属提交不得折叠进带 slot 的已归属行（同对象、同默认内容）."""
    store, ref = _method_store(tmp_path)
    slotted = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied", work_unit_id="TASK-A",
    )
    unresolved = store.record_use(
        ref, episode_ref="", decision="applied", allow_unresolved=True,
    )

    assert unresolved.get("idempotent") is not True  # 不吃已归属行的回执
    assert unresolved["submission_hash"] == slotted["submission_hash"]  # 同默认内容
    assert unresolved["slot_id"] == ""  # 保持未归属语义
    assert unresolved["method_ref"] == ref
    assert unresolved["ledger_seq"] != slotted["ledger_seq"]
    ledger = (tmp_path / "methods" / "usage.jsonl").read_text(encoding="utf-8")
    assert ledger.count("\n") == 2  # 未归属提交自身落账


# ── P-SET-4（GOAL-20261016-cf563b27 批次一）：统计读取面与去重扫描同一完整性口径 ──


def test_usage_entries_share_integrity_view_with_dedup_scan(tmp_path):
    """P-SET-4：中段篡改行不再"计入统计却对去重不可见"——两视图行数一致.

    审查反例：``usage_entries``（统计/回执视图）只做 JSON 解析不校验行级
    integrity，而 ``record_use`` 去重扫描走 ``read_ledger_entries``（凭据
    校验）。中段篡改行（JSON 仍合法、integrity 失配）计入统计却对去重
    不可见。修复后统计侧同样校验，两视图对同一账本文件给出同一行集。
    """
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="one")
    store.record_use(ref, episode_ref="episode:s1:2:bb", decision="adapted", note="two")

    # 中段篡改第一行 note：保持 JSON 合法（区别于解析失败），仅 integrity 失配
    ledger = tmp_path / "methods" / "usage.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    mutated = json.loads(lines[0])
    mutated["note"] = "rewritten after write"
    lines[0] = json.dumps(mutated, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 统计视图：篡改行不进入（legacy 无凭据行不受影响——本夹具两行均带凭据）
    visible = store.usage_entries(ref)
    assert [e["note"] for e in visible] == ["two"]
    # 与去重扫描同一行集：两视图对同一文件行数一致，不再分叉
    assert len(visible) == len(read_ledger_entries(ledger))
    # 去重视角行为断言：篡改行不可见 → 同内容重报不被它吞掉（真实追加）
    again = store.record_use(
        ref, episode_ref="episode:s1:1:aa", decision="applied", note="one",
    )
    assert again.get("idempotent") is not True
    assert len(store.usage_entries(ref)) == len(read_ledger_entries(ledger)) == 2


def test_usage_entries_legacy_rows_without_credential_stay_readable(tmp_path):
    """P-SET-4 边界：legacy 无凭据行（无 integrity 字段）仍可读，口径不变."""
    store, ref = _method_store(tmp_path)
    store.record_use(ref, episode_ref="episode:s1:1:aa", decision="applied", note="v2 row")
    ledger = tmp_path / "methods" / "usage.jsonl"
    legacy = {
        "ts": "2026-10-16T00:00:00",
        "method_ref": ref,
        "decision": "applied",
        "note": "legacy row without credential",
        "submission_hash": "legacy-hash",
    }
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(legacy, ensure_ascii=False, sort_keys=True) + "\n")

    notes = [e["note"] for e in store.usage_entries(ref)]
    assert notes == ["v2 row", "legacy row without credential"]  # legacy 行可读
