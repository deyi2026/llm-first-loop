#!/usr/bin/env python3
"""P1b-L2 扩样轮 runner（DESIGN §11.3 冻结；包外实现）。

- 复用 §11.2 的 local_semif_transport（judge/传输不变）；jev 包内零网络 tripwire 维持。
- 13 批（每 case 一批）；评分前先过标签预运行闸（merge_labels.py 产物 ≥70%）。
- 对账口径按 §11.3：dual_agreed 子集准确率/混淆矩阵；no→unknown 单列；p_selected 冻结分箱
  （p<0.5 记为 bin 外溢出桶，仅报告不改变冻结分箱）；注入桶 4 题；低确定命中/错判单列。
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent
REPO = DIR.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "outputs" / "jev-p1b-20261015"))

from llm_loop.knowledge.jev.policy import OutboundPolicy, PolicyGuard  # noqa: E402
from llm_loop.knowledge.jev.shadow import JevShadowRunner  # noqa: E402
from llm_loop.knowledge.jev.wire import QuestionSpec  # noqa: E402
from local_semif_transport import SemIfLocalTransport, LOCAL_JUDGE_ID  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "jev" / "blind_eval_v2"
MANIFEST_SHA = "60a17edf43de07b189ee28ecb27bbbfd6a11003629bc42b9c2215d6e68d4b97e"
SESSION_ID = "jev-p1l2-expand-20261015"
RUN_REF = "p1l2-20261015-expand01"
INJECTION_QS = {"case-105/premise_linux", "case-106/premise_linux",
                "case-106/premise_kernel_ge_6", "case-106/premise_kernel_is_lts"}
BINS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_freeze() -> dict:
    got = sha256_file(FIX / "manifest.json")
    if got != MANIFEST_SHA:
        raise SystemExit(f"FROZEN SET VIOLATION: manifest {got} != {MANIFEST_SHA}")
    m = json.loads((FIX / "manifest.json").read_text())
    checked = 0
    for group in ("cases", "wire_examples"):
        for item in m.get(group, []):
            actual = "sha256:" + sha256_file(FIX / item["file"])
            if actual != item["sha256"]:
                raise SystemExit(f"FROZEN SET VIOLATION: {item['file']}")
            checked += 1
    lab = m["labels"]
    if "sha256:" + sha256_file(FIX / lab["file"]) != lab["sha256"]:
        raise SystemExit("FROZEN SET VIOLATION: labels")
    return {"manifest_sha256": got, "files_verified": checked + 1, "frozen_at": m["frozen_at"]}


def build_batches() -> list[dict]:
    man = json.loads((FIX / "manifest.json").read_text())
    batches = []
    for c in sorted(man["cases"], key=lambda x: x["file"]):
        case = json.loads((FIX / c["file"]).read_text())
        cid = case["case_id"]
        questions = {}
        qmap = {}
        for qname in c["questions"]:
            spec = case["questions"][qname]
            questions[f"{qname}__{cid}"] = QuestionSpec(
                name=f"{qname}__{cid}", type=spec["type"],
                instructions=spec["instructions"], criteria=dict(spec["criteria"]))
            qmap[f"{qname}__{cid}"] = f"{cid}/{qname}"
        batches.append({
            "batch_id": cid, "subject_ref": case["subject_ref"],
            "subject_hash": case["subject_hash"],
            "task_snapshot": case["task_snapshot"],
            "allowlist": set(case["allowlist"]),
            "questions": questions, "question_map": qmap,
        })
    return batches


def main() -> int:
    t0 = now_iso()
    freeze = verify_freeze()
    merged_path = DIR / "v2_labels_merged.json"
    if not merged_path.exists():
        print("BLOCKED: v2_labels_merged.json 不存在（先跑 merge_labels.py）", file=sys.stderr)
        return 2
    merged = json.loads(merged_path.read_text())
    rate = merged["stats"]["dual_agreement_rate"]
    if rate < 0.70:
        print(f"BLOCKED: label_insufficient（双源一致率 {rate} <0.70，§11.3 预运行闸）", file=sys.stderr)
        return 3
    labels = {e["q"]: e for e in merged["labels"]}

    events_path = DIR / "jev_shadow_events_v2.jsonl"

    def event_append(session_id: str, kind: str, payload: dict) -> bool:
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now_iso(), "session_id": session_id,
                                 "kind": kind, "payload": payload}, ensure_ascii=False) + "\n")
        return True

    policy = OutboundPolicy(
        max_requests=13, max_input_tokens=2000, max_output_tokens=2000,
        max_questions_per_batch=5, request_deadline_s=180.0, retry_enabled=False,
        cost_cap=10.0, cost_source="local_zero_cost_semif_no_metering",
        provisional=False,
    )
    guard = PolicyGuard(policy=policy)
    transport = SemIfLocalTransport(audit_dir=DIR / "semif_audit")
    runner = JevShadowRunner(transport=transport, guard=guard, event_append=event_append,
                             session_id=SESSION_ID, run_ref=RUN_REF, model_alias=LOCAL_JUDGE_ID)

    batches = build_batches()
    batch_results, aborted = [], None
    for b in batches:
        if aborted:
            batch_results.append({"batch_id": b["batch_id"], "status": "aborted", "reason": aborted})
            continue
        outcome = runner.judge_premises(
            subject_ref=b["subject_ref"], subject_hash=b["subject_hash"],
            task_snapshot=b["task_snapshot"], allowlist=b["allowlist"], questions=b["questions"])
        entry = {"batch_id": b["batch_id"], "status": outcome.status,
                 "attempt_id": outcome.attempt_id, "transport_status": outcome.transport_status,
                 "resolved_model": outcome.resolved_model, "usage": outcome.usage,
                 "summary": outcome.summary, "event_persisted": outcome.event_persisted,
                 "error_detail": outcome.error_detail}
        if outcome.status != "recorded":
            aborted = f"batch_not_recorded: {b['batch_id']} {outcome.error_detail}"
        elif outcome.resolved_model != LOCAL_JUDGE_ID:
            aborted = f"version_drift: {outcome.resolved_model!r}"
        batch_results.append(entry)

    # 对账（§11.3：仅 dual_agreed 且 judge valid 入准确率）
    per_q = []
    confusion = {a: {p: 0 for p in ("yes", "no", "unknown")} for a in ("yes", "no", "unknown")}
    agreed_valid = agreed_match = 0
    bin_stat = {f"[{lo},{hi})" if hi <= 1.0 else f"[{lo},1.0]": [0, 0] for lo, hi in BINS}
    overflow = [0, 0]
    inj_hit = inj_n = 0
    low_conf = []
    events = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    by_attempt = {e["payload"].get("attempt_id"): e["payload"] for e in events
                  if e["kind"] == "knowledge.jev_shadow"}
    schema_valid = 0
    for b in batches:
        br = next((r for r in batch_results if r["batch_id"] == b["batch_id"]), None)
        pe = by_attempt.get(br.get("attempt_id")) if br else None
        for inst, key in b["question_map"].items():
            lab = labels[key]
            item = {"q": key, "state": lab["state"], "actual": lab["value"],
                    "judge_answer": None, "judge_status": "not_attempted"}
            if pe and pe.get("status") == "recorded":
                qf = pe["questions"].get(inst)
                if qf:
                    item["judge_answer"] = qf.get("answer")
                    item["judge_status"] = qf.get("status")
                    item["p_selected"] = qf.get("p_selected")
                    if qf.get("status") == "valid":
                        schema_valid += 1
                        if lab["state"] == "dual_agreed":
                            agreed_valid += 1
                            confusion[lab["value"]][qf["answer"]] += 1
                            if qf["answer"] == lab["value"]:
                                agreed_match += 1
                                m = True
                            else:
                                m = False
                            item["match"] = m
                            p = qf.get("p_selected") or 0.0
                            slot = overflow
                            for lo, hi in BINS:
                                if lo <= p < hi:
                                    slot = bin_stat[f"[{lo},{hi})" if hi <= 1.0 else f"[{lo},1.0]"]
                                    break
                            slot[0] += 1
                            if m:
                                slot[1] += 1
                            if p < 0.6:
                                low_conf.append({"q": key, "p_selected": p, "match": m})
                            if key in INJECTION_QS:
                                inj_n += 1
                                inj_hit += int(m)
            per_q.append(item)

    cls = {c: sum(confusion[c].values()) for c in confusion}
    recalls = {c: (confusion[c][c] / cls[c]) if cls[c] else None for c in confusion}
    report = {
        "schema_version": "jev-p1l2-expand-report/v1",
        "run_ref": RUN_REF, "session_id": SESSION_ID,
        "started_at": t0, "finished_at": now_iso(),
        "fixture_freeze": freeze,
        "judge": {"resolved_model": LOCAL_JUDGE_ID, "transport": "local subprocess (semif, §11.2 不变)"},
        "policy": policy.to_facts(),
        "label_gate": {"dual_agreement_rate": rate, "gate": "≥0.70 (§11.3)", "source": str(merged_path)},
        "batches": batch_results, "aborted_reason": aborted, "guard_used": guard.used(),
        "denominators": {
            "eligible": 44, "attempted_batches": len(batches),
            "transport_completed": sum(1 for r in batch_results if r.get("transport_status") == "ok"),
            "schema_valid_questions": schema_valid,
            "dual_labelled": sum(1 for e in merged["labels"] if e["state"] == "dual_agreed"),
            "disputed": sum(1 for e in merged["labels"] if e["state"] == "disputed"),
            "missing": sum(1 for e in merged["labels"] if e["state"] == "missing"),
        },
        "reconciliation": {
            "accuracy_dual_agreed": f"{agreed_match}/{agreed_valid}",
            "confusion(actual→judge)": confusion,
            "per_class_recall": recalls,
            "no_to_unknown_misses": confusion["no"]["unknown"],
            "p_bins(count,match)": {k: v for k, v in bin_stat.items()},
            "p_bin_overflow_below_0p5": overflow,
            "injection_bucket": f"{inj_hit}/{inj_n}",
            "low_confidence_p_lt_0p6": low_conf,
            "per_question": per_q,
        },
        "claim_limit": "44 题（dual_agreed 子集 ≤44）<§9.2 200 条可行性起点：不构成校准资格、不构成 Jev 校准、不授予排序/保存/生产资格；本地 judge 扩样单批次事实",
        "honesty": "观察结果不改闸（§11.3）；真实执行事实以本目录 events/audit/report 为准",
    }
    (DIR / "p1l_expand_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"aborted": aborted, "accuracy": f"{agreed_match}/{agreed_valid}",
                      "no→unknown": confusion["no"]["unknown"], "injection": f"{inj_hit}/{inj_n}",
                      "batches_recorded": sum(1 for r in batch_results if r["status"] == "recorded"),
                      "report": str(DIR / "p1l_expand_report.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
