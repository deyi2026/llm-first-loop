"""命令通道写侧闸（P1-a）——把写侧授权从「工具面剔除」下沉到「命令族判定」.

DESIGN-20261030 §16（P1-a，并入 C8 档1 字面量校验）.

背景
----
P1-b（受限 child 直接剔除 ``execute_command`` 工具面）把写侧约束做成
「没有命令就没有写」：强度最高，但代价是受限 child 连只读命令与测试都跑不了。
P1-a 保留命令工具，把约束改到命令语义层——识别**写盘命令族**，要求写目标
可静态定位且落在 write scope 内，否则拒绝。

判定口径（fail-closed）
-----------------------
1. **不可静态判定的 shell 构造 ⇒ 直接拒绝**：命令替换（``$(...)``、反引号）、
   字面量分组（``(...)``、``{...}``）、控制流关键字（``if``/``for``/``case``…）、
   heredoc。这些构造让「写目标在哪」无法静态判定——与其猜，不如拒。
2. **写盘命令族**（rm/cp/mv/… + git 写子命令 + find 的删除与落盘动作 + 压缩/归档/
   构建/包管理族）⇒ 写目标必须静态可定位且落在 scope 内。**隐式写目标**（git 写
   ``.git/``、``xargs`` 目标来自 stdin、``mktemp`` 写 ``TMPDIR``、构建产物、
   ``find -delete``）直接拒。
3. **解释器与测试运行器**（python/node/pytest…）⇒ 不判为写盘族。这是 P1-a 相对
   P1-b 的已知放宽，残余清单见 DESIGN §16.6。
4. **读侧字面量** ⇒ 不阻断；越界记 ``scope_unverified`` 审计。scope 是写侧授权：
   把读侧封成监狱会阻断解释器与测试执行，与 P1-a 的灵活性目标冲突。
5. 只有 ``scope.declared`` 为真才生效；未受限会话行为零变化。

本模块只做判定，不做强制点（接线在 ``tools/builtin/execute_command.py``）。
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass

from llm_loop.core.write_scope import WriteScope, scope_allows

MAX_TOKENS = 512
MAX_SEGMENTS = 64
MAX_DEPTH = 3

# 显式写目标的命令族（写目标可从参数定位）
WRITE_FAMILY = frozenset(
    {
        "rm", "rmdir", "mkdir", "touch", "install", "dd", "tee", "truncate",
        "ln", "rsync", "shred", "chmod", "chown", "chgrp", "sed", "tar",
        "unzip", "zip", "gzip", "xz", "bzip2", "zstd", "cp", "mv", "mktemp",
        "curl", "wget", "patch",
    }
)

# 隐式写目标的命令族（写到哪里不可静态定位 ⇒ 直接拒）
IMPLICIT_WRITE = frozenset(
    {
        "make", "cmake", "ninja", "gradle", "mvn", "cargo", "go", "docker",
        "pip", "pip3", "npm", "pnpm", "yarn", "brew", "apt", "apt-get",
        "yum", "dnf", "terraform", "kubectl", "jekyll",
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
        "notes", "replace", "sparse-checkout", "format-patch", "bundle",
    }
)

# git 全局选项（取值型选项：其后的参数不是子命令）
GIT_VALUE_OPTIONS = frozenset(
    {
        "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path",
        "--super-prefix", "--config-env",
    }
)

# 组合载体：自身不写盘，但会把写盘命令作为参数执行
CARRIERS = frozenset(
    {
        "find", "xargs", "env", "sudo", "su", "nohup", "time", "timeout",
        "command", "stdbuf", "nice", "exec", "setsid", "ionice", "eval",
        "watch",
    }
)

# 载体自身选项（取值型：其后一个 token 是选项值而非命令）
CARRIER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "sudo": frozenset(
        {
            "-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "--close-from",
            "-D", "--chdir", "-h", "--host", "-r", "--role", "-t", "--type",
            "-U", "--other-user",
        }
    ),
    "timeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "stdbuf": frozenset({"-i", "--input", "-o", "--output", "-e", "--error"}),
    "watch": frozenset({"-n", "--interval", "-b", "--beep", "-x", "--exec"}),
}

# shell 解释器（-c 载荷按命令串重解析；脚本文件写目标不可静态定位 ⇒ 拒）
SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})

# 控制流关键字（段首出现 ⇒ 不可静态判定 ⇒ 拒）
SHELL_KEYWORDS = frozenset(
    {
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
        "done", "case", "esac", "select", "function", "coproc", "!", "in",
    }
)

# 段分隔运算符
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "|&", "\n"})

# 写重定向（含 fd 合并形式）
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})
_READ_REDIRECTS = frozenset({"<", "<<<"})

# 写目标无法静态定位的标记（变量展开/命令替换/通配/家目录/花括号占位）
_UNSTATIC_MARKERS = ("$", "`", "*", "?", "~", "{", "}")

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class _UnparsableError(Exception):
    """命令串无法做 shell 词法切分（引号不闭合等）——fail-closed 拒绝。"""


@dataclass(frozen=True)
class CommandScopeDecision:
    """一次命令写侧判定结果。

    - ``allowed=False`` 时 ``reason`` 是稳定的机器可读原因码；
    - ``unverified`` 是「放行但无法证明落在 scope 内」的 (path, reason) 清单
      （读侧越界字面量等），供 ``scope_unverified`` 审计落账。
    """

    allowed: bool
    reason: str = ""
    detail: str = ""
    unverified: tuple[tuple[str, str], ...] = ()


def _basename(token: str) -> str:
    return os.path.basename(str(token))


def _is_assignment(token: str) -> bool:
    return bool(_ASSIGNMENT_RE.match(str(token)))


def _tokenize(command: str) -> list[str]:
    """shell 词法切分（运算符独立成词）。无法切分 → 抛 _UnparsableError。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError as exc:
        raise _UnparsableError(str(exc)) from exc


