#!/usr/bin/env python3
"""promo_closeout.py — D6 收口单一脚本（骨架，2026-11-12）

设计依据: docs/design/DESIGN-20261112-promo-shift-efficiency-v1.md §4 D1/D6
落地载体: docs/promotion/PLAN-20261011-new-original-topics.md「班次运行规程」配套行

把班次收口四件事合并为一次执行：
  1) verify — 机械核对：公网验收回执布尔门、冻结稿 SHA、审计回执 verdict、数值台账存在
  2) STATUS — 日级 STATUS 文件「收口记账」小节幂等补记一行
  3) 台账   — receipts/closeout-ledger.json 以 key=<date>-<shift> 去重记账
  4) goal   — 输出唯一一次 update_goal 所需的证据指引（goal 工具由模型侧执行，脚本不代调）

双回执: <out-dir>/<date>-<shift>-closeout.json（机读）+ .md（人类可读摘要）
幂等:   重复执行 → 跳过记账，回执标注 idempotent=true，不重复计「新增公开主题」
降级链: 公网回执缺失/失败时，--frozen-sha 匹配 + --degraded-note ⇒ DEGRADED（公网未核项）
fail-closed: 判据空/无回执 = FAIL = 不得停班（RULE-AI-30）
写后读校验: 回执与台账写完即复读并比对 sha256，不一致视为本次执行失败。

仅标准库；只写 <out-dir> 与 --status 指向的文件；不做 git 操作。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))

# 公网验收回执里必须全为真的布尔门（缺字段 = fail-closed 记失败）
PUBLIC_GATES = [
    "title_match",
    "key_strings_all_hit",
    "fig_captions_all_hit",
    "dims_all_match",
    "has_ai_decl",
]

VERDICT_KEYS = ["CLOSEOUT_VERDICT", "audit_verdict", "AUDIT_VERDICT", "verdict", "VERDICT"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_verdict(obj: dict) -> str | None:
    # 审查修复（R2 P2-4）：非 dict JSON（裸标量/列表）优雅降级——
    # 回 None 走 fail-closed 判 FAIL，不抛 AttributeError 裸栈。
    if not isinstance(obj, dict):
        return None
    for k in VERDICT_KEYS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
    return None


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"_load_error": f"{type(e).__name__}: {e}"}


def peek_ledger_entry(out_dir: Path, key: str) -> dict | None:
    """审查修复（R2 P1）：幂等重跑预检——key 已记账则沿用既有回执。

    重写回执会换 generated_at → 台账存储的 receipt_sha256 与盘上文件漂移
    （R2 P2-1 审计不一致）；跳过路径也必须让写后读门看到一致的语义
    （未写无需校验），否则合法重跑被误判 FAIL（R2 P1）。
    """
    ledger = out_dir / "closeout-ledger.json"
    if not ledger.exists():
        return None
    data = load_json(ledger)
    if not isinstance(data, dict):
        return None  # 损坏台账走正常路径，由 book_ledger 恢复分支接管
    entry = data.get(key)
    return entry if isinstance(entry, dict) else None


def verify(args) -> dict:
    """纯核对，不写任何文件。返回 checks 事实字典。"""
    c: dict = {"fails": [], "public_gates": {}, "degraded_used": False}

    # 1) 主稿 md 与冻结 SHA
    md = Path(args.md) if args.md else None
    md_sha = sha256_file(md) if md and md.exists() else None
    c["md_path"], c["md_sha256"] = str(md) if md else None, md_sha
    c["md_exists"] = bool(md and md.exists())
    if not c["md_exists"]:
        c["fails"].append(f"md 不存在或未提供: {md}")
    if args.frozen_sha:
        c["frozen_sha_expected"] = args.frozen_sha
        c["frozen_sha_match"] = md_sha == args.frozen_sha
        if not c["frozen_sha_match"]:
            c["fails"].append("冻结稿 SHA 与当前 md 不一致")

    # 2) 公网验收回执
    pr = Path(args.public_receipt) if args.public_receipt else None
    pub = None
    if pr and pr.exists():
        pub = load_json(pr)
        # 审查修复（R2 P2-4）：非 dict JSON（裸标量/列表）按不可解析处理——
        # fail-closed 判 FAIL，不抛 AttributeError 裸栈。
        if not isinstance(pub, dict):
            c["fails"].append(f"公网回执非 JSON 对象: {type(pub).__name__}")
        elif "_load_error" in pub:
            c["fails"].append(f"公网回执不可解析: {pub['_load_error']}")
        else:
            for g in PUBLIC_GATES:
                ok = pub.get(g) is True  # 审查修复（R1 P2-3）：只认 JSON true，拒绝 truthy 字符串
                c["public_gates"][g] = ok
                if not ok:
                    c["fails"].append(f"公网回执门未通过: {g}={pub.get(g)!r}")
            if pub.get("key_strings_missed"):
                c["fails"].append(f"关键句未命中: {pub['key_strings_missed']}")
            if int(pub.get("tag_count") or 0) < 1:
                c["fails"].append(f"tag_count={pub.get('tag_count')!r}")
    else:
        c["public_receipt_exists"] = False
        # D1 降级链：无公网回执 → 允许两级判据（冻结 SHA 一致 + 显式降级说明）
        if args.frozen_sha and c.get("frozen_sha_match") and args.degraded_note:
            c["degraded_used"] = True
        else:
            c["fails"].append(f"公网验收回执缺失且不满足降级链: {pr}")

    # 3) 审计回执（可选）
    if args.audit_receipt:
        ar = Path(args.audit_receipt)
        if not ar.exists():
            c["fails"].append(f"审计回执不存在: {ar}")
        else:
            av = extract_verdict(load_json(ar))
            c["audit_verdict"] = av
            if av != "PASS":
                c["fails"].append(f"审计回执 verdict={av!r} ≠ PASS")

    # 4) 数值台账存在性
    if args.sources_ledger:
        sl = Path(args.sources_ledger)
        c["sources_ledger_exists"] = sl.exists()
        if not sl.exists():
            c["fails"].append(f"数值台账不存在: {sl}")

    if isinstance(pub, dict) and "_load_error" not in pub:
        c["public_receipt_facts"] = {
            k: pub.get(k)
            for k in ("item_id", "url", "verified_at", "platform_time_seen", "full_text_len", "web_img_count")
        }
    if c["degraded_used"]:
        c["degraded_note"] = args.degraded_note
    return c


def status_row(args, verdict: str, receipt_name: str) -> str:
    return (
        f"| {args.date} | {args.shift} | "
        f"{verdict} | {now_cst()} | receipts/{receipt_name} |"
    )


def status_section_header() -> str:
    return (
        "\n## 收口记账（promo_closeout.py，D6）\n\n"
        "| 日期 | 班次 | 收口判定 | 记账时间 | 机读回执 |\n|---|---|---|---|---|\n"
    )


def update_status(path: Path, key: str, row: str) -> dict:
    """幂等补记 STATUS：该 key 已有行则不重复写。返回动作事实。"""
    if not path.exists():
        return {"status": "missing", "detail": f"{path} 不存在，跳过（骨架不代建总账）"}
    text = path.read_text(encoding="utf-8")
    marker = f"<!--closeout:{key}-->"
    if marker in text:
        return {"status": "already_booked", "detail": "STATUS 已有该班收口记账行"}
    header = "## 收口记账（promo_closeout.py，D6）"
    block = f"{marker}\n{row}\n"
    if header in text:
        new_text = text.rstrip("\n") + "\n" + block
    else:
        new_text = text.rstrip("\n") + status_section_header() + block
    path.write_text(new_text, encoding="utf-8")
    back = path.read_text(encoding="utf-8")
    return {
        "status": "appended" if marker in back else "write_verify_failed",
        "detail": "写后复读" + ("一致" if marker in back else "不一致"),
        "sha256_after": sha256_file(path),
    }


def book_ledger(out_dir: Path, key: str, entry: dict) -> dict:
    """幂等记账：closeout-ledger.json，key=<date>-<shift>。

    审查修复（R1 P1-1a）：合法非 dict JSON 的恢复分支此前把新记账写进
    无人引用的局部 entries——簿记静默丢失且返回 booked=True。修复后
    记账落在恢复容器的顶层（与常规平铺格式一致），跨恢复边界幂等。
    """
    ledger = out_dir / "closeout-ledger.json"
    data = load_json(ledger) if ledger.exists() else {}
    if not isinstance(data, dict):
        data = {"_corrupt_recovered_at": now_cst(), "entries": data if data else {}}
    entries = data
    if key in entries:
        return {"booked": False, "reason": "key 已存在", "existing": entries[key]}
    entries[key] = entry
    data["updated_at"] = now_cst()
    ledger.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads(ledger.read_text(encoding="utf-8"))
    ok = back.get(key, {}).get("receipt_sha256") == entry.get("receipt_sha256")
    return {
        "booked": True,
        "write_verify": "一致" if ok else "不一致",
        "ledger_path": str(ledger),
        "total_keys": len([k for k in back if not k.startswith("_") and k != "updated_at"]),
    }


def human_md(args, checks: dict, verdict: str, receipt_name: str) -> str:
    gates = "、".join(f"{k}={'真' if v else '假'}" for k, v in checks["public_gates"].items()) or "（降级链：无公网回执）"
    lines = [
        f"# 收口摘要 · {args.date} {args.shift} · {verdict}",
        "",
        f"- 生成时间：{now_cst()}（Asia/Shanghai）",
        f"- 主稿：`{checks.get('md_path')}` sha256 `{checks.get('md_sha256')}`",
        f"- 冻结 SHA 匹配：{checks.get('frozen_sha_match', '（未提供）')}",
        f"- 公网回执门：{gates}",
        f"- 公网事实：`{checks.get('public_receipt_facts')}`",
        f"- 审计 verdict：{checks.get('audit_verdict', '（未提供）')}",
        f"- 数值台账存在：{checks.get('sources_ledger_exists', '（未提供）')}",
        f"- 机读回执：receipts/{receipt_name}",
    ]
    if checks["fails"]:
        lines.append(f"- 失败项（{len(checks['fails'])}）：" + "；".join(checks["fails"]))
    if checks.get("degraded_used"):
        lines.append(f"- **公网未核项（DEGRADED）**：{checks['degraded_note']} —— 交下一班补核")
    lines += [
        "",
        "## goal 收口指引（模型侧执行，脚本不代调）",
        "",
        "判据链满足（PASS）时立即执行且仅执行一次：",
        "",
        "```",
        f"update_goal(goal_id=<本班 goal>, status=\"complete\", reason=\"{args.date} {args.shift} 收口 {verdict}\",",
        f"           evidence_refs=[\"{checks.get('md_path')}\", \"receipts/{receipt_name}\"])",
        "```",
        "",
        "DEGRADED/FAIL 时不得 complete：DEGRADED 在 STATUS 标注「公网未核项」后可停班待补核；",
        "FAIL 按fail-closed 继续任务（RULE-AI-30）。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="D6 收口单一脚本（verify+STATUS+台账+goal 指引）")
    ap.add_argument("--date", required=True, help="班次日期，如 20261112")
    ap.add_argument("--shift", required=True, help="班次代号，如 d81")
    ap.add_argument("--md", help="主稿 md 路径")
    ap.add_argument("--public-receipt", dest="public_receipt", help="公网验收回执 json")
    ap.add_argument("--audit-receipt", dest="audit_receipt", help="审计回执 json（可选）")
    ap.add_argument("--sources-ledger", dest="sources_ledger", help="数值台账 sources.md（可选）")
    ap.add_argument("--frozen-sha", dest="frozen_sha", help="冻结稿期望 sha256（两级判据/降级链用）")
    ap.add_argument("--degraded-note", dest="degraded_note", help="降级说明：公网未核项清单（降级必填）")
    ap.add_argument("--status", help="日级 STATUS md 路径（可选；幂等补记）")
    ap.add_argument("--out-dir", dest="out_dir", default="docs/promotion/receipts", help="回执/台账输出目录")
    ap.add_argument(
        "--publish-action-id", dest="publish_action_id", action="append", default=[],
        help="待闭合的发布动作 id（EVO-20261112-fd945e83 D8；可重复）。"
        "PASS/DEGRADED 收口成功后写豁免标记，发布完成提醒即闭合",
    )
    ap.add_argument("--data-dir", dest="data_dir", default="data", help="运行数据根（dismissal 标记写入 data/state/publish_closeout/）")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true", help="只核对与打印，不写任何文件")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    key = f"{args.date}-{args.shift}"
    receipt_name = f"{key}-closeout.json"

    checks = verify(args)
    verdict = "PASS"
    if checks["degraded_used"]:
        verdict = "DEGRADED"
    elif checks["fails"]:
        verdict = "FAIL"

    idempotent = False
    actions: dict = {"status": None, "ledger": None}

    if not args.dry_run and verdict in ("PASS", "DEGRADED"):
        out_dir.mkdir(parents=True, exist_ok=True)
        md_name = f"{key}-closeout.md"
        # 审查修复（R2 P1+P2-1）：幂等重跑不重写回执——key 已记账时
        # 沿用既有文件与台账（重写会换 generated_at → 存储的
        # receipt_sha256 与盘上回执漂移）；跳过路径的写后读门语义为
        # 「未写无需校验」= 一致，不再误判合法重跑 FAIL，且 --publish-action-id
        # 后续豁免标记照常写入（原 gate 早退会吞掉第 4 步）。
        existing_entry = peek_ledger_entry(out_dir, key)
        if existing_entry is not None:
            idempotent = True
            write_verify = True  # 未重写：无新写需校验（gate 消息引用）
            actions["ledger"] = {
                "booked": False,
                "reason": "key 已存在",
                "existing": existing_entry,
                "write_verify": "一致",
                "skipped": True,
            }
            actions["receipt_write_verify"] = "一致（幂等未重写）"
            actions["receipts"] = ["(幂等重跑：沿用既有回执与台账，未重写)"]
        else:
            # 1) 双回执（先写机读，再写人类可读）
            receipt = {
                "script": "scripts/promo_closeout.py",
                "design": "docs/design/DESIGN-20261112-promo-shift-efficiency-v1.md#D6",
                "key": key,
                "generated_at": now_cst(),
                "CLOSEOUT_VERDICT": verdict,
                "checks": checks,
                "goal_evidence_refs": [
                    checks.get("md_path"),
                    args.public_receipt,
                    f"{out_dir}/{receipt_name}",
                ],
            }
            jp = out_dir / receipt_name
            jp.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding="utf-8")
            j_sha = sha256_file(jp)
            (out_dir / md_name).write_text(human_md(args, checks, verdict, receipt_name), encoding="utf-8")
            # 写后读校验
            back = json.loads(jp.read_text(encoding="utf-8"))
            write_verify = back.get("CLOSEOUT_VERDICT") == verdict
            # 2) 台账幂等记账
            entry = {
                "verdict": verdict,
                "md_sha256": checks.get("md_sha256"),
                "public": checks.get("public_receipt_facts"),
                "receipt_sha256": j_sha,
                "booked_at": now_cst(),
            }
            actions["ledger"] = book_ledger(out_dir, key, entry)
            idempotent = not actions["ledger"]["booked"]
            actions["receipt_write_verify"] = "一致" if write_verify else "不一致"
            actions["receipts"] = [str(jp), str(out_dir / md_name)]
        # 3) STATUS 幂等补记（可选）
        if args.status:
            actions["status"] = update_status(
                Path(args.status), key, status_row(args, verdict, receipt_name)
            )
        # 审查修复（R1 P1-1b）：写后读不一致必须 fail-closed——簿记
        # 缺失/不一致的收口不得按成功退出（模块头声明的执行失败语义）。
        ledger_wv = actions["ledger"].get("write_verify") == "一致"
        if not (write_verify and ledger_wv):
            print(
                "  FAIL-写后读校验: receipt="
                f"{'一致' if write_verify else '不一致'} ledger_write_verify="
                f"{actions['ledger'].get('write_verify')!r}"
                "——按执行失败处理，不得 update_goal complete；请重跑核对。"
            )
            actions["write_verify_gate"] = "FAIL"
            return 1
        # 4) 发布完成提醒闭合（EVO-20261112-fd945e83 D8）：收口成功后写
        #    豁免标记，publish_closeout 提醒/投影即停。自足实现（不依赖
        #    llm_loop 可导入）：标记即 JSON 文件，schema 与
        #    write_publish_closeout_dismissal 一致；fail-open 不阻断收口。
        if args.publish_action_id:
            dismissed: list[str] = []
            marker_dir = Path(args.data_dir) / "state" / "publish_closeout"
            marker_dir.mkdir(parents=True, exist_ok=True)
            for aid in args.publish_action_id:
                aid = str(aid).strip()
                # 审查修复（R2 P2-3 同源）：与 service_control 读写侧同一严格形状
                if not re.fullmatch(r"[A-Za-z0-9._-]+", aid):
                    continue
                marker = marker_dir / f"{aid}.json"
                if marker.is_file():
                    dismissed.append(aid)
                    continue
                try:
                    marker.write_text(
                        json.dumps(
                            {
                                "schema": "publish-closeout-dismissal/v1",
                                "action_id": aid,
                                "by": "promo_closeout",
                                # 幂等分支 jp 未定义——用确定性路径（key 固定，
                                # 与首次写入时同一文件）
                                "receipt": f"{out_dir}/{receipt_name}",
                                "dismissed_at": now_cst(),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    dismissed.append(aid)
                except OSError as exc:
                    print(f"  WARN-发布提醒闭合失败: {aid}: {exc}")
            if dismissed:
                actions["publish_reminders_dismissed"] = dismissed

    print(f"[promo_closeout] key={key} verdict={verdict} dry_run={bool(args.dry_run)} idempotent={idempotent}")
    for f in checks["fails"]:
        print(f"  FAIL-项: {f}")
    if checks.get("degraded_used"):
        print(f"  公网未核项: {checks['degraded_note']}")
    if not args.dry_run:
        print(f"  actions: {json.dumps(actions, ensure_ascii=False)}")
    if verdict == "FAIL":
        print("  goal 指引: FAIL — 按 RULE-AI-30 不得收口、继续任务；本次未写任何回执/记账")
    elif args.dry_run:
        print("  goal 指引: dry-run 未写回执")
    elif verdict == "PASS":
        print(f"  goal 指引: 见 {out_dir}/{key}-closeout.md（立即一次性 update_goal complete）")
    else:
        print(f"  goal 指引: 见 {out_dir}/{key}-closeout.md（DEGRADED：STATUS 标注公网未核项后停班待补核，不得 complete）")
    return 0 if verdict in ("PASS", "DEGRADED") else 1


if __name__ == "__main__":
    sys.exit(main())
