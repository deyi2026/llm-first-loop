"""main 直写机械门（2026-11-06，并行处理完善建议② / RULE-AI-34 补充）。

背景（两次真实事故）：多会话并行时，某会话在他人 lane 走合并闸期间直写
``main``——①git commit 落在共享 worktree 的他人分支上（被重建成剔除）；
②cherry-pick 直写 main（再次与他人合并闸竞争）。纪律：可合并改动先
``lane_open`` 登记，在分支提交；``main`` 直写仅在无他人 active lane 时允许。

判定（返回 None=放行；返回 dict=拒绝事实）：
- 命令是 ``git commit`` / ``git push``（heredoc 数据区正文不计入判定）；
- 目标分支 main/master：commit → workdir 当前分支；push → 显式 refspec 或当前分支；
- 账本存在他人 live lane（status ∈ {open, active, verifying, merging} 且
  ``owner_session_id`` != 当前会话）。

2026-11-09（EVO-20261109-0e5fdde5，人工批准）扩展两条：
- **判据拆分**：commit 被全部 live lane 挡（共享 worktree 直写会落错分支）；
  push 只被 live ``verifying``/``merging`` 挡（对方即将改写 main），并额外做
  ``ls-remote`` 快进校验（明确非快进才拒绝；读不到远端按无法判定放行）。
  ``--all``/``--mirror`` 会推他人分支，保持宽判据（任意 live lane 挡）。
- **失效回收**：他人 lane 的 ``last_activity`` 超过 TTL（模块常量
  ``STALE_AFTER_S``，默认 4h，<=0 关闭）且（head 已并入 main 或其
  worktree 无未提交改动）时，不再计入 blocker；拒绝回执在 ``stale_lanes``
  标注依据与闲置时长。只读投影，不改写账本——睡眠会话的未合并分支不被作废。
- **目标仓库跟随**：``git -C <path>`` 会被解析（相对路径按命令 workdir），
  判定用的是写入实际落到的仓库分支，避免从 feature worktree 借 ``-C`` 改道。

2026-11-09 P2 残留处置（本文件）：
- **删除型 refspec**（``:main`` / ``--delete main``）：删除无法用快进证明安全，
  不再走快进校验静默放行；删除目标含 main 时按宽判据（任意 live lane 挡）。
- **非快进校验用被推 src**：``git push origin feat:main`` 用 ``feat`` 的 sha
  判定，不再误用本地 ``main``（旧实现只会误拒，但仍应修正）。
- **naive 时间戳**：时区不可判定 → 不参与闲置回收（按 live 挡），不再按本地
  时区猜（写入侧当前为 aware 本地时间；naive 只在旧数据/外部写入出现）。
- **--git-dir/--work-tree**：目标仓库不明 → 保守当 main（fail-closed），
  不再静默按 workdir 当前分支放行。

无法判定（无 audit_dir / 无法解析分支 / 读账本失败 / 无法证明闲置可回收）→
放行或按 live 计，不把"无法判定"伪造成"无冲突"（fail-open，与命令闸的错误处理
一致：拒绝必须基于已证事实）。
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

_MAIN_BRANCHES = frozenset({"main", "master"})
_LANE_ACTIVE = frozenset({"open", "active", "verifying", "merging"})
# push 只被"正在收口"的 lane 挡：对方 verifying/merging = 即将改写 main。
_PUSH_CLOSING = frozenset({"verifying", "merging"})
# 失效回收阈值：owner 超过该时长无活动，且可证明无风险（已合并/工作树干净）。
# 这里用模块常量而不是新增 env 读取：直接 os.environ 会打破 runtime env 访问的
# 单向棘轮（tests/unit/test_runtime_env_access_gate.py）；需要运行时可调时由
# config/Settings 统一引入，而不是在 core 里开新口子。
STALE_AFTER_S = 4 * 3600.0
# git 全局选项里带值、且会影响目标仓库的选项：
# - ``-C`` 会被链式解析成实际目标仓库（见 _chained_cwd）；无法解析按 main 保守处理；
# - ``--git-dir``/``--work-tree`` 会重定向仓库且不做路径语义跟随 → 标记目标仓库
#   不明，调用方按 fail-closed 保守当 main（2026-11-09 P2：由"静默放行"改为保守判定）；
# - ``-c``/``--namespace`` 与目标仓库无关，仅跳过其取值以免误判。
_GIT_VALUE_OPTS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace"})
# push 的"分离式带值"flag：其值是数据（push option / 路径），不是 remote 或 refspec。
_PUSH_FLAGS_WITH_VALUE = frozenset(
    {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
)


def _git_verbs(
    command: str, workdir: str | None = None
) -> list[tuple[str, list[str], str | None]]:
    """抽出 ``(verb, refspec_tokens, 目标仓库路径)``；仅识别 commit/push。

    ``-C`` 按 git 语义**顺序链式**解析（后段相对前段）；无法解析时返回哨兵
    ``""``（调用方按"目标仓库不明"保守当 main 处理，不静默放行）。
    """
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
    out: list[tuple[str, list[str], str | None]] = []
    i = 0
    while i < len(tokens):
        if tokens[i] != "git":
            i += 1
            continue
        j = i + 1
        target: str | None = None
        # 环境变量 GIT_DIR/GIT_WORK_TREE 同样会重定向 git 仓库；只看紧邻 git 前的
        # 赋值链（`env GIT_DIR=... git ...` 也覆盖），与 --git-dir 同一处置：
        # 目标不明 → 保守当 main（fail-closed）。
        k = i - 1
        while k >= 0 and "=" in tokens[k] and not tokens[k].startswith("-"):
            if tokens[k].startswith(("GIT_DIR=", "GIT_WORK_TREE=")):
                target = ""
                break
            k -= 1
        while j < len(tokens) and tokens[j].startswith("-"):
            tok = tokens[j]
            if tok in _GIT_VALUE_OPTS:
                if tok == "-C" and j + 1 < len(tokens):
                    target = _chained_cwd(target, tokens[j + 1], workdir)
                elif tok in ("--git-dir", "--work-tree"):
                    # 仓库被选项重定向，且不做后续路径语义跟随（--git-dir 可指
                    # .git 目录或 bare 仓库）→ 标记"目标仓库不明"，调用方按
                    # fail-closed 保守当 main（与 -C 链不可解析同一处置）。
                    target = ""
                j += 2
            elif tok.startswith(("--git-dir=", "--work-tree=")):
                target = ""
                j += 1
            else:
                j += 1
        if j < len(tokens) and tokens[j] in ("commit", "push"):
            out.append((tokens[j], tokens[j + 1 :], target))
            i = j + 1
        else:
            i = j
    return out


def _chained_cwd(current: str | None, seg: str, workdir: str | None) -> str:
    """按 ``git -C`` 语义把一段 -C 叠加到当前目标路径上；不可解析返回 ""。"""
    if current == "":  # 前段已不可解析
        return ""
    path = Path(seg)
    if path.is_absolute():
        return str(path)
    base = current if current is not None else workdir
    if not base:
        return ""
    return str(Path(base) / path)


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


def _normalize_ref_name(name: str) -> str:
    """refspec 目标归一：``+main`` 去 force 前缀，``refs/heads/x`` 取短名。"""
    name = name.strip().lstrip("+")
    prefix = "refs/heads/"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name


def _push_has_repo_option(verb_refspecs: list[str]) -> bool:
    """是否出现 ``--repo``/``--repo=`` 选项（值感知：``-o --repo`` 里的是值，不算）。

    护栏**不建模** ``--repo``：远端取自选项值、位置参数里没有 remote 位，
    "args[0] 是 remote" 的通则不再成立；且选项值不可信，不能原样喂给
    ``git ls-remote``（形如 ``--upload-pack=...`` 会被 git 当选项执行）。
    因此调用方按 fail-closed 拒绝该形式，而不是猜它的语义。
    """
    i = 0
    while i < len(verb_refspecs):
        tok = verb_refspecs[i]
        if tok == "--repo" or tok.startswith("--repo="):
            return True
        if tok in _PUSH_FLAGS_WITH_VALUE:
            # 该 token 是别的带值 flag 的值（如 ``-o --repo``），不是 --repo 选项。
            i += 2
            continue
        i += 1
    return False


def _push_positional(verb_refspecs: list[str]) -> tuple[list[str], list[str]]:
    """分离 push 的位置参数与 flag；分离式带值 flag 连同其值一起丢弃。

    返回 ``(args, flags)``。args[0] 是 remote（若有），其后是 refspec；
    ``--repo`` 形式不在这里建模（见 ``_push_has_repo_option``，调用方 fail-closed）。
    """
    args: list[str] = []
    flags: list[str] = []
    i = 0
    while i < len(verb_refspecs):
        tok = verb_refspecs[i]
        if tok in _PUSH_FLAGS_WITH_VALUE:  # 值不是 remote/refspec，整对跳过
            i += 2
            continue
        if tok.startswith("-"):
            flags.append(tok)
        else:
            args.append(tok)
        i += 1
    return args, flags


def _push_targets(
    verb_refspecs: list[str], workdir: str | None = None
) -> list[str]:
    """push 参数中的分支目标（首 token 是 remote，其余为 refspec）。

    - ``--all``/``--mirror`` → ``["__ALL__"]``（推全部分支，含 main）；
    - 仅 remote 无 refspec（``git push origin``）→ ``[]``（由调用方按当前分支判定）；
    - 其余：remote 之后每个 token 取 ``src:dst`` 的 dst，并归一 ``+``/``refs/heads/``
      前缀（``git push origin +main``、``HEAD:main``、``refs/heads/main`` 都必须被识别）；
    - ``-o ci.skip`` 这类分离式带值 flag 的值不是 remote/refspec，整对跳过；
    - src-only ``HEAD``/``@`` 视为当前分支（``git push origin HEAD`` 就是在推它）；
    - 通配 dst（``*`` 或 ``*/x``）可能写到 main → 按 ``__ALL__`` 宽判据；
    - ``--repo`` 形式不建模：``_main_write_targets`` 先判 ``_push_has_repo_option``
      并整体 fail-closed（远端由选项给出时位置参数没有 remote 位）。
    """
    args, flags = _push_positional(verb_refspecs)
    if any(f in ("--all", "--mirror") for f in flags):
        return ["__ALL__"]
    refspecs = args[1:]
    if not refspecs:
        return []
    targets: list[str] = []
    for tok in refspecs:
        name = _normalize_ref_name(tok.split(":", 1)[1] if ":" in tok else tok)
        if name in ("HEAD", "@"):  # src-only HEAD/@ = 当前分支
            name = _current_branch(workdir) or ""
        if not name:
            continue
        if name == "*" or name.endswith("/*"):  # 通配目标可能写到 main
            return ["__ALL__"]
        targets.append(name)
    return targets


def _push_src_name(
    refspecs: list[str], dst: str, workdir: str | None = None
) -> str | None:
    """与 ``dst`` 配对的 refspec 左端（src）名；无法唯一对应返回 None。

    ``""`` 表示删除型 refspec（``:main`` / ``--delete main``，src 为空）。
    """
    args, flags = _push_positional(refspecs)
    if any(flag in ("--delete", "-d") for flag in flags):
        return ""
    for tok in args[1:]:
        if ":" in tok:
            src, raw_dst = tok.split(":", 1)
        else:
            src = raw_dst = tok
        name = _normalize_ref_name(raw_dst)
        if name in ("HEAD", "@"):
            name = _current_branch(workdir) or ""
        if name != dst:
            continue
        src = _normalize_ref_name(src)
        if src in ("HEAD", "@"):
            src = _current_branch(workdir) or ""
        return src
    return None


def _push_is_delete(refspecs: list[str]) -> bool:
    """删除型 push：``--delete``/``-d`` flag 或 ``:<dst>`` 空 src refspec。

    删除远端 ref 没有"快进"可证，不能走快进校验；是否拦由调用方按
    "删除的是否 main"决定（见 ``check_git_main_write``）。
    """
    args, flags = _push_positional(refspecs)
    if any(flag in ("--delete", "-d") for flag in flags):
        return bool(args[1:])
    return any(tok.startswith(":") and tok.strip() != ":" for tok in args[1:])


def _git_out(args: list[str], cwd: str | None, timeout: float = 5.0) -> str | None:
    """只读 git 命令的 stdout；失败/超时/无 cwd 返回 None（按无法判定处理）。"""
    if not cwd:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _main_write_targets(
    verb: str, refspecs: list[str], workdir: str | None
) -> tuple[list[str], bool]:
    """命令触碰的 main/master 分支名，以及是否 ``--all``/``--mirror``。"""
    if verb == "commit":
        branch = _current_branch(workdir)
        return ([branch] if branch in _MAIN_BRANCHES else []), False
    if _push_has_repo_option(refspecs):
        # 远端由 --repo 给出：位置参数没有 remote 位，且选项值不可信（不喂 git）；
        # 不猜语义，返回标记让调用方在他人 live lane 期间整体拒绝。
        return ["__REPO_OPTION__"], False
    targets = _push_targets(refspecs, workdir)
    if targets == ["__ALL__"]:
        return sorted(_MAIN_BRANCHES), True
    if not targets:  # git push 无 refspec → 当前分支
        branch = _current_branch(workdir)
        return ([branch] if branch in _MAIN_BRANCHES else []), False
    hits: list[str] = []
    for name in targets:
        if name in _MAIN_BRANCHES and name not in hits:
            hits.append(name)
    return hits, False


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


def _idle_seconds(row: dict[str, Any], now: datetime) -> float | None:
    """距最后一次活动（last_activity，缺失回退 created_at）的秒数。

    无法解析或时区不可判定 → None（调用方按 live 处理，永不已此回收）。
    """
    raw = str(row.get("last_activity") or row.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        # naive 时间戳的时区不可判定：既可能是 naive UTC，也可能是 naive 本地
        # 时间，两者差一个时区偏移；据此算 idle 会放大或缩小闲置时长，反向
        # 影响回收。按 fail-closed 视为不可判定，该 lane 仍按 live 挡。
        return None
    return (now - ts).total_seconds()


def _repo_root(workdir: str | None) -> str | None:
    if not workdir:
        return None
    return _git_out(["rev-parse", "--show-toplevel"], workdir)


def _main_ref_sha(workdir: str | None) -> str | None:
    """本地 main/master 的 sha（refs 在 worktree 间共享，不依赖当前分支）。"""
    for ref in ("refs/heads/main", "refs/heads/master"):
        sha = _git_out(["rev-parse", "--verify", "--quiet", ref], workdir)
        if sha:
            return sha
    return None


def _is_ancestor(ancestor: str, descendant: str, workdir: str | None) -> bool | None:
    """ancestor 是否为 descendant 祖先；无法判定返回 None。"""
    if not ancestor or not descendant or not workdir:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", workdir, "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _main_repo_root(workdir: str | None) -> str | None:
    """主仓库根：worktree 共享 common dir 的父目录（lane 相对路径以此为准）。"""
    if not workdir:
        return None
    common = _git_out(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], workdir
    )
    if common:
        path = Path(common)
        if path.name == ".git":
            return str(path.parent)
        return str(path)
    return _repo_root(workdir)


def _worktree_clean(worktree: str, workdir: str | None) -> bool | None:
    """lane worktree 无未提交改动（含 untracked）→ True；有改动 False；无法判定 None。"""
    if not worktree:
        return None
    path = Path(worktree)
    if not path.is_absolute():
        base = _main_repo_root(workdir) or workdir
        if not base:
            return None
        path = Path(base) / path
    if not path.is_dir():
        return None
    out = _git_out(["status", "--porcelain"], str(path), timeout=10)
    if out is None:
        return None
    return out == ""


def _reclaim_basis(
    row: dict[str, Any], workdir: str | None, main_sha: str | None
) -> str:
    """失效回收依据：merged / clean_worktree / ""（不可回收）。"""
    head = str(row.get("head_sha") or "").strip()
    if head and main_sha and _is_ancestor(head, main_sha, workdir) is True:
        return "merged"
    if _worktree_clean(str(row.get("worktree") or ""), workdir) is True:
        return "clean_worktree"
    return ""


def _split_stale_lanes(
    rows: list[dict[str, Any]], *, workdir: str | None, now: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把他人 active lane 分成 (live, stale)；不可判定的旧 lane 一律按 live。"""
    if STALE_AFTER_S <= 0:  # 关闭回收（测试/特殊部署可用）
        return rows, []
    main_sha = _main_ref_sha(workdir)
    live: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    for row in rows:
        idle = _idle_seconds(row, now)
        if idle is None or idle <= STALE_AFTER_S:
            live.append(row)
            continue
        basis = _reclaim_basis(row, workdir, main_sha)
        if not basis:
            live.append(row)
            continue
        stale.append(
            {**row, "_reclaim_basis": basis, "_idle_hours": round(idle / 3600.0, 1)}
        )
    return live, stale


