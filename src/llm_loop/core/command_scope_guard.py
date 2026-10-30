"""命令通道写侧闸（P1-a）——把写侧授权从「工具面剔除」下沉到「命令族判定」.

DESIGN-20261030 §16（对应 §5.6 三档里的 P1-a，并入 C8 档1 字面量校验）.

背景
----
P1-b（受限 child 直接剔除 ``execute_command`` 工具面）把写侧约束做成
「没有命令就没有写」：强度最高，但代价是受限 child 连只读命令与测试都跑不了。
P1-a 保留命令工具，把约束改到命令语义层——识别**写盘命令族**，要求写目标
可静态定位且落在 write scope 内，否则拒绝。

判定口径（fail-closed）
-----------------------
1. **写盘命令族**（rm/cp/mv/… + git 写子命令 + 重定向 + 组合载体嵌套）→
   写目标必须静态可定位且落在 scope 内。不可静态定位（变量展开/通配/cd 位移/
   隐式目标）→ 拒绝。
2. **解释器**（python/node/perl 与 ``-c`` 载荷）→ 不判为写盘族。这是 P1-a
   相对 P1-b 的已知放宽，残余清单见 DESIGN §16。
3. **读侧字面量** → 不阻断；越界时记 ``scope_unverified`` 审计。scope 是写侧
   授权：把读侧也封成监狱会阻断解释器与测试执行（与 P1-a 的灵活性目标冲突），
   读侧越界以审计暴露，不静默。
4. 只有 ``scope.declared`` 为真才生效；未受限会话行为零变化。

本模块只做判定，不做强制点（接线在 ``tools/builtin/execute_command.py``）。
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence
from dataclasses import dataclass

from llm_loop.core.write_scope import WriteScope, scope_allows

MAX_TOKENS = 512
MAX_SEGMENTS = 64
MAX_DEPTH = 3

# 写盘命令族（argv0 basename）：直接写盘或改写磁盘状态
WRITE_FAMILY = frozenset(
    {
        "rm", "rmdir", "mkdir", "touch", "install", "dd", "tee", "truncate",
        "ln", "rsync", "shred", "chmod", "chown", "chgrp", "sed", "tar",
        "unzip", "zip", "patch", "cp", "mv", "mktemp",
    }
)

# git 写子命令（改写 .git/ 或工作树）
GIT_WRITE_SUBCOMMANDS = frozenset(
    {
        "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean",
        "clone", "commit", "fetch", "gc", "init", "merge", "mv", "pull",
        "push", "rebase", "repack", "reset", "restore", "revert", "rm",
        "stash", "submodule", "switch", "tag", "worktree", "write-tree",
        "commit-tree", "mktree", "hash-object", "update-ref", "update-index",
        "notes", "replace", "sparse-checkout", "format-patch",
    }
)

# 组合载体：自身不写盘，但会把写盘命令作为参数执行（find -exec / xargs / sudo）
CARRIERS = frozenset(
    {
        "find", "xargs", "env", "sudo", "nohup", "time", "timeout", "command",
        "stdbuf", "watch", "nice", "exec", "setsid", "ionice",
    }
)

# 嵌套 shell：``-c`` 载荷需递归解析
SHELL_BINS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})

# 段分隔运算符
_OPERATORS = frozenset({"&&", "||", ";", "|", "&"})

# 写目标无法静态定位的标记（变量展开/命令替换/通配/家目录/花括号占位）
_UNSTATIC_MARKERS = ("$", "`", "*", "?", "~", "{", "}")


class _UnparsableError(Exception):
    """命令串无法做 shell 词法切分（引号不闭合等）——fail-closed 拒绝。"""


@dataclass(frozen=True)
class CommandScopeDecision:
    """一次命令写侧判定结果。

    - ``allowed=False`` 时 ``reason`` 是稳定的机器可读原因码；
    - ``unverified`` 是「放行但无法证明落在 scope 内」的路径清单（读侧越界、
      cwd 位移后的显式相对路径），供 ``scope_unverified`` 审计落账。
    """

    allowed: bool
    reason: str = ""
    detail: str = ""
    unverified: tuple[str, ...] = ()


def _basename(token: str) -> str:
    return os.path.basename(str(token))


def _tokenize(command: str) -> list[str]:
    """shell 词法切分（运算符独立成词）。无法切分 → 抛 _Unparsable。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError as exc:
        raise _UnparsableError(str(exc)) from exc


