#!/usr/bin/env python3
"""P1b-OR-V2（DESIGN §11.8，v0.9）：blind_eval_v2 44 题对真 Jev（OpenRouter System One）。

冻结于任何 v2→OpenRouter 请求之前：
- 任务集/打包/标签源/对账口径沿用 §11.3 冻结值（R3 执行形态；无 seen_bucket——Jev 对 v2 零先验暴露）
- 传输/模型/预检/牌价沿用 §11.6/§11.7 冻结值（endpoint /api/v1/systemone；model typesafe/jev-1.13；
  resolved 合法集 {别名, -20260917 快照}；预检 GET /api/v1/key 单列记账）
- 预算（§11.8）：决策 POST ≤13、题 44 封顶、est input ≤8000 / est output ≤12288、每批题 ≤5、
  重试 0、单请求 deadline 2s（不放宽）、费用硬闸累计 >$0.14（≈1 元 RMB）即停
- 中止条件沿用 §11.3 + 任一题 schema-invalid 即停轮（raw excerpt 留档）
"""
from __future__ import annotations
import argparse
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
from llm_loop.knowledge.jev.transport import MockJevTransport  # noqa: E402
from llm_loop.knowledge.jev.wire import QuestionSpec  # noqa: E402
from run_batch import (  # noqa: E402 （§11.7 终态：传输/预检/漂移/费用扫描复用，不复制）
    OR_ENDPOINT,
    OR_MODEL_ALIAS,
    RealJevTransport,
    model_drift,
    or_preflight,
    read_env_key,
    scan_cost_fields,
)