def _push_remote(refspecs: list[str]) -> str:
    """push 的 remote：第一个位置参数；缺省 origin（``--repo`` 形式不建模）。"""
    args, _flags = _push_positional(refspecs)
    return args[0] if args else "origin"


def _commit_known(sha: str, workdir: str | None) -> bool | None:
    """本地是否有该提交对象；无法判定 None。"""
    if not sha or not workdir:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", workdir, "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 128:
        return False
    return None


def _is_shallow(workdir: str | None) -> bool | None:
    """仓库是否浅克隆；无法判定 None。"""
    out = _git_out(["rev-parse", "--is-shallow-repository"], workdir)
    if out == "true":
        return True
    if out == "false":
        return False
    return None


_SAFE_REV_RE = re.compile(r"^(?!--)[A-Za-z0-9._/@^~-]+$")


def _rev_sha(rev: str, workdir: str | None) -> str | None:
    """分支名/HEAD/sha → 本地 commit sha；不可安全解析返回 None（无法判定）。

    只接受不以 ``-`` 开头、无选项/通配元字符的 token，绝不把任意命令文本
    喂给 git（防 ``--upload-pack=`` 一类选项注入）。
    """
    if not rev or not _SAFE_REV_RE.match(rev):
        return None
    if rev in ("HEAD", "@"):
        return _git_out(["rev-parse", "--verify", "--quiet", "HEAD"], workdir)
    return _git_out(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{rev}"], workdir
    ) or _git_out(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], workdir)