def _split_segments(tokens: Sequence[str]) -> list[tuple[list[str], list[str]]]:
    """按 shell 运算符切段；重定向目标单独收集（它们是写目标）。"""
    segments: list[tuple[list[str], list[str]]] = []
    argv: list[str] = []
    redirects: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _OPERATORS:
            if argv or redirects:
                segments.append((argv, redirects))
            argv, redirects = [], []
            index += 1
            continue
        if token in (">", ">>"):
            index = _take_redirect(tokens, index, redirects)
            continue
        if token == "<<":
            index += 2  # heredoc 分隔符不是写目标
            continue
        if token == "<":
            index += 2  # 输入源不是写目标
            continue
        argv.append(token)
        index += 1
    if argv or redirects:
        segments.append((argv, redirects))
    return segments


def _take_redirect(tokens: Sequence[str], index: int, redirects: list[str]) -> int:
    """取重定向目标。``2>&1`` 这类 fd 复制不产生写目标。"""
    if index + 2 < len(tokens) and tokens[index + 1] == "&" and tokens[index + 2] in ("1", "2"):
        return index + 3
    if index + 1 < len(tokens) and tokens[index + 1] not in _OPERATORS:
        redirects.append(tokens[index + 1])
        return index + 2
    redirects.append("")
    return index + 1


def _write_targets(argv: Sequence[str]) -> tuple[list[str], bool]:
    """返回 (静态写目标列表, 是否存在无法静态定位的隐式写目标).

    隐式写目标 = 目标落在当前目录/环境目录/``.git/`` 等闸无法静态定位的位置
    （如 ``git commit`` 写 ``.git/``、``xargs rm`` 目标来自 stdin、``mktemp``
    写 ``TMPDIR``）。按 P1-a 口径一律拒绝，不靠「看起来无害」放行。
    """
    if not argv:
        return [], False
    name = _basename(argv[0])
    args = [a for a in argv[1:] if not a.startswith("-")]
    if name in ("cp", "mv", "install", "ln", "rsync"):
        return (args[-1:], len(args) < 2)
    if name in ("rm", "rmdir", "mkdir", "touch", "tee", "truncate", "shred", "patch"):
        return (args, not args)
    if name in ("chmod", "chown", "chgrp"):
        return (args[1:], len(args) < 2)
    if name == "sed":
        inplace = "-i" in argv or "--in-place" in argv
        return (args[1:], not args) if inplace else ([], False)
    if name == "dd":
        of = [a.split("=", 1)[1] for a in argv[1:] if a.startswith("of=")]
        return (of, not of)
    if name == "tar":
        if any(a in ("-x", "--extract") for a in argv):
            return [], True
        return (args[:1], not args)
    if name == "unzip":
        if "-d" in argv:
            idx = argv.index("-d")
            dest = argv[idx + 1] if idx + 1 < len(argv) else ""
            return ([dest], not dest)
        return [], True
    if name == "zip":
        return (args[:1], not args)
    return [], True


def _literal_candidates(token: str) -> list[str]:
    """拆出 token 里可能的路径字面量（``--output=/abs`` 形态也覆盖）。"""
    if "=" in token:
        head, tail = token.split("=", 1)
        return [head, tail]
    return [token]


def _looks_explicit_relative(token: str) -> bool:
    return token.startswith("./") or token.startswith("../") or token in (".", "..")