FIX = REPO / "tests" / "fixtures" / "jev" / "blind_eval_v2"
MANIFEST_SHA = "60a17edf43de07b189ee28ecb27bbbfd6a11003629bc42b9c2215d6e68d4b97e"
SESSION_ID = "jev-p1or-v2-20261015"
RUN_REF = "p1or-v2-20261015-expand01"
COST_CAP_USD = 0.14  # ≈1 元 RMB（§11.8 用户授权上限；牌价 USD 记账）
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=("mock", "real_or"), required=True)
    args = ap.parse_args()

    t0 = now_iso()
    freeze = verify_freeze()
    merged = json.loads((DIR / "v2_labels_merged.json").read_text())
    rate = merged["stats"]["dual_agreement_rate"]
    if rate < 0.70:
        print(f"BLOCKED: label_insufficient（{rate} <0.70，§11.3 预运行闸沿用）", file=sys.stderr)
        return 3
    labels = {e["q"]: e for e in merged["labels"]}

    events_path = DIR / "jev_shadow_events_v2or.jsonl"

    def event_append(session_id: str, kind: str, payload: dict) -> bool:
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now_iso(), "session_id": session_id,
                                 "kind": kind, "payload": payload}, ensure_ascii=False) + "\n")
        return True

    policy = OutboundPolicy(
        max_requests=13, max_input_tokens=8000, max_output_tokens=12288,
        max_questions_per_batch=5, request_deadline_s=2.0, retry_enabled=False,
        cost_cap=COST_CAP_USD, cost_source="openrouter_usage_cost_usd",
        provisional=False,
    )
    guard = PolicyGuard(policy=policy)

    batches = build_batches()
    if args.transport == "mock":
        script = []
        for b in batches:
            script.append({
                "model": OR_MODEL_ALIAS + "-mock",  # startswith(alias+"-") → 漂移检查通过
                "answers": {inst: {"choice": "unknown",
                                   "probabilities": {"yes": 0.1, "no": 0.1, "unknown": 0.8},
                                   "confidence": 0.8} for inst in b["questions"]},
                "usage": {"input_tokens": 260, "output_tokens": 20, "total_tokens": 280},
            })
        transport = MockJevTransport(script=script)
        mode = "dry_run_mock"
    else:
        api_key = read_env_key("OPENROUTER_API_KEY")
        if not api_key:
            print("BLOCKED: 根 .env 未找到 OPENROUTER_API_KEY（§11.6 凭据冻结名）；"
                  "不得以其它 provider 凭据替代。", file=sys.stderr)
            return 2
        try:
            pf = or_preflight(api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"BLOCKED: or_preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        event_append(SESSION_ID, "or_preflight", pf)
        transport = RealJevTransport(api_key, endpoint=OR_ENDPOINT)
        mode = "real_or_systemone"

    runner = JevShadowRunner(transport=transport, guard=guard, event_append=event_append,
                             session_id=SESSION_ID, run_ref=RUN_REF, model_alias=OR_MODEL_ALIAS)

    batch_results, aborted = [], None
    cumulative_cost: list[dict] = []
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
                 "error_detail": outcome.error_detail,
                 "raw_answers_excerpt": outcome.raw_answers_excerpt or None}
        if outcome.status != "recorded":
            aborted = f"batch_not_recorded: {b['batch_id']} {outcome.error_detail}"
        elif model_drift(outcome.resolved_model, OR_MODEL_ALIAS):
            aborted = f"version_drift: {outcome.resolved_model!r}"
        else:
            costs = scan_cost_fields(outcome.questions) + scan_cost_fields(outcome.usage)
            entry["cost_fields_found"] = costs
            cumulative_cost.extend(costs)
            total = sum(c["value"] for c in cumulative_cost)
            if cumulative_cost and total > COST_CAP_USD:
                aborted = f"budget_breach: reported cost {total} > cap {COST_CAP_USD} (USD≈1 RMB)"
            invalid = [
                inst for inst, qf in (outcome.questions or {}).items()
                if (qf.get("status") if isinstance(qf, dict) else getattr(qf, "status", None)) != "valid"
            ]
            if invalid:
                aborted = f"schema_invalid_stop: {b['batch_id']} {sorted(invalid)}"
        batch_results.append(entry)

    # 对账：主指标 = dual_agreed 43（对 Jev 无已见题，无 seen_bucket）
    per_q = []
    confusion = {a: {p: 0 for p in ("yes", "no", "unknown")} for a in ("yes", "no", "unknown")}
    agreed_valid = agreed_match = 0
    bin_stat = {f"[{lo},{hi})" if hi <= 1.0 else f"[{lo},1.0]": [0, 0] for lo, hi in BINS}
    overflow = [0, 0]
    inj_hit = inj_n = 0
    low_conf, high_conf_miss = [], []
    events = [json.loads(l) for l in events_path.read_text().splitlines() if l.strip()]
    by_attempt = {e["payload"].get("attempt_id"): e["payload"] for e in events
                  if e["kind"] == "knowledge.jev_shadow" and e["payload"].get("run_ref") == RUN_REF}
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
                    item["confidence"] = qf.get("confidence")
                    if qf.get("status") == "valid":
                        schema_valid += 1
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
                            if (qf.get("confidence") or 0) >= 0.8 and not m:
                                high_conf_miss.append({"q": key, "judge": qf["answer"],
                                                        "label": lab["value"],
                                                        "p_selected": p,
                                                        "confidence": qf.get("confidence")})
                            if key in INJECTION_QS:
                                inj_n += 1
                                inj_hit += int(m)
            per_q.append(item)

    cls = {c: sum(confusion[c].values()) for c in confusion}
    recalls = {c: (confusion[c][c] / cls[c]) if cls[c] else None for c in confusion}
    report = {
        "schema_version": "jev-p1or-v2-expand-report/v1",
        "run_ref": RUN_REF, "session_id": SESSION_ID, "mode": mode,
        "started_at": t0, "finished_at": now_iso(),
        "fixture_freeze": freeze,
        "judge": {"resolved_model_alias": OR_MODEL_ALIAS,
                  "legal_set": [OR_MODEL_ALIAS, OR_MODEL_ALIAS + "-20260917"],
                  "transport": "openrouter_systemone_urllib",
                  "preflight": "GET /api/v1/key（单列记账）"},
        "policy": policy.to_facts(),
        "label_gate": {"dual_agreement_rate": rate, "gate": "≥0.70（§11.3 沿用）"},
        "batches": batch_results, "aborted_reason": aborted, "guard_used": guard.used(),
        "cumulative_cost_fields": cumulative_cost,
        "denominators": {
            "eligible_all44": 44, "attempted_batches": len(batches),
            "transport_completed": sum(1 for r in batch_results if r.get("transport_status") == "ok"),
            "schema_valid_questions_all44": schema_valid,
            "dual_labelled_primary": agreed_valid,
            "disputed_excluded": sum(1 for e in merged["labels"] if e["state"] == "disputed"),
            "seen_bucket": 0,
        },
        "reconciliation": {
            "accuracy_dual_agreed_primary43": f"{agreed_match}/{agreed_valid}",
            "confusion(actual→judge)": confusion,
            "per_class_recall": recalls,
            "no_to_unknown_misses": confusion["no"]["unknown"],
            "p_bins(count,match)": bin_stat,
            "p_bin_overflow_below_0p5": overflow,
            "injection_bucket": f"{inj_hit}/{inj_n}",
            "low_confidence_p_lt_0p6": low_conf,
            "high_confidence_misses_ge_0p8": high_conf_miss,
            "per_question": per_q,
        },
        "claim_limit": "43 题（dual_agreed）<§9.2 200 条可行性起点：不构成校准资格、不授予排序/保存/生产资格；"
                       "真 Jev 对 v2 的单批次事实；本地 judge 56.8% 负结果不因本轮回改",
        "honesty": "观察结果不改闸（§11.8）；真实执行事实以本目录 events/report 为准",
    }
    (DIR / "p1l_or_expand_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"mode": mode, "aborted": aborted,
                      "accuracy_primary43": f"{agreed_match}/{agreed_valid}",
                      "no→unknown": confusion["no"]["unknown"],
                      "injection": f"{inj_hit}/{inj_n}",
                      "high_conf_misses": len(high_conf_miss),
                      "batches_recorded": sum(1 for r in batch_results if r.get("status") == "recorded")},
                     ensure_ascii=False))
    return 0 if not aborted else 1


if __name__ == "__main__":
    raise SystemExit(main())
