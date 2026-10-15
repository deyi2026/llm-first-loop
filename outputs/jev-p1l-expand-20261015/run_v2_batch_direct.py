#!/usr/bin/env python3
"""P1b-L2-R2 扩样轮 runner（DESIGN §11.4 冻结：direct 模式；包外实现）。

- 传输 = local_semif_transport_direct（--mode direct，每行独立全前向，无 shared 前缀校验）。
- 主指标 = cases 102-113 的 40 题（全 dual_agreed）；case-101 四题转 seen_bucket
  （§11.3 已评分暴露，不入任何准确率；对照 §11.3 shared 轮答案做执行一致性观察）。
- 其余对账口径/预算/中止条件沿用 §11.3/§11.4 冻结值。
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
from local_semif_transport_direct import SemIfLocalDirectTransport, DIRECT_JUDGE_ID  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "jev" / "blind_eval_v2"
MANIFEST_SHA = "60a17edf43de07b189ee28ecb27bbbfd6a11003629bc42b9c2215d6e68d4b97e"
SESSION_ID = "jev-p1l2-expand-20261015"
RUN_REF = "p1l2-20261015-expand02-direct"
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
        questions, qmap = {}, {}
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
    merged = json.loads((DIR / "v2_labels_merged.json").read_text())
    rate = merged["stats"]["dual_agreement_rate"]
    if rate < 0.70:
        print(f"BLOCKED: label_insufficient（{rate} <0.70，§11.3/§11.4 预运行闸）", file=sys.stderr)
        return 3
    labels = {e["q"]: e for e in merged["labels"]}

    events_path = DIR / "jev_shadow_events_v2direct.jsonl"

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
    transport = SemIfLocalDirectTransport(audit_dir=DIR / "semif_audit_direct")
    runner = JevShadowRunner(transport=transport, guard=guard, event_append=event_append,
                             session_id=SESSION_ID, run_ref=RUN_REF, model_alias=DIRECT_JUDGE_ID)

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
        elif outcome.resolved_model != DIRECT_JUDGE_ID:
            aborted = f"version_drift: {outcome.resolved_model!r}"
        batch_results.append(entry)

    # §11.4 对账：主指标 = cases 102-113 且 dual_agreed；case-101 → seen_bucket
    shared_events = [json.loads(l) for l in (DIR / "jev_shadow_events_v2.jsonl").read_text().splitlines() if l.strip()]
    shared_q = {}
    for e in shared_events:
        if e["kind"] == "knowledge.jev_shadow" and e["payload"].get("status") == "recorded":
            for inst, qf in e["payload"].get("questions", {}).items():
                shared_q[inst] = {"answer": qf.get("answer"), "p_selected": qf.get("p_selected"),
                                  "probabilities": qf.get("probabilities")}

    per_q, seen_bucket = [], []
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
                        if key.startswith("case-101"):
                            sh = shared_q.get(inst, {})
                            seen_bucket.append({
                                "q": key, "label_state": lab["state"],
                                "dual_value": lab["value"], "author": lab["author"],
                                "direct_answer": qf.get("answer"),
                                "direct_p_selected": qf.get("p_selected"),
                                "direct_probs": qf.get("probabilities"),
                                "shared_answer": sh.get("answer"),
                                "shared_p_selected": sh.get("p_selected"),
                                "same_answer_shared_vs_direct": (
                                    sh.get("answer") == qf.get("answer")) if sh.get("answer") else None,
                            })
                            continue
                        if lab["state"] == "dual_agreed":
                            agreed_valid += 1
                            confusion[lab["value"]][qf["answer"]] += 1
                            m = qf["answer"] == lab["value"]
                            if m:
                                agreed_match += 1
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
    shared_direct_same = sum(1 for s in seen_bucket if s["same_answer_shared_vs_direct"])
    report = {
        "schema_version": "jev-p1l2-expand-direct-report/v1",
        "run_ref": RUN_REF, "session_id": SESSION_ID,
        "started_at": t0, "finished_at": now_iso(),
        "fixture_freeze": freeze,
        "judge": {"resolved_model": DIRECT_JUDGE_ID, "mode": "direct (§11.4)", "transport": "local subprocess"},
        "policy": policy.to_facts(),
        "label_gate": {"dual_agreement_rate": rate, "gate": "≥0.70 (§11.3/§11.4)"},
        "batches": batch_results, "aborted_reason": aborted, "guard_used": guard.used(),
        "denominators": {
            "eligible_primary_40": 40, "attempted_batches": len(batches),
            "transport_completed": sum(1 for r in batch_results if r.get("transport_status") == "ok"),
            "schema_valid_questions_all44": schema_valid,
            "dual_labelled_primary": agreed_valid,
            "disputed_excluded": sum(1 for e in merged["labels"] if e["state"] == "disputed"),
            "seen_bucket": len(seen_bucket),
        },
        "reconciliation": {
            "accuracy_dual_agreed_primary40": f"{agreed_match}/{agreed_valid}",
            "confusion(actual→judge)": confusion,
            "per_class_recall": recalls,
            "no_to_unknown_misses": confusion["no"]["unknown"],
            "p_bins(count,match)": bin_stat,
            "p_bin_overflow_below_0p5": overflow,
            "injection_bucket": f"{inj_hit}/{inj_n}",
            "low_confidence_p_lt_0p6": low_conf,
            "per_question": per_q,
        },
        "seen_bucket_case101": {
            "note": "§11.3 已暴露，不入准确率；shared↔direct 同题执行一致性观察",
            "answer_agreement_shared_vs_direct": f"{shared_direct_same}/{len(seen_bucket)}",
            "items": seen_bucket,
        },
        "claim_limit": "主指标 40 题（cases 102-113，全 dual_agreed；case-101 4 题 §11.3 已暴露转 seen_bucket）<§9.2 200 条可行性起点：不构成校准资格、不构成 Jev 校准、不授予排序/保存/生产资格；本地 judge 扩样单批次事实",
        "honesty": "观察结果不改闸（§11.4）；真实执行事实以本目录 events/audit/report 为准",
    }
    (DIR / "p1l_expand_report_direct.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"aborted": aborted, "accuracy_primary40": f"{agreed_match}/{agreed_valid}",
                      "no→unknown": confusion["no"]["unknown"], "injection": f"{inj_hit}/{inj_n}",
                      "seen_bucket_agree": f"{shared_direct_same}/{len(seen_bucket)}",
                      "batches_recorded": sum(1 for r in batch_results if r["status"] == "recorded"),
                      "report": str(DIR / "p1l_expand_report_direct.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