def _push_is_non_ff(
    branch: str, remote: str, workdir: str | None, local_ref: str | None = None
) -> bool:
    """远端 main 有本地未包含的提交 → True；读不到远端/本地按无法判定放行。

    ``local_ref`` 是被推 refspec 的 **src**（``git push origin feat:main`` 的
    ``feat``）；只用 dst 名解析会把本地 ``main`` 误当被推对象。``None``（无
    显式 refspec / 无法唯一对应）退回 dst 名。
    """
    if not workdir:
        return False
    if not remote or remote.startswith("-"):
        # 远端名不能安全作为 git 参数（形如 ``--upload-pack=...`` 会被当选项执行）
        # → 不喂给 ls-remote，按"非快进"保守拒绝（fail-closed）。
        return True
    out = _git_out(
        ["ls-remote", "--heads", remote, f"refs/heads/{branch}"], workdir, timeout=10
    )
    if not out:
        return False
    parts = out.splitlines()[0].split()
    remote_sha = parts[0] if parts else ""
    if not remote_sha:
        return False
    local_sha = _rev_sha(local_ref if local_ref is not None else branch, workdir)
    if not local_sha or local_sha == remote_sha:
        return False
    # 快进要求远端 sha 是本地祖先；对象在本地不存在即证明不是祖先。
    known = _commit_known(remote_sha, workdir)
    if known is False:
        # 浅克隆下远端对象常不在本地，缺失不能证明非快进 → 无法判定放行。
        return _is_shallow(workdir) is False
    if known is None:
        return False
    return _is_ancestor(remote_sha, local_sha, workdir) is False