def _split_segments(tokens: Sequence[str]) -> list[list[str]]:
    """按 shell 运算符切段。"""
    segments: list[list[str]] = []
    argv: list[str] = []
    for token in tokens:
        if token in _OPERATORS:
            if argv:
                segments.append(argv)
            argv = []
            continue
        argv.append(token)
    if argv:
        segments.append(argv)
    return segments


def _unmodeled_construct(tokens: Sequence[str]) -> str:
    """扫描不可静态判定的构造（命令替换 / 分组 / heredoc）。命中即返回说明。"""
    for token in tokens:
        if token == "$" or "$(" in token or "`" in token:
            return f"command_substitution: {token}"
        if token in ("(", ")", "{", "}"):
            return f"grouping_construct: {token}"
        if token in ("<<", "<<-"):
            return f"heredoc_construct: {token}"
    return ""


def _strip_fd_prefixes(tokens: list[str]) -> list[str]:
    """去掉段首的 fd 号前缀（``2> file`` 里的 ``2``）。"""
    index = 0
    while index < len(tokens) and tokens[index].isdigit():
        index += 1
    return tokens[index:]


def _strip_carrier_prefix(name: str, args: list[str]) -> list[str]:
    """跳过载体自身的选项（及取值型选项的参数），返回载体之后的参数。"""
    value_options = CARRIER_VALUE_OPTIONS.get(name, frozenset())
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            return args[index + 1:]
        if "=" in token and token.startswith("-"):
            index += 1
            continue
        if token in value_options:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if name == "env" and _is_assignment(token):
            index += 1
            continue
        break
    return args[index:]


def _non_flag_args(args: Sequence[str]) -> list[str]:
    return [a for a in args if not str(a).startswith("-")]


def _flag_value(args: Sequence[str], *flags: str) -> str | None:
    """取 ``-t DIR`` / ``--target-directory=DIR`` 形态的选项值。"""
    for index, token in enumerate(args):
        for flag in flags:
            if token == flag:
                if index + 1 < len(args):
                    return args[index + 1]
                return ""
            if token.startswith(flag + "="):
                return token.split("=", 1)[1]
    return None


def _write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """返回 (静态写目标列表, 是否存在无法静态定位的隐式写目标)."""
    positional = _non_flag_args(args)
    if name in ("cp", "mv", "install", "ln", "rsync"):
        target_dir = _flag_value(args, "-t", "--target-directory")
        if target_dir is not None:
            return ([target_dir], not target_dir)
        if name == "ln" and "-T" in args:
            return ([positional[-1]] if positional else [], not positional)
        return (positional[-1:], len(positional) < 2)
    if name in ("rm", "rmdir", "mkdir", "touch", "tee", "truncate", "shred", "patch"):
        return (positional, False)
    if name in ("chmod", "chown", "chgrp"):
        return (positional[1:], len(positional) < 2)
    if name == "sed":
        if "-i" in args or "--in-place" in args:
            return (positional[1:], len(positional) < 2)
        return ([], False)
    if name == "dd":
        outputs = [a.split("=", 1)[1] for a in args if a.startswith("of=")]
        return (outputs, not outputs)
    if name == "tar":
        if any(a in ("-x", "--extract") for a in args):
            return ([], True)
        return (positional[:1], not positional)
    if name == "unzip":
        dest = _flag_value(args, "-d", "--directory")
        return ([dest] if dest else [], not dest)
    if name == "zip":
        return (positional[:1], not positional)
    if name in ("gzip", "xz", "bzip2", "zstd"):
        if any(a in ("-d", "--decompress", "-c", "--stdout") for a in args):
            return ([], False)
        return (positional[:1], not positional)
    if name == "curl":
        out = _flag_value(args, "-o", "--output")
        if out is not None:
            return ([out], not out)
        out_dir = _flag_value(args, "--output-dir")
        if out_dir is not None:
            return ([out_dir], not out_dir)
        if "-O" in args or "--remote-name" in args:
            return ([], True)
        return ([], False)
    if name == "wget":
        out = _flag_value(args, "-O", "--output-document")
        if out is not None:
            return ([out], not out)
        out_dir = _flag_value(args, "-P", "--directory-prefix")
        if out_dir is not None:
            return ([out_dir], not out_dir)
        return ([], False)
    return ([], True)


