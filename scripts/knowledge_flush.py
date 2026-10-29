#!/usr/bin/env python3
"""knowledge_flush.py — 知识资产（方法卡/经验卡）批量入库。

为什么需要它
------------
运行时把方法卡写到 ``data/methods/<id>/METHOD.md``、经验卡写到 ``experiences/*.md``。
仓库政策（.gitignore）明确这两处是**入库保全**的学习资产：``data/*`` 忽略，但
``!data/methods/`` 与经验卡例外。可现实是卡片由运行过程持续产生，没人会为每张卡
单独提交 → 越积越多、越容易被忘，最后只存在于本机工作区：别的 clone / 安装 / 发布
拿不到，学习效果等于没有。

本工具只解决这一件事：把「尚未入库的知识资产」一次收进**一个本地提交**。

刻意不做的事（边界）
--------------------
- 不 push：推送走 RULE-AI-28 独立审查闸；知识卡随同一次发布 push 一起上去。
- 不逐卡提交：一批一个提交，避免提交风暴。
- 不碰其它路径：用 ``git commit -- <pathspec>`` 只提交知识资产，工作区里其它已暂存
  改动不会被卷进来。
- 不 amend / 不 rebase / 不改写历史。
- 合并/变基进行中直接拒绝（0 副作用），避免把别人的冲突解算混进知识提交。

用法
----
::

    python scripts/knowledge_flush.py                # 入库（默认）
    python scripts/knowledge_flush.py --dry-run      # 只报告会提交什么
    python scripts/knowledge_flush.py --check        # 发布前置闸：有待入库资产 → 退出码 3
    python scripts/knowledge_flush.py --json         # 机器可读回执

退出码：0 = 已入库或无事可做；2 = 环境/校验错误（未提交）；3 = ``--check`` 有待入库资产。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

MIN_CARD_BYTES = 40
KNOWLEDGE_PATHS = ("data/methods", "experiences")
IN_PROGRESS_MARKERS = ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")


class FlushError(RuntimeError):
    """环境/校验问题：调用方应为未提交状态。"""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:  # 统一折算成 FlushError，调用方按未提交处理
        raise FlushError(f"git {' '.join(args)} 超时（120s）") from exc
    if check and proc.returncode != 0:
        raise FlushError(f"git {' '.join(args)} 失败: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def repo_root(start: Path) -> Path:
    proc = _git(start, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise FlushError(f"不在 git 仓库内: {start}")
    return Path(proc.stdout.strip())


def _pending(root: Path) -> list[tuple[str, str]]:
    """返回 [(status, relpath)]；status 为 porcelain 的 XY 两字符。"""
    proc = _git(
        root,
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=all",
        "--",
        *KNOWLEDGE_PATHS,
    )
    out = proc.stdout
    rows: list[tuple[str, str]] = []
    i = 0
    while i < len(out):
        status = out[i : i + 2]
        i += 3  # XY + 空格
        end = out.find("\0", i)
        if end < 0:
            end = len(out)
        path = out[i:end]
        i = end + 1
        if status[:1] in {"R", "C"}:
            # 重命名/复制条目后跟原路径，跳过
            nxt = out.find("\0", i)
            i = len(out) if nxt < 0 else nxt + 1
        rows.append((status, path))
    return rows


def collect(root: Path) -> dict[str, object]:
    rows = _pending(root)
    cards: list[str] = []
    experiences: list[str] = []
    other: list[str] = []
    incomplete: list[str] = []
    too_small: list[str] = []
    for status, path in rows:
        if path.startswith("data/methods/") and path.endswith("/METHOD.md"):
            card_dir = (root / path).parent
            card_path = root / path
            is_new = "?" in status or status[:1] in {"A"}
            if is_new and card_path.is_file() and card_path.stat().st_size < MIN_CARD_BYTES:
                too_small.append(path)
                continue
            if not card_path.is_file() and "D" not in status:
                # 只有真的缺卡（半成品目录）才跳过；删除（工作区 " D" 或暂存 "D "）要照常入库
                incomplete.append(str(card_dir.relative_to(root)))
                continue
            cards.append(path)
        elif path.startswith("experiences/") and path.endswith(".md"):
            experiences.append(path)
        elif path.startswith("experiences/") and path.count("/") == 1 and "." not in Path(path).name:
            # 目录级未跟踪条目（unlikely with -uall，兜底）
            other.append(path)
        else:
            other.append(path)
    # 缺 METHOD.md 的半成品目录整体跳过，避免把写了一半的残片入库；
    # 卡片目录里的附属文件（qualification.json 等）留在 other 里，随卡一起提交
    half_baked = set(incomplete)
    kept: list[str] = []
    for path in other:
        parent = Path(path).parent
        if str(parent) in half_baked:
            continue
        if path.startswith("data/methods/") and not (root / parent / "METHOD.md").is_file():
            incomplete.append(str(parent))
            continue
        kept.append(path)
    other = kept
    return {
        "cards": sorted(cards),
        "experiences": sorted(experiences),
        "other": sorted(other),
        "incomplete": sorted(set(incomplete)),
        "too_small": sorted(too_small),
    }


def _in_progress(root: Path) -> str | None:
    git_dir = Path(_git(root, "rev-parse", "--git-dir").stdout.strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    for marker in IN_PROGRESS_MARKERS:
        if (git_dir / marker).exists():
            return marker
    return None


def flush(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    marker = _in_progress(root)
    if marker:
        raise FlushError(f"仓库处于进行中的操作（{marker}），先收尾再入库")
    found = collect(root)
    cards = found["cards"]
    experiences = found["experiences"]
    other = found["other"]
    pending_paths = [*cards, *experiences, *other]
    receipt: dict[str, object] = {
        "repo": str(root),
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip(),
        "cards": len(cards),
        "experiences": len(experiences),
        "other": len(other),
        "pending": len(pending_paths),
        "incomplete": found["incomplete"],
        "too_small": found["too_small"],
        "committed": False,
        "commit": None,
    }
    if not pending_paths:
        return receipt
    if dry_run:
        receipt["paths"] = pending_paths
        return receipt

    # pathspec 必须真实存在：两个知识目录在部分检出里可能缺一个，git add 会整体报错
    specs = [p for p in KNOWLEDGE_PATHS if (root / p).exists()]
    if not specs:
        return receipt
    _git(root, "add", "-A", "--", *specs)
    staged = _git(root, "diff", "--cached", "--name-only", "-z", "--", *specs).stdout
    if not staged.strip("\0"):
        return receipt
    message = (
        f"knowledge: 入库 {len(cards)} 张方法卡与 {len(experiences)} 条经验卡"
        f"（knowledge_flush {date.today().isoformat()}）"
    )
    # 逐个文件提交：--only 语义，工作区其它已暂存改动不会被卷进来
    commit = _git(root, "commit", "-m", message, "--", *pending_paths, check=False)
    if commit.returncode != 0:
        raise FlushError(f"git commit 失败: {commit.stderr.strip() or commit.stdout.strip()}")
    receipt["committed"] = True
    receipt["commit"] = _git(root, "rev-parse", "HEAD").stdout.strip()
    receipt["message"] = message
    return receipt


def _print_human(receipt: dict[str, object], *, quiet: bool) -> None:
    cards = receipt["cards"]
    experiences = receipt["experiences"]
    if receipt["committed"]:
        print(
            f"✅ knowledge_flush：已入库 {cards} 张方法卡 / {experiences} 条经验卡"
            f" → {str(receipt['commit'])[:12]}（{receipt['branch']}，未推送）"
        )
    elif receipt["pending"]:
        print(
            f"• knowledge_flush：待入库 {cards} 张方法卡 / {experiences} 条经验卡"
            f"（{receipt['pending']} 个文件，未提交）"
        )
    elif not quiet:
        print("✅ knowledge_flush：无待入库知识资产")
    for path in receipt.get("incomplete", []) or []:  # type: ignore[union-attr]
        print(f"  ⚠️ 缺少 METHOD.md，已跳过: {path}", file=sys.stderr)
    for path in receipt.get("too_small", []) or []:  # type: ignore[union-attr]
        print(f"  ⚠️ 卡片过小（<{MIN_CARD_BYTES}B），已跳过: {path}", file=sys.stderr)
    if receipt.get("paths"):
        for path in receipt["paths"]:  # type: ignore[index]
            print(f"  + {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="知识资产（方法卡/经验卡）批量入库")
    parser.add_argument("--root", default=".", help="仓库内任意路径（默认当前目录）")
    parser.add_argument("--dry-run", action="store_true", help="只报告，不提交")
    parser.add_argument("--check", action="store_true", help="有待入库资产时退出码 3（发布前置闸）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 回执")
    parser.add_argument("--quiet", action="store_true", help="无事可做时不输出")
    args = parser.parse_args(argv)

    try:
        root = repo_root(Path(args.root).resolve())
        receipt = flush(root, dry_run=args.dry_run or args.check)
    except FlushError as exc:
        print(f"❌ knowledge_flush: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(receipt, ensure_ascii=False))
    else:
        _print_human(receipt, quiet=args.quiet)
    if args.check and receipt["pending"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
