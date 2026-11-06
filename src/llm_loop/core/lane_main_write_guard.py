"""main 直写机械门（2026-11-06，并行处理完善建议② / RULE-AI-34 补充）。

背景（两次真实事故）：多会话并行时，某会话在他人 lane 走合并闸期间直写
``main``——①git commit 落在共享 worktree 的他人分支上（被重建成剔除）；
②cherry-pick 直写 main（再次与他人合并闸竞争）。纪律：可合并改动先
``lane_open`` 登记，在分支提交；``main`` 直写仅在无他人 active lane 时允许。

判定（返回 None=放行；返回 dict=拒绝事实）：
- 命令是 ``git commit`` / ``git push``（heredoc 数据区正文不计入判定）；
- 目标分支 main/master：commit → workdir 当前分支；push → 显式 refspec 或当前分支；
- 账本存在他人 active lane（status ∈ {open, active, verifying, merging} 且
  ``owner_session_id`` != 当前会话）。

无法判定（无 audit_dir / 无法解析分支 / 读账本失败）→ 放行，不把"无法判定"
伪造成"无冲突"（fail-open，与命令闸的错误处理一致：拒绝必须基于已证事实）。
"""
from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

_MAIN_BRANCHES = frozenset({"main", "master"})
_LANE_ACTIVE = frozenset({"open", "active", "verifying", "merging"})
# git 全局选项里带值的前缀（守卫目标只关心 commit/push，正常用法不出现这些；
# 出现时视为无法解析 → 放行）
_GIT_VALUE_OPTS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace"})


def _git_verbs(command: str) -> list[tuple[str, list[str]]]:
    """抽出 ``(verb, refspec_tokens)``；仅识别 commit/push，其余忽略。"""
    try:
        from llm_loop.core.command_scope_guard import _strip_heredocs

        stripped, _reason = _strip_heredocs(command)
        text = stripped
    except Exception:  # noqa: BLE001 — 剥离失败不阻断（按原串保守解析）
        text = command
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        return []
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(tokens):
        if tokens[i] != "git":
            i += 1
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-"):
            j += 2 if tokens[j] in _GIT_VALUE_OPTS else 1
        if j < len(tokens) and tokens[j] in ("commit", "push"):
            out.append((tokens[j], tokens[j + 1 :]))
            i = j + 1
        else:
            i = j
    return out


def _current_branch(workdir: str | None) -> str | None:
    """workdir 的当前分支；detached/失败返回 None。"""
    cwd = workdir or "."
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def _push_targets(verb_refspecs: list[str]) -> list[str]:
    """push 参数中的分支目标（首 token 是 remote，其余为 refspec）。

    - ``--all``/``--mirror`` → ``["__ALL__"]``（推全部分支，含 main）；
    - 仅 remote 无 refspec（``git push origin``）→ ``[]``（由调用方按当前分支判定）；
    - 其余：remote 之后每个 token 取 ``src:dst`` 的 dst。
    """
    flags = [t for t in verb_refspecs if t.startswith("-")]
    if any(f in ("--all", "--mirror") for f in flags):
        return ["__ALL__"]
    nonflags = [t for t in verb_refspecs if not t.startswith("-")]
    if len(nonflags) <= 1:
        return []
    targets: list[str] = []
    for tok in nonflags[1:]:
        name = tok.split(":")[-1] if ":" in tok else tok
        if name:
            targets.append(name)
    return targets


def _main_target(verb: str, refspecs: list[str], workdir: str | None) -> bool:
    """命令是否触碰 main/master。"""
    if verb == "commit":
        branch = _current_branch(workdir)
        return branch in _MAIN_BRANCHES if branch else False
    targets = _push_targets(refspecs)
    if targets == ["__ALL__"]:
        return True  # --all/--mirror 必然推 main
    if not targets:  # git push 无 refspec → 当前分支
        branch = _current_branch(workdir)
        return branch in _MAIN_BRANCHES if branch else False
    return any(t in _MAIN_BRANCHES for t in targets)


def _active_other_lanes(audit_dir: str, session_id: str) -> list[dict[str, Any]]:
    """账本中他人 active lane 行；读失败返回空（调用方不据此拒绝）。"""
    path = Path(audit_dir) / "lanes.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    lanes: dict[str, dict[str, Any]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("lane_id"):
            lanes[str(row["lane_id"])] = row  # 末条快照
    out: list[dict[str, Any]] = []
    for row in lanes.values():
        if str(row.get("status") or "") not in _LANE_ACTIVE:
            continue
        owner = str(row.get("owner_session_id") or "")
        if owner and owner == session_id:
            continue
        out.append(row)
    return out


def check_git_main_write(
    command: str,
    *,
    audit_dir: str,
    session_id: str,
    workdir: str | None,
) -> dict[str, Any] | None:
    """判定命令是否构成「他人 active lane 存在时直写 main」。

    返回 None=放行；返回 dict={reason, detail, lanes} 表示拒绝事实。
    """
    if not command or not audit_dir:
        return None
    verbs = _git_verbs(command)
    if not verbs:
        return None
    hits = [(verb, refs) for verb, refs in verbs if _main_target(verb, refs, workdir)]
    if not hits:
        return None
    others = _active_other_lanes(audit_dir, session_id)
    if not others:
        return None
    lanes_note = "、".join(
        f"{row.get('lane_id')}({row.get('branch')} goal={row.get('goal_id')})"
        for row in others[:3]
    )
    verb_note = "、".join(verb for verb, _refs in hits)
    return {
        "reason": "lane_main_write_conflict",
        "detail": (
            f"命令含 git {verb_note} 目标 main，且存在他人 active lane：{lanes_note}。"
            "并行会话期间 main 直写会与他人合并闸竞争（2026-11-05/06 两次事故）。"
            "建议: 先 lane_open 登记并在分支提交，或等对方 lane 合并后再动 main；"
            "合并建议可用 lane_merge_advice。"
        ),
        "lanes": others[:5],
    }