def _git_subcommand(args: Sequence[str]) -> str:
    """取 git 子命令（跳过全局选项与其取值）。"""
    index = 0
    while index < len(args):
        token = args[index]
        if token in GIT_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


class _Scanner:
    """一次命令串的写侧扫描器（状态在段间累积：cwd 位移、审计清单）。"""

    def __init__(self, scope: WriteScope, workspace_root: str, cwd: str) -> None:
        self.scope = scope
        self.workspace_root = workspace_root
        self.cwd = cwd
        self.unverified: list[tuple[str, str]] = []
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
        unmodeled = _unmodeled_construct(tokens)
        if unmodeled:
            return CommandScopeDecision(False, "unmodeled_shell_construct", unmodeled)
        segments = _split_segments(tokens)
        if len(segments) > MAX_SEGMENTS:
            return CommandScopeDecision(
                False, "command_too_large", f"segments={len(segments)} > {MAX_SEGMENTS}"
            )
        for argv in segments:
            decision = self._scan_segment(argv, depth)
            if decision is not None:
                return decision
        return CommandScopeDecision(True, unverified=tuple(self.unverified))

    # ── 段级判定 ──────────────────────────────────────────────────────────

    def _scan_segment(
        self, argv: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        write_redirects, read_redirects, cmd_tokens = self._split_redirects(argv)
        cmd_tokens = _strip_fd_prefixes(cmd_tokens)
        while cmd_tokens and _is_assignment(cmd_tokens[0]):
            cmd_tokens.pop(0)
        if not cmd_tokens:
            return None
        name = _basename(cmd_tokens[0])
        if name == "cd" or name == "pushd":
            self.cwd_unstable = True
        if name in SHELL_KEYWORDS:
            return CommandScopeDecision(
                False, "shell_keyword_construct", f"{name}：控制流不可静态判定"
            )
        if name == "eval":
            return self._scan_eval(cmd_tokens[1:], depth)
        effective, args = self._resolve_command(cmd_tokens)
        if effective is None:
            return None
        effective_name = _basename(effective[0])
        if effective_name in SHELL_INTERPRETERS:
            decision = self._scan_interpreter(effective_name, args, depth)
            if decision is not None:
                return decision
        elif effective_name == "find":
            decision = self._scan_find(args, depth)
            if decision is not None:
                return decision
        elif effective_name == "xargs":
            return CommandScopeDecision(
                False, "implicit_write_target", "xargs：写目标来自 stdin，不可静态定位"
            )
        elif effective_name == "git":
            sub = _git_subcommand(args)
            if sub in GIT_WRITE_SUBCOMMANDS:
                return CommandScopeDecision(
                    False, "implicit_write_target", f"git {sub}：写目标不可静态定位"
                )
        elif effective_name in IMPLICIT_WRITE:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{effective_name}：写目标不可静态定位（构建/安装族）",
            )
        elif effective_name in WRITE_FAMILY:
            targets, implicit = _write_targets(effective_name, args)
            if implicit:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"{effective_name}：写目标无法静态定位",
                )
            for target in targets:
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(
                        False, reason, detail, tuple(self.unverified)
                    )
        for target in write_redirects:
            ok, reason, detail = self._check_target(target)
            if not ok:
                return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        self._audit_literals(cmd_tokens + read_redirects)
        return None

    def _split_redirects(
        self, argv: Sequence[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """拆出写重定向目标、读重定向源与命令本体。"""
        writes: list[str] = []
        reads: list[str] = []
        cmd: list[str] = []
        index = 0
        while index < len(argv):
            token = argv[index]
            if token in _WRITE_REDIRECTS:
                if index + 1 < len(argv):
                    writes.append(argv[index + 1])
                index += 2
                continue
            if token == ">&":
                if index + 1 < len(argv):
                    nxt = argv[index + 1]
                    if not (nxt.isdigit() or nxt == "-"):
                        writes.append(nxt)
                index += 2
                continue
            if token in _READ_REDIRECTS:
                if index + 1 < len(argv):
                    reads.append(argv[index + 1])
                index += 2
                continue
            cmd.append(token)
            index += 1
        return writes, reads, cmd

    def _resolve_command(self, tokens: list[str]) -> tuple[list[str] | None, list[str]]:
        """解析载体前缀，返回 (有效命令 tokens, 其参数)。"""
        if not tokens:
            return None, []
        name = _basename(tokens[0])
        if name in CARRIERS and name not in ("find", "xargs", "eval"):
            rest = _strip_carrier_prefix(name, tokens[1:])
            if not rest:
                return tokens, tokens[1:]
            return self._resolve_command(rest)
        return tokens, tokens[1:]

    def _scan_eval(self, args: Sequence[str], depth: int) -> CommandScopeDecision | None:
        """``eval`` 的载荷按命令串重解析。"""
        if depth + 1 > MAX_DEPTH:
            return CommandScopeDecision(False, "nesting_too_deep", "eval 嵌套过深")
        if not args:
            return None
        return self.scan(" ".join(args), depth + 1)

    def _scan_interpreter(
        self, name: str, args: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        """shell 解释器：``-c`` 载荷重解析；脚本文件写目标不可静态定位 ⇒ 拒。"""
        if "-c" in args:
            index = args.index("-c")
            payload = args[index + 1] if index + 1 < len(args) else ""
            if not payload:
                return CommandScopeDecision(
                    False, "unparsable_command", f"{name} -c 缺载荷"
                )
            if depth + 1 > MAX_DEPTH:
                return CommandScopeDecision(
                    False, "nesting_too_deep", "解释器嵌套过深"
                )
            return self.scan(payload, depth + 1)
        script = [a for a in args if not str(a).startswith("-")]
        if script:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name} {script[0]}：脚本写目标不可静态定位",
            )
        return None

    def _scan_find(self, args: Sequence[str], depth: int) -> CommandScopeDecision | None:
        """``find`` 自身的删除与落盘动作（-delete / -fprint / -exec）。"""
        index = 0
        while index < len(args):
            token = args[index]
            if token == "-delete":
                return CommandScopeDecision(
                    False, "implicit_write_target", "find -delete：删除目标不可静态定位"
                )
            if token in ("-fprint", "-fprintf", "-fls"):
                target = args[index + 1] if index + 1 < len(args) else ""
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
                index += 2
                continue
            if token in ("-exec", "-execdir"):
                nested = args[index + 1:]
                effective, nested_args = self._resolve_command(nested)
                if effective is None:
                    return None
                nested_name = _basename(effective[0])
                if nested_name == "find" or nested_name == "xargs":
                    return CommandScopeDecision(
                        False, "implicit_write_target", "find -exec：写目标不可静态定位"
                    )
                targets, implicit = _write_targets(nested_name, nested_args)
                if implicit:
                    return CommandScopeDecision(
                        False,
                        "implicit_write_target",
                        f"find -exec {nested_name}：写目标无法静态定位",
                    )
                for target in targets:
                    if any(marker in target for marker in ("{", "}", "$")):
                        return CommandScopeDecision(
                            False,
                            "unverifiable_write_target",
                            f"{target}（占位符/展开，目标不可静态定位）",
                        )
                    ok, reason, detail = self._check_target(target)
                    if not ok:
                        return CommandScopeDecision(
                            False, reason, detail, tuple(self.unverified)
                        )
                index = len(args)
                continue
            index += 1
        return None

    # ── 目标判定与审计 ────────────────────────────────────────────────────

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
                return (
                    False,
                    "unverifiable_write_target",
                    f"{token}（cwd 位移后无法静态定位）",
                )
            abs_path = os.path.realpath(os.path.join(self.cwd, token))
        allowed, reason = scope_allows(self.scope, abs_path, self.workspace_root)
        if not allowed:
            return False, f"write_target_{reason}", f"{token} → {abs_path}（{reason}）"
        return True, "", ""

    def _audit_literals(self, tokens: Sequence[str]) -> None:
        """读侧字面量审计：越界不阻断，记 ``scope_unverified``（DESIGN §16 口径 4）。"""
        for token in tokens:
            candidate = str(token)
            if "=" in candidate and candidate.startswith("-"):
                candidate = candidate.split("=", 1)[1]
            if candidate.startswith("/"):
                allowed, reason = scope_allows(self.scope, candidate, self.workspace_root)
                if not allowed:
                    self.unverified.append((candidate, reason))
                continue
            if not (candidate.startswith("./") or candidate.startswith("../")):
                continue
            if self.cwd_unstable:
                self.unverified.append((candidate, "cwd 位移，无法静态定位"))
                continue
            abs_path = os.path.realpath(os.path.join(self.cwd, candidate))
            allowed, reason = scope_allows(self.scope, abs_path, self.workspace_root)
            if not allowed:
                self.unverified.append((candidate, reason))


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