def _lanes_note(rows: list[dict[str, Any]]) -> str:
    return "、".join(
        f"{row.get('lane_id')}({row.get('branch')} goal={row.get('goal_id')})"
        for row in rows[:3]
    )


def _stale_note(stale: list[dict[str, Any]]) -> str:
    if not stale:
        return ""
    items = "、".join(
        f"{row.get('lane_id')}(闲置 {row.get('_idle_hours')}h, "
        f"依据 {row.get('_reclaim_basis')})"
        for row in stale[:3]
    )
    return f"已按失效回收忽略：{items}。"


def _stale_payload(stale: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "lane_id": row.get("lane_id"),
            "branch": row.get("branch"),
            "status": row.get("status"),
            "idle_hours": row.get("_idle_hours"),
            "reclaim_basis": row.get("_reclaim_basis"),
        }
        for row in stale[:5]
    ]


def _deny(
    code: str,
    operation: str,
    blockers: list[dict[str, Any]],
    stale: list[dict[str, Any]],
    detail: str,
) -> dict[str, Any]:
    return {
        "reason": "lane_main_write_conflict",
        "reason_code": code,
        "operation": operation,
        "detail": detail + _stale_note(stale),
        "lanes": blockers[:5],
        "stale_lanes": _stale_payload(stale),
    }


