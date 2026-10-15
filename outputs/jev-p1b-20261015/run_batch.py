#!/usr/bin/env python3
"""P1b 批次 runner（包外实现，DESIGN §11.1/§11.1.1 v0.8.1 外发冻结 + §11.2 v0.8.2 P1b-L 本地 judge 冻结）。

- 复用包内 wire/policy/shadow，零逻辑复制；jev 包内零网络 import tripwire 维持。
- 真实传输 RealJevTransport 定义于本文件（包外）：urllib、单次尝试、不跟随重定向、
  deadline=2s；缺凭据即拒绝发送（不得以其它 provider 凭据替代）。
- §11.6 v0.8.7 P1b-OR 分支：--transport real_or —— endpoint=OpenRouter System One、
  凭据=根 .env 的 OPENROUTER_API_KEY（定向单键读取，不经 shell history/export）、
  请求模型 id=typesafe/jev-1.13、发题前 1 次 GET /api/v1/key 预检
  （单列 or_preflight 事件记账，不占 ≤2 请求批预算）。
- Mock 模式仅验证链路（投影/守卫/预算/事件/对账），其答案为脚本中立值，
  不构成对 Jev 质量的任何主张。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import socket
import sys
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from llm_loop.knowledge.jev.policy import OutboundPolicy, PolicyGuard  # noqa: E402
from llm_loop.knowledge.jev.shadow import JevShadowRunner  # noqa: E402
from llm_loop.knowledge.jev.transport import (  # noqa: E402
    JevTransportError,
    MockJevTransport,
)
from llm_loop.knowledge.jev.wire import (  # noqa: E402
    CONTRACT_ENDPOINT,
    CONTRACT_MODEL_ALIAS,
    QuestionSpec,
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from local_semif_transport import LOCAL_JUDGE_ID, SemIfLocalTransport  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "jev" / "blind_eval_v1"
LABELS_FILE = REPO / "outputs" / "jev-blind-eval-20261015" / "blind_eval_result_v2_ds_v4_flash.json"
MANIFEST_SHA = "4372a1885adb83cbbfd9156c2b3da5680b9b631d2ee8aed49d050181a2364636"
COST_CAP_RMB = 10.0
SESSION_ID = "jev-p1b-batch-20261015"
RUN_REF = "p1b-20261015-batch01"

# §11.6 v0.8.7：P1b-OR OpenRouter 分支冻结值（四字段 + 预检；其余全部沿用 §11.1/§11.1.1）
OR_ENDPOINT = "https://openrouter.ai/api/v1/systemone"
OR_MODEL_ALIAS = "typesafe/jev-1.13"
OR_PREFLIGHT_URL = "https://openrouter.ai/api/v1/key"


def sha256_file(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")


def read_env_key(name: str) -> str:
    """从根 .env 定向读取单个键（§11.6：不经 shell history/export；值不打印）。"""
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return ""


def or_preflight(api_key: str) -> dict:
    """§11.6 预检：1 次 GET /api/v1/key，仅验 key；0 题、0 模型调用、无任务数据。"""
    req = urllib.request.Request(
        OR_PREFLIGHT_URL, method="GET", headers={"Authorization": f"Bearer {api_key}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body_head = resp.read(4096)
        return {"url": OR_PREFLIGHT_URL, "status": resp.status, "body_bytes_head": len(body_head)}


class RealJevTransport:
    """包外真实传输：一次 send = 一次物理尝试，无重试、不跟随重定向。"""

    def __init__(self, api_key: str, endpoint: str = CONTRACT_ENDPOINT) -> None:
        if not api_key or not api_key.strip():
            raise RuntimeError("TYPESAFE_API_KEY missing/empty")
        self._key = api_key.strip()
        self.endpoint = endpoint
        self.attempts: list[dict] = []

    def send(self, request: dict, *, deadline_s: float) -> dict:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise urllib.error.HTTPError(newurl, code, "redirect blocked", headers, fp)

        opener = urllib.request.build_opener(_NoRedirect)
        started = time.monotonic()
        self.attempts.append({"started_at": started, "deadline_s": float(deadline_s)})
        try:
            with opener.open(req, timeout=float(deadline_s)) as resp:
                raw_bytes = resp.read()
                status = resp.status
        except TimeoutError as exc:
            raise JevTransportError("timeout", f"socket timeout after {deadline_s}s: {exc}") from exc
        except urllib.error.HTTPError as exc:
            raise JevTransportError("transport", f"http_error {exc.code}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise JevTransportError("timeout", f"url timeout: {exc.reason}") from exc
            raise JevTransportError("transport", f"url_error: {exc.reason}") from exc
        if status != 200:
            raise JevTransportError("transport", f"unexpected status {status}")
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise JevTransportError("transport", f"non-json body: {type(exc).__name__}") from exc
        if not isinstance(parsed, dict):
            raise JevTransportError("transport", "response body is not an object")
        return parsed


def verify_fixture_freeze() -> dict:
    manifest = FIXTURE_ROOT / "manifest.json"
    got = sha256_file(manifest)
    if got != MANIFEST_SHA:
        raise SystemExit(f"FROZEN SET VIOLATION: manifest sha256 {got} != {MANIFEST_SHA}")
    m = json.loads(manifest.read_text())
    checked = 0
    for group in ("cases", "wire_examples"):
        for item in m.get(group, []):
            p = FIXTURE_ROOT / item["file"]
            actual = "sha256:" + sha256_file(p)
            if actual != item["sha256"]:
                raise SystemExit(f"FROZEN SET VIOLATION: {item['file']} sha mismatch")
            checked += 1
    lab = m.get("labels", {})
    if "sha256:" + sha256_file(FIXTURE_ROOT / lab["file"]) != lab["sha256"]:
        raise SystemExit("FROZEN SET VIOLATION: labels sha mismatch")
    return {"manifest_sha256": got, "files_verified": checked + 1, "frozen_at": m["frozen_at"]}


def case_snapshot(case: dict) -> dict:
    return {k: v for k, v in case["task_snapshot"].items() if k in set(case["allowlist"])}


def build_batches() -> list[dict]:
    cases = {
        cid: json.loads((FIXTURE_ROOT / f"cases/case-{cid}.json").read_text())
        for cid in ("001", "002", "003", "004", "006")
    }
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text())
    case_shas = {
        c["file"]: c["sha256"].split(":", 1)[1]
        for c in manifest["cases"]
    }

    def q(cid: str, qname: dict) -> QuestionSpec:
        name, spec = qname
        return QuestionSpec(
            name=f"{name}__case-{cid}",
            type=spec["type"],
            instructions=(
                f"[case-{cid} 专属判定] 本题唯一依据是 state.task_snapshot 中 case-{cid} 的内容；"
                f"state 中其它 case 条目与本题无关。" + spec["instructions"]
            ),
            criteria=dict(spec["criteria"]),
        )

    b1_cases = ("001", "002", "003", "006")
    b1_hash = "sha256:" + hashlib.sha256(
        "".join(case_shas[f"cases/case-{c}.json"] for c in b1_cases).encode()
    ).hexdigest()
    batch1 = {
        "batch_id": "batch-1",
        "subject_ref": "batch:blind_eval_v1/cases-001-002-003-006",
        "subject_hash": b1_hash,
        "task_snapshot": {f"case-{c}": case_snapshot(cases[c]) for c in b1_cases},
        "allowlist": {f"case-{c}" for c in b1_cases},
        "questions": {
            f"premise_linux__case-{c}": q(c, ("premise_linux", cases[c]["questions"]["premise_linux"]))
            for c in b1_cases
        },
        "question_map": {f"premise_linux__case-{c}": (f"case-{c}", "premise_linux") for c in b1_cases},
    }
    c4 = cases["004"]
    batch2 = {
        "batch_id": "batch-2",
        "subject_ref": c4["subject_ref"],
        "subject_hash": c4["subject_hash"],
        "task_snapshot": case_snapshot(c4),
        "allowlist": set(c4["allowlist"]),
        "questions": {
            f"{qn}__case-004": q("004", (qn, spec))
            for qn, spec in c4["questions"].items()
        },
        "question_map": {f"{qn}__case-004": ("case-004", qn) for qn in c4["questions"]},
    }
    return [batch1, batch2]


def scan_cost_fields(node, found=None, path="") -> list[dict]:
    if found is None:
        found = []
    import re
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and re.search(
                r"cost|amount|charge|price|fee", str(k), re.I
            ):
                found.append({"path": f"{path}.{k}", "value": float(v)})
            else:
                scan_cost_fields(v, found, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            scan_cost_fields(v, found, f"{path}[{i}]")
    return found


def model_drift(resolved: str | None, alias: str = CONTRACT_MODEL_ALIAS) -> bool:
    if not resolved:
        return True
    return not (resolved == alias or resolved.startswith(alias + "-"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=("mock", "real", "local", "real_or"), required=True)
    args = ap.parse_args()

    t0 = now_iso()
    freeze = verify_fixture_freeze()
    blind = json.loads(LABELS_FILE.read_text())

    events_path = OUT_DIR / "jev_shadow_events.jsonl"

    def event_append(session_id: str, kind: str, payload: dict) -> bool:
        line = json.dumps(
            {"ts": now_iso(), "session_id": session_id, "kind": kind, "payload": payload},
            ensure_ascii=False,
        )
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True

    if args.transport == "mock":
        # 中立脚本答案：仅验证链路，不构成质量主张
        def _mock_answer(name: str) -> dict:
            # EVO-20261015（R1 根因修复）：官方逐题值字段名 choice
            return {
                "choice": "unknown",
                "probabilities": {"yes": 0.1, "no": 0.1, "unknown": 0.8},
                "confidence": 0.8,
            }

        transport = MockJevTransport(
            script=[
                {
                    "model": "jev-1.13.0-mock",
                    "answers": {f"premise_linux__case-{c}": _mock_answer(c) for c in ("001", "002", "003", "006")},
                    "usage": {"input_tokens": 700, "output_tokens": 60, "total_tokens": 760},
                },
                {
                    "model": "jev-1.13.0-mock",
                    "answers": {
                        "premise_bare_metal__case-004": _mock_answer("004"),
                        "premise_systemd__case-004": _mock_answer("004"),
                    },
                    "usage": {"input_tokens": 220, "output_tokens": 40, "total_tokens": 260},
                },
            ]
        )
        mode = "dry_run_mock"
    elif args.transport == "local":
        # P1b-L（§11.2）：本地开源 judge（SemIf+Qwen3.5-4B@851bf6e+MLX），零外发、零凭据
        transport = SemIfLocalTransport(OUT_DIR / "semif_audit")
        mode = "local_semif"
    elif args.transport == "real_or":
        # §11.6 v0.8.7：OpenRouter System One 分支（四字段 + 预检；其余沿用 §11.1/§11.1.1）
        api_key = read_env_key("OPENROUTER_API_KEY")
        if not api_key:
            print(
                "BLOCKED: 根 .env 未找到 OPENROUTER_API_KEY（§11.6 凭据冻结名）；"
                "不得以其它 provider 凭据替代。",
                file=sys.stderr,
            )
            return 2
        try:
            pf = or_preflight(api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"BLOCKED: or_preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        event_append(SESSION_ID, "or_preflight", pf)
        transport = RealJevTransport(api_key, endpoint=OR_ENDPOINT)
        mode = "real_or_systemone"
    else:
        api_key = os.environ.get("TYPESAFE_API_KEY", "")
        if not api_key.strip():
            print(
                "BLOCKED: TYPESAFE_API_KEY 未设置。2026-10-15 09:20 已复核 .env 无任何 "
                "TypeSafe 凭据；不得以其它 provider 凭据替代（跨方泄露）。请提供该账户的 API key "
                "（例如写入 .env 的 TYPESAFE_API_KEY=... 后重跑本命令）。",
                file=sys.stderr,
            )
            return 2
        transport = RealJevTransport(api_key)
        mode = "real"

    policy = OutboundPolicy(
        max_requests=2,
        max_input_tokens=2000,
        max_output_tokens=2000,
        max_questions_per_batch=5,
        request_deadline_s=180.0 if args.transport == "local" else 2.0,  # 本地首跑 shader 编译+prefill，§11.2 冻结
        retry_enabled=False,
        cost_cap=COST_CAP_RMB,
        cost_source="user_authorization_20261015_usage_audit_no_price_list",
        provisional=False,
    )
    guard = PolicyGuard(policy=policy)
    judge_alias = (
        LOCAL_JUDGE_ID
        if args.transport == "local"
        else OR_MODEL_ALIAS
        if args.transport == "real_or"
        else CONTRACT_MODEL_ALIAS
    )
    run_ref = (
        "p1b-or-20261015-batch01-r4" if args.transport == "real_or" else RUN_REF
    )
    runner = JevShadowRunner(
        transport=transport,
        guard=guard,
        event_append=event_append,
        session_id=SESSION_ID,
        run_ref=run_ref,
        model_alias=judge_alias,
    )

    batches = build_batches()
    batch_results = []
    aborted_reason = None
    cumulative_cost_fields: list[dict] = []

    for b in batches:
        if aborted_reason:
            batch_results.append({"batch_id": b["batch_id"], "status": "aborted", "reason": aborted_reason})
            continue
        outcome = runner.judge_premises(
            subject_ref=b["subject_ref"],
            subject_hash=b["subject_hash"],
            task_snapshot=b["task_snapshot"],
            allowlist=b["allowlist"],
            questions=b["questions"],
        )
        entry = {
            "batch_id": b["batch_id"],
            "status": outcome.status,
            "attempt_id": outcome.attempt_id,
            "transport_status": outcome.transport_status,
            "resolved_model": outcome.resolved_model,
            "usage": outcome.usage,
            "summary": outcome.summary,
            "request_hash": outcome.request_hash,
            "questions_map_hash": outcome.questions_map_hash,
            "event_persisted": outcome.event_persisted,
            "error_detail": outcome.error_detail,
            # R1 教训（DESIGN v0.8.8）：逐题无效时保留官方 answers 原文摘录
            "raw_answers_excerpt": outcome.raw_answers_excerpt or None,
        }
        if outcome.status == "recorded":
            costs = scan_cost_fields(outcome.questions) + scan_cost_fields(outcome.usage)
            entry["cost_fields_found"] = costs
            cumulative_cost_fields.extend(costs)
            total = sum(c["value"] for c in cumulative_cost_fields)
            if cumulative_cost_fields and total > COST_CAP_RMB:
                aborted_reason = f"budget_breach: reported cost {total} > cap {COST_CAP_RMB}"
            elif model_drift(outcome.resolved_model, judge_alias):
                aborted_reason = f"version_drift: resolved_model={outcome.resolved_model!r} != {judge_alias}"
        batch_results.append(entry)

    # 对账（仅 mode=real 且题状态 valid 才入准确率样本；mock 只算不主张）
    eligible = 6
    per_q = []
    match_n = valid_n = 0
    label_map = {e["q"]: e for e in blind["comparison"]["per_question"]}
    for b in batches:
        for qname, (cid, qn) in b["question_map"].items():
            key = f"{cid}/{qn}"
            lab = label_map[key]
            per_q.append({
                "q": key, "batch_id": b["batch_id"], "question_instance_id": qname,
                "blind_actual": lab["judge"], "blind_final_state": lab["final_state"],
                "jev_answer": None, "jev_question_status": "not_attempted",
            })

    # 从事件文件恢复逐题答案（单一事实源：knowledge.jev_shadow 事件）
    events = [json.loads(ln) for ln in events_path.read_text().splitlines() if ln.strip()]
    batch_events = {e["payload"].get("attempt_id"): e["payload"] for e in events if e["kind"] == "knowledge.jev_shadow"}
    for item in per_q:
        br = next(r for r in batch_results if r["batch_id"] == item["batch_id"])
        pe = batch_events.get(br.get("attempt_id"))
        if pe and pe.get("status") == "recorded":
            qf = pe["questions"].get(item["question_instance_id"])
            if qf:
                item["jev_answer"] = qf.get("answer")
                item["jev_question_status"] = qf.get("status")
                item["jev_confidence"] = qf.get("confidence")
                item["jev_p_selected"] = qf.get("p_selected")
                if qf.get("status") == "valid":
                    valid_n += 1
                    if str(qf.get("answer")) == str(item["blind_actual"]):
                        match_n += 1
                        item["match"] = True
                    else:
                        item["match"] = False

    transport_completed = sum(1 for r in batch_results if r.get("transport_status") == "ok")
    requests_used = guard.used()["requests_used"]
    report = {
        "schema_version": "jev-p1b-report/v1",
        "mode": mode,
        "run_ref": run_ref,
        "session_id": SESSION_ID,
        "started_at": t0,
        "finished_at": now_iso(),
        "fixture_freeze": freeze,
        "label_source": {
            "file": str(LABELS_FILE.relative_to(REPO)),
            "judge_model": blind["judge"]["model"],
            "manifest_sha256": blind["manifest_sha256"],
        },
        "policy": policy.to_facts(),
        "endpoint": None
        if mode == "dry_run_mock"
        else (
            "local:vendor/SemIf mlx shared"
            if mode == "local_semif"
            else OR_ENDPOINT
            if mode == "real_or_systemone"
            else CONTRACT_ENDPOINT
        ),
        "batches": batch_results,
        "aborted_reason": aborted_reason,
        "guard_used": guard.used(),
        "reconciliation": {
            "eligible": eligible,
            "attempted_batches": requests_used,
            "transport_completed_batches": transport_completed,
            "schema_valid_questions": valid_n,
            "independently_labelled": 6,
            "label_agreement_with_author": blind["comparison"]["summary"]["value_agreement"],
            "matches": match_n,
            "per_question": per_q,
            "claim_limit": "6 题仅证明 wire/守卫/对账链路可运行，不构成 §9.2 校准资格；"
            + (
                "mock 模式答案为脚本中立值，不代表 Jev 质量" if mode == "dry_run_mock"
                else (
                    "local_semif：SemIf+Qwen3.5-4B 复现 Jev 接口模式而非 Jev 本体，结果仅为本地 judge 单批次事实，不构成 Jev 校准资格"
                    if mode == "local_semif"
                    else "real_or_systemone：OpenRouter System One 面（§11.6）单批次事实，不构成校准/排序资格"
                    if mode == "real_or_systemone"
                    else "real 模式结果为单批次事实"
                )
            ),
        },
        "cost": {
            "cap_rmb": COST_CAP_RMB,
            "fields_found": cumulative_cost_fields,
            "enforcement": "token 硬闸 + usage 审计 + 响应携带费用字段且累计>cap 即中止",
        },
        "honesty": "真实发送与否以本目录 events/receipt 为准；观察结果不改闸（§11.1/§11.1.1）",
    }
    report_path = OUT_DIR / (
        "p1b_or_report_r4.json"
        if mode == "real_or_systemone"
        else "p1b_report_dry_run_mock.json"
        if mode == "dry_run_mock"
        else "p1b_report.json"
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "mode": mode, "batches": [(r["batch_id"], r["status"]) for r in batch_results],
        "aborted_reason": aborted_reason, "requests_used": guard.used(),
        "valid_q": valid_n, "match": match_n,
        "report": str(report_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
