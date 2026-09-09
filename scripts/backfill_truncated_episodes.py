#!/usr/bin/env python3
"""一次性存量回填 CLI（EVO-20260902-251f059a，B2-P2 可选项落地）.

扫 data/event_logs 全部会话的非 completed run.end 边界，为历史中断 run 补写
data/episodes/{sid}.truncated.jsonl 行（幂等键=(session_id, run_end_seq)，
重复运行安全；与 B1/B2 在线路径同键互斥，不会双写）。

用法:
  python scripts/backfill_truncated_episodes.py                 # dry-run：只报告不写
  python scripts/backfill_truncated_episodes.py --apply         # 实际写入
  python scripts/backfill_truncated_episodes.py --session <sid> --apply
  python scripts/backfill_truncated_episodes.py --event-logs-dir D --episodes-dir E --apply

默认路径按"代码所在区=数据所在区"从本脚本位置推导（<repo>/data/...）。
诚实边界：B1 上线前半截产物不可恢复，回填行尾段如实为空（只恢复结构可见性）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from llm_loop.event_log.backfill_truncated import backfill_truncated_runs  # noqa: E402
from llm_loop.event_log.store import EventStore  # noqa: E402
from llm_loop.memory.episode import EpisodeStore  # noqa: E402


def enumerate_session_ids(event_logs_dir: Path) -> list[str]:
    """枚举事件日志目录中的会话 ID（平文件 <sid>.jsonl ∪ 轮转目录 <sid>/）."""
    sids: set[str] = set()
    if not event_logs_dir.exists():
        return []
    for p in event_logs_dir.iterdir():
        if p.name.endswith(".lock"):
            continue
        if p.is_file() and p.suffix == ".jsonl":
            sids.add(p.stem)
        elif p.is_dir():
            sids.add(p.name)
    return sorted(sids)


def main() -> int:
    ap = argparse.ArgumentParser(description="truncated episode 存量回填（幂等）")
    ap.add_argument("--event-logs-dir", type=Path, default=REPO_ROOT / "data" / "event_logs")
    ap.add_argument("--episodes-dir", type=Path, default=REPO_ROOT / "data" / "episodes")
    ap.add_argument("--session", action="append", default=[], help="限定会话（可多次）")
    ap.add_argument("--apply", action="store_true", help="实际写入（缺省 dry-run 只报告）")
    args = ap.parse_args()

    sids = args.session or enumerate_session_ids(args.event_logs_dir)
    event_store = EventStore(args.event_logs_dir)
    episode_store = EpisodeStore(args.episodes_dir)

    report = backfill_truncated_runs(episode_store, event_store, sids, dry_run=not args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"[{mode}] sessions={report['sessions']} runs_seen={report['runs_seen']} "
        f"written={report['written']} deduped={report['deduped']} "
        f"would_write={report['would_write']} errors={report['errors']}"
    )
    for d in report["details"]:
        print(
            f"  {d['session_id']}: seen={d['seen']} written={d['written']} deduped={d['deduped']}"
        )
    print(json.dumps({k: v for k, v in report.items() if k != "details"}, ensure_ascii=False))
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