def check_git_main_write(
    command: str,
    *,
    audit_dir: str,
    session_id: str,
    workdir: str | None,
) -> dict[str, Any] | None:
    """判定命令是否构成「他人 live lane 存在时直写 main」。

    返回 None=放行；返回 dict={reason, reason_code, operation, detail, lanes,
    stale_lanes} 表示拒绝事实。
    """
    if not command or not audit_dir:
        return None
    verbs = _git_verbs(command, workdir)
    if not verbs:
        return None
    commit_hit = False
    # (目标分支, 被推 src, 目标仓库, remote)；src="" 表示删除型 refspec
    pushes: list[tuple[str, str | None, str | None, str]] = []
    push_all = False
    push_delete_main = False
    basis_workdir: str | None = None
    for verb, refs, cwd_override in verbs:
        # 判定基于实际目标仓库：`git -C <path>` 会改变写入落到哪个分支。
        target_workdir = cwd_override if cwd_override is not None else workdir
        unresolved_cwd = target_workdir == ""  # -C 链不可解析
        if unresolved_cwd:
            target_workdir = workdir
        if basis_workdir is None and target_workdir:
            basis_workdir = target_workdir
        branches, is_all = _main_write_targets(verb, refs, target_workdir)
        if unresolved_cwd and not branches:  # 目标仓库不明 → 保守当 main
            branches = ["main"]
            is_all = verb == "push" and _push_targets(refs) == ["__ALL__"]
        if not branches:
            continue
        if verb == "commit":
            commit_hit = True
            continue
        push_all = push_all or is_all
        if _push_is_delete(refs) and any(name in _MAIN_BRANCHES for name in branches):
            push_delete_main = True
        remote = _push_remote(refs)
        for name in branches:
            entry = (
                name,
                _push_src_name(refs, name, target_workdir),
                target_workdir,
                remote,
            )
            if entry not in pushes:
                pushes.append(entry)
    if not commit_hit and not pushes:
        return None
    others = _active_other_lanes(audit_dir, session_id)
    if not others:
        return None
    # 宿主本地时区墙钟（RULE-AI-26 时间标注口径；仅用于计算闲置时长）。
    now = datetime.now().astimezone()
    live, stale = _split_stale_lanes(others, workdir=basis_workdir, now=now)
    if commit_hit and live:
        return _deny(
            "main_commit_other_lane",
            "commit",
            live,
            stale,
            "命令含 git commit 目标 main，且存在他人 live lane："
            f"{_lanes_note(live)}。"
            "并行会话期间 main 直写会与他人合并闸竞争（2026-11-05/06 两次事故）。"
            "建议: 先 lane_open 登记并在分支提交，或等对方 lane 合并后再动 main；"
            "合并建议可用 lane_merge_advice。",
        )
    if pushes:
        if any(entry[0] == "__REPO_OPTION__" for entry in pushes):
            if live:
                return _deny(
                    "main_push_repo_option_unmodeled",
                    "push",
                    live,
                    stale,
                    "命令用 --repo 指定远端：本闸不建模该形式（远端不在位置参数里，"
                    f"选项值也不可信），存在他人 live lane 时按 fail-closed 拒绝："
                    f"{_lanes_note(live)}。改写为 `git push <remote> <refspec>` 后重试。",
                )
            # 无他人 live lane → 闸本就不拦，去掉标记继续（无可判定目标）。
            pushes = [p for p in pushes if p[0] != "__REPO_OPTION__"]
        if push_delete_main:
            blockers = live
            code = "main_push_delete_other_lane"
            why = (
                "命令删除远端 main（删除型 refspec 无法用快进证明安全），"
                "且存在他人 live lane"
            )
        elif push_all:
            blockers = live
            code = "main_push_all_other_lane"
            why = (
                "命令含 git push --all/--mirror（会推他人分支），"
                "且存在他人 live lane"
            )
        else:
            blockers = [
                row
                for row in live
                if str(row.get("status") or "") in _PUSH_CLOSING
            ]
            code = "main_push_closing_lane"
            why = (
                "命令含 git push 目标 main，且存在他人 live 收口 lane"
                "（verifying/merging，即将改写 main）"
            )
        if blockers:
            return _deny(
                code,
                "push",
                blockers,
                stale,
                f"{why}：{_lanes_note(blockers)}。先等对方落定再推。",
            )
        for branch, local_ref, target_workdir, remote in pushes:
            if local_ref == "":  # 删除型 refspec：无"快进"语义（前面已按删除判定）
                continue
            if _push_is_non_ff(branch, remote, target_workdir, local_ref=local_ref):
                return {
                    "reason": "lane_main_write_conflict",
                    "reason_code": "main_push_not_fast_forward",
                    "operation": "push",
                    "detail": (
                        f"git push {branch} 非快进：远端 {remote}/{branch} "
                        "有本地未包含的提交。先 git fetch 并 rebase/merge 后再推"
                        "（本闸只做只读校验，不会自动改远端）。"
                    ),
                    "lanes": [],
                    "stale_lanes": [],
                }
    return None
