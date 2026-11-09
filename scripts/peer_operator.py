#!/usr/bin/env python3
"""本机 TTY 监督确认 CLI（DESIGN-20261108 §2.3）。

用法：
    python scripts/peer_operator.py list --data-dir data/peer --node-id deepin-01
    python scripts/peer_operator.py confirm <task_id> --data-dir data/peer \\
        --node-id deepin-01 --write-root /srv/work
    python scripts/peer_operator.py reject <task_id> --data-dir data/peer --node-id deepin-01

边界：confirm 必须在本机 TTY 上逐次确认；HTTP 面没有批准入口（D3）。
票据一次性、绑定参数摘要，执行前会再重判一次租约/额度/并发/路径。
"""

from __future__ import annotations

import argparse
import getpass
import inspect
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from llm_loop.peer.admission import AdmissionStore  # noqa: E402
from llm_loop.peer.artifacts import ArtifactStore  # noqa: E402
from llm_loop.peer.errors import PeerError  # noqa: E402
from llm_loop.peer.service import PeerService  # noqa: E402
from llm_loop.peer.store import PeerStore  # noqa: E402


def _default_operator() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - 取不到用户名时用固定标签，不阻塞确认
        return "operator"


def _require_supervision_runtime() -> None:
    """Refuse old wheels clearly; never turn an API mismatch into a bypass."""
    try:
        parameters = inspect.signature(PeerService).parameters
    except (TypeError, ValueError) as exc:
        raise PeerError("executor_internal_error", f"无法核验 PeerService API: {exc}") from exc
    # **kwargs accepts arbitrary values but may ignore supervision entirely.
    missing = []
    for required in ("supervision_enabled", "write_root"):
        if required not in parameters:
            missing.append(required)
    for method in ("list_supervised", "issue_supervision_ticket", "resume_supervised", "reject_supervised"):
        if not callable(getattr(PeerService, method, None)):
            missing.append(method)
    if missing:
        raise PeerError(
            "executor_internal_error",
            "peer_runtime_incompatible: 当前安装 wheel 缺少受监督 Peer API: " + ", ".join(missing)
            + "；请安装与 peer_operator.py 同版本的 LFL wheel。",
        )


def _service(args: argparse.Namespace) -> PeerService:
    _require_supervision_runtime()
    return PeerService(
        store=PeerStore(args.data_dir),
        admissions=AdmissionStore(args.data_dir),
        artifacts=ArtifactStore(args.data_dir / "artifacts"),
        node_id=args.node_id,
        write_root=args.write_root,
        supervision_enabled=True,
    )


def _print_scope(args: argparse.Namespace) -> None:
    write_root = Path(args.write_root).resolve() if args.write_root else "未配置"
    print(
        "生效配置："
        f"data_root={args.data_dir.resolve()} "
        f"node_id={args.node_id} "
        f"write_root={write_root}"
    )


def _data_dir_owned_by_me(args: argparse.Namespace) -> bool:
    """D3：data 目录属主必须等于当前 uid——否则拒绝（可能是 root 建的共享目录）。"""
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return True
    try:
        return args.data_dir.stat().st_uid == getuid()
    except OSError:
        return False


def _cmd_list(args: argparse.Namespace) -> int:
    service = _service(args)
    _print_scope(args)
    rows = service.list_supervised()
    if not rows:
        print("没有等待确认的任务。")
        return 0
    print(f"等待确认 {len(rows)} 条：")
    for row in rows:
        params = json.dumps(row["params"], ensure_ascii=False, sort_keys=True)
        if len(params) > 300:
            params = params[:300] + "…"
        print(
            f"- {row['task_id']}  kind={row['kind']}  剩余={row['remaining_s']}s  "
            f"expires={row['expires_at']}\n  params={params}"
        )
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("拒绝：confirm 必须在本机 TTY 上逐次确认（D3）。", file=sys.stderr)
        return 2
    if not _data_dir_owned_by_me(args):
        print(f"拒绝：data 目录属主不是当前用户：{args.data_dir}", file=sys.stderr)
        return 2
    service = _service(args)
    _print_scope(args)
    row = next((r for r in service.list_supervised() if r["task_id"] == args.task_id), None)
    if row is None:
        print(f"拒绝：任务 {args.task_id} 不在等待确认态。", file=sys.stderr)
        return 2
    print(f"任务：{row['task_id']}")
    print(f"kind：{row['kind']}")
    print(f"params：{json.dumps(row['params'], ensure_ascii=False, sort_keys=True)}")
    print(f"票据绑定 digest：{row['params_digest'][:16]}…")
    # D3：键入伍 task_id 后 6 位（不是 yes）——防"手滑回车"就把写放出去。
    tail = row["task_id"][-6:]
    answer = input(f"确认执行？输入任务号后 6 位（{tail}）继续：").strip()
    if answer != tail:
        print("已放弃；任务仍在等待确认。")
        return 1
    ticket = service.issue_supervision_ticket(args.task_id, issued_by=args.operator)
    print(f"票据已签发：expires={ticket.expires_at}")
    receipt = service.resume_supervised(args.task_id, decided_by=args.operator)
    print(f"结果：state={receipt['state']}  reason={receipt.get('reason_code') or '-'}")
    return 0 if receipt["state"] == "succeeded" else 3


def _cmd_reject(args: argparse.Namespace) -> int:
    service = _service(args)
    _print_scope(args)
    receipt = service.reject_supervised(args.task_id, decided_by=args.operator)
    print(f"已拒绝：state={receipt['state']}  reason={receipt.get('reason_code')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LFL peer 监督确认（本机 TTY）")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--write-root", default=None, help="与 peer_serve 一致；confirm 必填")
    parser.add_argument(
        "--supervision-ttl-s", type=int, default=None,
        help="兼容旧调用；已停用，期限一律读取任务持久化 supervision_expires_at",
    )
    parser.add_argument("--operator", default=_default_operator())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出等待确认的任务")
    confirm = sub.add_parser("confirm", help="逐次确认并执行")
    confirm.add_argument("task_id")
    reject = sub.add_parser("reject", help="拒绝并收尾为 denied")
    reject.add_argument("task_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "confirm":
            if not args.write_root:
                print("拒绝：confirm 必须显式给 --write-root（闸4 写域）。", file=sys.stderr)
                return 2
            return _cmd_confirm(args)
        return _cmd_reject(args)
    except PeerError as exc:
        print(f"失败：{exc.reason_code}（{exc.detail}）", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断；任务仍在等待确认。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
