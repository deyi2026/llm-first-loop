#!/usr/bin/env python3
"""知识闭环独立打分器 CLI（StartLux-Decision 27B，/v1/systemone）。

对经验/方法知识卡在某任务中的实际帮助程度做独立打分（区别于模型自评）：
数据源 = use ledger 的使用回执；每条使用回执一次独立打分（一对多，不合并）。

用法:
  python scripts/knowledge_score.py --all-pending [--limit N]
  python scripts/knowledge_score.py --ref experience:<id或slug> [--ref method:<id> ...]
  加 --dry-run 只打印 state 与请求体，不调服务、不写任何文件

采纳规则: p_evidence_sufficient ≥ 0.5 且 confidence ≥ 0.5 才写回 sidecar
（data/knowledge_scores/cards/<slug>.json，卡片文件零触碰——version 调查结论），
否则只落 ledger（data/knowledge_scores/ledger.jsonl）。

逐卡隔离：单卡失败（服务错误/解析失败/卡片加载失败）写 error 行后继续；
全部失败退出码非零；部分成功退出码 0 并在 stderr 汇总失败。

写回重试（P2-5）: 「打分成功、仅写回 sidecar 失败」的 slot（ledger 按
最新行判定）重跑时只从已落账结果补写回 sidecar，不重打分（零 27B 调用）；
补写回成功后落一行 writeback_replayed 补账行，后续重跑零重复。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, "src")

from llm_loop.knowledge_score.card_writeback import write_sidecard
from llm_loop.knowledge_score.client import (
    DEFAULT_SCORER_URL,
    ScorerError,
    ScoreResult,
    build_request_body,
    score_state,
)
from llm_loop.knowledge_score.ledger import (
    WRITEBACK_FAILED_PREFIX,
    KnowledgeScoreLedger,
    build_error_entry,
    build_success_entry,
)
from llm_loop.knowledge_score.pending import PendingUse, scan_pending
from llm_loop.knowledge_score.state_builder import (
    CardInfo,
    build_state,
    find_card,
    use_decision_reported,
)

ADOPT_P_EVIDENCE = 0.5
ADOPT_CONFIDENCE = 0.5


def _targets_for_ref(root: Path, ref: str) -> list[PendingUse]:
    """单卡目标：该卡全部使用回执（同 slot 修订链取链尾），旧→新。"""
    card = find_card(root, ref)
    wanted = card.ref
    items = [
        item
        for item in scan_pending(root, limit=None)
        if item.ref == wanted
    ]
    return items


def _format_summary(ref, slot, result, adopted) -> str:
    top_prob = result.probabilities.get(str(result.top_level), 0.0)
    return (
        f"[scored] {ref} slot={slot[:16]}… top={result.top_level}"
        f"({result.top_label},{top_prob:.3f}) expected={result.expected:.2f}/4 "
        f"confidence={result.confidence:.3f} p_evidence={result.p_evidence_sufficient:.3f} "
        f"adopted={'yes' if adopted else 'no'}"
    )


def _result_from_ledger_row(row: dict) -> ScoreResult:
    """从 ledger 已落账行重建打分结果（P2-5 补写回专用，绝不重打分）。"""
    return ScoreResult(
        probabilities={
            str(k): float(v) for k, v in (row.get("probabilities") or {}).items()
        },
        expected=float(row.get("expected") or 0.0),
        top_level=int(row.get("top_level") or 0),
        top_label=str(row.get("top_label") or ""),
        confidence=float(row.get("confidence") or 0.0),
        p_evidence_sufficient=float(row.get("p_evidence_sufficient") or 0.0),
        model=str(row.get("scorer_model") or ""),
    )


def _replay_writeback(
    ledger: KnowledgeScoreLedger,
    cards_dir: Path,
    *,
    item: PendingUse,
    card: CardInfo,
    row: dict,
    failures: list[str],
) -> bool:
    """P2-5(a) 重试语义：打分成功仅写回失败 → 重跑只补写回，不重打分。

    - 零打分服务调用：以 ledger 已落账行重建结果写 sidecar；
      card_version_at_scoring 取落账行 version（打分时点），不用当前卡版本。
    - 成功：追加一行「写回补账」行（复用原结果、writeback_replayed=true、
      adopted=true、writeback_target 补全），使 slot 进入已覆盖集合——
      后续重跑零重复、零额外调用。
    - 再次失败：不追加新行（既有失败行已如实记录状态，避免行堆积），
      仅计入 failures 等待下次重跑继续按本路径重试。
    """
    result = _result_from_ledger_row(row)
    scored_version = str(row.get("version") or card.version)
    try:
        write_sidecard(
            cards_dir,
            card=replace(card, version=scored_version),
            result=result,
            slot_id=str(item.use_entry.get("slot_id") or ""),
            use_ts=str(item.use_entry.get("ts") or ""),
        )
    except (OSError, RuntimeError) as exc:
        message = f"writeback replay failed: {exc}"
        failures.append(f"{item.ref}: {message}")
        print(f"[failed] {item.ref} writeback-replay: {exc}", file=sys.stderr)
        return False
    entry = build_success_entry(
        scorer_model=result.model,
        kind=item.kind,
        ref=item.ref,
        version=scored_version,
        slot_id=str(item.use_entry.get("slot_id") or ""),
        slot_key=item.slot_key,
        decision_reported=use_decision_reported(item.use_entry),
        top_level=result.top_level,
        top_label=result.top_label,
        expected=result.expected,
        confidence=result.confidence,
        p_evidence_sufficient=result.p_evidence_sufficient,
        probabilities=result.probabilities,
        adopted=True,
        writeback_target=f"data/knowledge_scores/cards/{card.slug}.json",
    )
    entry["writeback_replayed"] = True
    ledger.append(entry)
    print(
        f"[writeback-repaired] {item.ref} slot={item.slot_key[:16]}… "
        f"top={result.top_level}（ledger 已落账结果补写回，未重打分）"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="知识卡独立打分器（StartLux-Decision /v1/systemone）"
    )
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="REF",
        help="单卡打分: experience:<id或slug> 或 method:<id>，可多次",
    )
    parser.add_argument(
        "--all-pending",
        action="store_true",
        help="扫描 use ledger，找有使用回执但尚无打分记录(slot 级去重)的卡",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="--all-pending 最多处理的待打分条数（默认 10）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印构造出的 state 与请求体；不调服务、不写任何文件",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="仓库根目录（默认当前目录）",
    )
    parser.add_argument(
        "--endpoint",
        default=None,  # P1: None 时走 resolve_endpoint 的 env > 默认链，不得架空 env
        help=(
            "打分服务端点；显式指定优先，未指定时依次取环境变量"
            f" LFL_INDEPENDENT_SCORER_URL 与默认 {DEFAULT_SCORER_URL}"
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not args.ref and not args.all_pending:
        parser.error("需要 --ref <ref> 或 --all-pending 之一")

    targets: list[PendingUse] = []
    resolve_failures: list[str] = []
    if args.ref:
        for ref in args.ref:
            try:
                matched = _targets_for_ref(root, ref)
            except (FileNotFoundError, ValueError) as exc:
                resolve_failures.append(f"{ref}: {exc}")
                continue
            if not matched:
                resolve_failures.append(
                    f"{ref}: use ledger 中无该卡的使用回执（无可打分项）"
                )
                continue
            targets.extend(matched)
    if args.all_pending:
        pending = scan_pending(root, limit=args.limit)
        known = {(t.kind, t.ref, t.slot_key) for t in targets}
        targets.extend(
            t for t in pending if (t.kind, t.ref, t.slot_key) not in known
        )

    if not targets:
        for message in resolve_failures:
            print(f"[failed] {message}", file=sys.stderr)
        print("无待打分项", file=sys.stderr)
        return 1 if resolve_failures else 0

    ledger = None if args.dry_run else KnowledgeScoreLedger.for_root(root)
    cards_dir = None if args.dry_run else root / "data" / "knowledge_scores" / "cards"
    # P2-5(a): 「打分成功仅写回失败」的 slot（最新行判定）重跑时优先补写回
    writeback_retries: dict[str, dict] = (
        {} if ledger is None else ledger.latest_writeback_failed()
    )

    successes = 0
    failures: list[str] = []

    for item in targets:
        try:
            card: CardInfo = find_card(root, item.ref)
            state = build_state(card, item.use_entry)
        except Exception as exc:  # noqa: BLE001 — 逐卡隔离
            failures.append(f"{item.ref}({item.slot_key[:12]}…): {exc}")
            if ledger is not None:
                ledger.append(
                    build_error_entry(
                        scorer_model="",
                        kind=item.kind,
                        ref=item.ref,
                        version="",
                        slot_id=str(item.use_entry.get("slot_id") or ""),
                        slot_key=item.slot_key,
                        decision_reported=use_decision_reported(item.use_entry),
                        error=f"card/state build failed: {exc}",
                    )
                )
            print(f"[failed] {item.ref}: {exc}", file=sys.stderr)
            continue

        if args.dry_run:
            body = build_request_body(state)
            print("=" * 72)
            print(f"[dry-run] {item.ref} slot_key={item.slot_key}")
            print("-- state --")
            print(state)
            print("-- request body --")
            print(json.dumps(body, ensure_ascii=False, indent=2))
            continue

        # P2-5(a): 该 slot 已打分成功仅写回失败 → 只补写回，不重打分
        replay_row = writeback_retries.get(item.slot_key)
        if replay_row is not None:
            if _replay_writeback(
                ledger,
                cards_dir,
                item=item,
                card=card,
                row=replay_row,
                failures=failures,
            ):
                successes += 1
            continue

        try:
            result = score_state(state, endpoint=args.endpoint)
        except Exception as exc:  # noqa: BLE001 — 逐卡隔离兜底（P2-2）
            error_text = (
                str(exc) if isinstance(exc, ScorerError) else f"unexpected: {exc!r}"
            )
            failures.append(f"{item.ref}({item.slot_key[:12]}…): {error_text}")
            ledger.append(
                build_error_entry(
                    scorer_model="",
                    kind=item.kind,
                    ref=item.ref,
                    version=card.version,
                    slot_id=str(item.use_entry.get("slot_id") or ""),
                    slot_key=item.slot_key,
                    decision_reported=use_decision_reported(item.use_entry),
                    error=error_text,
                )
            )
            print(f"[failed] {item.ref}: {error_text}", file=sys.stderr)
            continue

        adopted = (
            result.p_evidence_sufficient >= ADOPT_P_EVIDENCE
            and result.confidence >= ADOPT_CONFIDENCE
        )
        writeback_target = ""
        writeback_error = ""
        if adopted:
            try:
                write_sidecard(
                    cards_dir,
                    card=card,
                    result=result,
                    slot_id=str(item.use_entry.get("slot_id") or ""),
                    use_ts=str(item.use_entry.get("ts") or ""),
                )
                writeback_target = f"data/knowledge_scores/cards/{card.slug}.json"
            except (OSError, RuntimeError) as exc:
                adopted = False
                # P2-5: 前缀与 ledger.WRITEBACK_FAILED_PREFIX 对齐（重跑补写回判据）
                writeback_error = f"{WRITEBACK_FAILED_PREFIX}: {exc}"
                failures.append(f"{item.ref}: {writeback_error}")
                print(f"[failed] {item.ref} writeback: {exc}", file=sys.stderr)

        entry = build_success_entry(
            scorer_model=result.model,
            kind=item.kind,
            ref=item.ref,
            version=card.version,
            slot_id=str(item.use_entry.get("slot_id") or ""),
            slot_key=item.slot_key,
            decision_reported=use_decision_reported(item.use_entry),
            top_level=result.top_level,
            top_label=result.top_label,
            expected=result.expected,
            confidence=result.confidence,
            p_evidence_sufficient=result.p_evidence_sufficient,
            probabilities=result.probabilities,
            adopted=adopted,
            writeback_target=writeback_target,
        )
        if writeback_error:
            entry["error"] = writeback_error
        ledger.append(entry)
        successes += 1
        print(_format_summary(item.ref, item.slot_key, result, adopted))

    if args.dry_run:
        print("=" * 72)
        print(f"[dry-run] 共 {len(targets)} 项，零写入（未调服务、未写文件）")
        return 0

    if failures:
        print(f"\n[summary] 成功 {successes} / 失败 {len(failures)}:", file=sys.stderr)
        for message in failures:
            print(f"  - {message}", file=sys.stderr)
    if successes == 0 and (failures or resolve_failures):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