class _Scanner:
    """一次命令串的写侧扫描器（状态在段间累积：cwd 位移、审计清单）。"""

    def __init__(self, scope: WriteScope, workspace_root: str, cwd: str) -> None:
        self.scope = scope
        self.workspace_root = workspace_root
        self.cwd = cwd
        self.unverified: list[str] = []
        self.cwd_unstable = False

    def scan(self, command: str, depth: int = 0) -> CommandScopeDecision:
        try:
            tokens = _tokenize(command)
        except _UnparsableError as exc:
            return CommandScopeDecision(False, "unparsable_command", str(exc))
        if len(tokens) > MAX_TOKENS:
            return CommandScopeDecision(
                False, "command_too_large", f"tokens={len(tokens)} > {MAX_TOKENS}"
            )
        segments = _split_segments(tokens)
        if len(segments) > MAX_SEGMENTS:
            return CommandScopeDecision(
                False, "command_too_large", f"segments={len(segments)} > {MAX_SEGMENTS}"
            )
        for argv, redirects in segments:
            decision = self._scan_segment(argv, redirects, depth)
            if decision is not None:
                return decision
        return CommandScopeDecision(True, unverified=tuple(self.unverified))

    def _scan_segment(
        self, argv: Sequence[str], redirects: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        name = _basename(argv[0]) if argv else ""
        if name in ("cd", "pushd"):
            self.cwd_unstable = True
        nested = self._nested_payload(name, argv)
        if nested is not None:
            if depth + 1 > MAX_DEPTH:
                return CommandScopeDecision(False, "nesting_too_deep", nested[:120])
            decision = self.scan(nested, depth + 1)
            if not decision.allowed:
                return decision
        write_cmd = self._effective_write_cmd(argv)
        targets: list[str] = []
        implicit = False
        if write_cmd is not None:
            targets, implicit = _write_targets(write_cmd)
        targets.extend(redirects)
        if implicit:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{_basename(write_cmd[0])}：写目标无法静态定位",
            )
        for target in targets:
            ok, reason, detail = self._check_target(target)
            if not ok:
                return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        self._audit_literals(argv)
        return None

    def _nested_payload(self, name: str, argv: Sequence[str]) -> str | None:
        """嵌套 shell 的 ``-c`` 载荷（需递归判定）。"""
        if name not in SHELL_BINS or "-c" not in argv:
            return None
        idx = argv.index("-c")
        return argv[idx + 1] if idx + 1 < len(argv) else None

    def _effective_write_cmd(self, argv: Sequence[str]) -> list[str] | None:
        """判定本段是否写盘；是则返回「等效写盘命令」（用于提取写目标）。"""
        if not argv:
            return None
        name = _basename(argv[0])
        if name in WRITE_FAMILY:
            return list(argv)
        if name == "git":
            sub = argv[1] if len(argv) > 1 else ""
            return ["git", sub, *argv[2:]] if sub in GIT_WRITE_SUBCOMMANDS else None
        if name in CARRIERS:
            return self._carrier_write_cmd(argv)
        return None

    def _carrier_write_cmd(self, argv: Sequence[str]) -> list[str] | None:
        """载体参数里出现的写盘命令（``find -exec rm`` / ``xargs rm`` / ``sudo rm``）。"""
        for idx in range(1, len(argv)):
            token = argv[idx]
            if token.startswith("-"):
                continue
            base = _basename(token)
            if base in WRITE_FAMILY:
                return [base, *argv[idx + 1:]]
            if base == "git":
                sub = argv[idx + 2] if idx + 2 < len(argv) else ""
                if sub in GIT_WRITE_SUBCOMMANDS:
                    return ["git", sub, *argv[idx + 3:]]
        return None

    def _check_target(self, token: str) -> tuple[bool, str, str]:
        """单个写目标判定：可静态定位 + 落在 scope 内。"""
        if not token:
            return False, "implicit_write_target", "写目标为空"
        if any(marker in token for marker in _UNSTATIC_MARKERS):
            return False, "unverifiable_write_target", f"{token}（含展开/通配/占位符）"
        if token.startswith("/"):
            abs_path = os.path.realpath(os.path.expanduser(token))
        else:
            if self.cwd_unstable:
                return False, "unverifiable_write_target", f"{token}（cwd 位移后无法静态定位）"
            abs_path = os.path.realpath(os.path.join(self.cwd, token))
        allowed, reason = scope_allows(self.scope, abs_path, self.workspace_root)
        if not allowed:
            return False, f"write_target_{reason}", f"{token} → {abs_path}（{reason}）"
        return True, "", ""

    def _audit_literals(self, argv: Sequence[str]) -> None:
        """读侧字面量审计：越界不阻断，记 ``scope_unverified``（DESIGN §16 口径 3）。"""
        for token in argv:
            for candidate in _literal_candidates(token):
                if candidate.startswith("/"):
                    allowed, reason = scope_allows(
                        self.scope, candidate, self.workspace_root
                    )
                    if not allowed:
                        self.unverified.append(f"{candidate}（{reason}）")
                    continue
                if not _looks_explicit_relative(candidate):
                    continue
                if self.cwd_unstable:
                    self.unverified.append(f"{candidate}（cwd 位移，无法静态定位）")
                    continue
                abs_path = os.path.realpath(os.path.join(self.cwd, candidate))
                allowed, reason = scope_allows(self.scope, abs_path, self.workspace_root)
                if not allowed:
                    self.unverified.append(f"{candidate} → {abs_path}（{reason}）")


def check_command_scope(
    command: str,
    *,
    scope: WriteScope | None,
    workspace_root: str,
    workdir: str = "",
) -> CommandScopeDecision:
    """命令写侧判定入口。

    - ``scope`` 为 None 或 ``declared=False`` → 恒放行（未受限会话零行为变化）。
    - ``workdir`` 为空 → 以 ``workspace_root`` 为相对写目标的解析基准。
    """
    if scope is None or not getattr(scope, "declared", False):
        return CommandScopeDecision(True)
    root = os.path.realpath(os.path.expanduser(str(workspace_root)))
    base = os.path.realpath(os.path.expanduser(str(workdir))) if workdir else root
    scanner = _Scanner(scope, root, base)
    return scanner.scan(command)
