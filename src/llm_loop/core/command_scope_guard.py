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
        # 第二轮审查后补入的写工具：名单外的命令会走「按只读处理」的默认路径，
        # 那是**放行**方向——写工具漏进名单＝漏检。故写工具宁可多列。
        "scp", "sftp", "ftp", "lftp", "rcp", "perl", "ex", "ed", "openssl",
        "gpg", "gpg2", "7z", "7za", "7zr", "lzma", "lz4", "brotli", "pigz",
        "unpigz", "hg", "svn", "bzr", "fossil", "darcs",
        "fallocate", "chflags", "setfattr", "chattr", "rename", "sqlite3",
        "gunzip", "bunzip2", "unxz",
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
        "config", "bisect",
    }
)

# git 全局选项（取值型选项：其后的参数不是子命令）
GIT_VALUE_OPTIONS = frozenset(
    {
        "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path",
        "--super-prefix", "--config-env", "-c",
    }
)

# git 读子命令里 ``-o/--output`` 表示**输出文件**的子命令（其余子命令的 -o 是别的语义）
GIT_OUTPUT_SUBCOMMANDS = frozenset({"archive", "diff", "show"})

# 组合载体：自身不写盘，但会把写盘命令作为参数执行
CARRIERS = frozenset(
    {
        "find", "xargs", "env", "sudo", "nohup", "time", "timeout",
        "command", "stdbuf", "nice", "exec", "setsid", "ionice", "eval",
        "watch", "busybox",
    }
)

# 载体自身选项（取值型：其后一个 token 是选项值而非命令）
CARRIER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "sudo": frozenset(
        {
            "-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "--close-from",
            "-D", "--chdir", "-h", "--host", "-r", "--role", "-t", "--type",
            "-U", "--other-user",
        }
    ),
    "timeout": frozenset({"-k", "--kill-after", "-s", "--signal"}),
    "stdbuf": frozenset({"-i", "--input", "-o", "--output", "-e", "--error"}),
    # watch 的 -x/--exec 是**布尔**开关（命令直接跟在后面），不是取值型选项
    "watch": frozenset({"-n", "--interval", "-b", "--beep"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "ionice": frozenset(
        {"-c", "--class", "-n", "--classdata", "-p", "--pid", "-t", "--ignore"}
    ),
}

# 载体的**位置参数**（选项之后的普通参数不是命令）：timeout 的时长
CARRIER_SKIP_POSITIONALS = {"timeout": 1}

# shell 解释器（-c 载荷按命令串重解析；脚本文件写目标不可静态定位 ⇒ 拒）
SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash"})

# 脚本载入命令（. / source）：脚本内写目标不可静态定位 ⇒ 拒
SCRIPT_LOADERS = frozenset({".", "source"})

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

# 命令身份（argv[0]）必须是**字面量**：含展开/通配/花括号的命令身份不可静态判定
# （``$X``、``r{m,}``、``$(which rm)``…）。命令身份不字面 ⇒ 拒。
_IDENTITY_MARKERS = ("$", "`", "*", "?", "~", "{", "}", "[", "]")

# 转义分号哨兵：``\;`` 是 find -exec 的**参数终止符**，不是命令分隔符。
# shlex 的 posix 模式会吃掉反斜杠，故先替换成哨兵再切词。
_ESC_SEM = "\x01esc-semi\x01"

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
    """shell 词法切分（运算符独立成词）。无法切分 → 抛 _UnparsableError。

    先把转义分号 ``\\;`` 换成哨兵——它是 ``find -exec`` 的参数终止符，不是命令
    分隔符；若被切成独立 ';'，``find . -exec true {} \\; -delete`` 会被误拆成两段，
    后一段的 ``-delete`` 就漏检了。
    """
    lexer = shlex.shlex(command.replace("\\;", _ESC_SEM), posix=True, punctuation_chars=True)
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
    rest = args[index:]
    # 载体的位置参数不是命令（``timeout 10 rm x`` 的 '10' 是时长）
    for _ in range(CARRIER_SKIP_POSITIONALS.get(name, 0)):
        if rest and not str(rest[0]).startswith("-"):
            rest = rest[1:]
    return rest


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
        # rsync 的 -t 是 --times（布尔开关），只有 cp/mv/install 的 -t 才是
        # --target-directory（审查 P1-1）
        flags = ("-t", "--target-directory") if name in ("cp", "mv", "install") else ("--target-directory",)
        target_dir = _flag_value(args, *flags)
        if target_dir is not None:
            return ([target_dir], not target_dir)
        if name == "ln" and "-T" in args:
            return ([positional[-1]] if positional else [], not positional)
        return (positional[-1:], len(positional) < 2)
    if name in ("rm", "rmdir", "mkdir", "touch", "tee", "truncate", "shred"):
        return (positional, False)
    if name == "patch":
        # patch 无目标文件 ⇒ 从 stdin 读补丁并改写文件（目标不可静态定位）
        return (positional, not positional)
    if name in ("chmod", "chown", "chgrp"):
        return (positional[1:], len(positional) < 2)
    if name == "sed":
        if "-i" in args or "--in-place" in args:
            return (positional[1:], len(positional) < 2)
        return ([], False)
    if name == "perl":
        # perl -i（就地编辑）改写**输入文件**；无 -i 时是解释器残余（见残余清单）
        if any(a.startswith("-i") for a in args):
            return (positional[1:], len(positional) < 2)
        return ([], False)
    if name in ("ex", "ed"):
        # ed/ex 原地编辑目标文件（命令脚本内容在 -c 里，写目标以文件为准）
        return (positional, not positional)
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
        if any(a in ("-c", "--stdout", "--to-stdout") for a in args):
            return ([], False)
        # 就地解压（-d）改写**输入文件**；压缩写的是新文件（保守按输入文件判）
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
        # 无输出选项 ⇒ wget 按 URL 派生文件名写到当前目录（文件名不可静态定位）
        return ([], True)
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
        if name in SCRIPT_LOADERS:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：脚本载入的写目标不可静态定位",
            )
        if name == "eval":
            return self._scan_eval(cmd_tokens[1:], depth)
        if name == "su":
            return self._scan_su(cmd_tokens[1:], depth)
        if name == "env":
            payload = _flag_value(cmd_tokens[1:], "-S", "--split-string")
            if payload:
                return self._scan_payload(payload, depth)
        effective, args = self._resolve_command(cmd_tokens)
        if effective is None:
            return None
        effective_name = _basename(effective[0])
        if any(marker in effective_name for marker in _IDENTITY_MARKERS):
            return CommandScopeDecision(
                False,
                "command_identity_not_literal",
                f"{effective[0]}：命令身份含展开/通配，不可静态判定",
            )
        if effective_name in SHELL_INTERPRETERS:
            decision = self._scan_interpreter(effective_name, args, depth)
            if decision is not None:
                return decision
        elif effective_name == "su":
            decision = self._scan_su(args, depth)
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
            if sub in GIT_OUTPUT_SUBCOMMANDS:
                out = _flag_value(args, "--output", "-o")
                if out:
                    ok, reason, detail = self._check_target(out)
                    if not ok:
                        return CommandScopeDecision(
                            False, reason, detail, tuple(self.unverified)
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

    def _resolve_command(self, tokens: Sequence[str]) -> tuple[list[str] | None, list[str]]:
        """解析载体前缀，返回 (有效命令 tokens, 其参数)。"""
        tokens = list(tokens)
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

    def _scan_payload(self, payload: str, depth: int) -> CommandScopeDecision | None:
        """载荷（``sh -c`` / ``su -c`` / ``env -S``）按命令串重解析。"""
        if depth + 1 > MAX_DEPTH:
            return CommandScopeDecision(False, "nesting_too_deep", "载荷嵌套过深")
        if not payload:
            return CommandScopeDecision(False, "unparsable_command", "载荷为空")
        return self.scan(payload, depth + 1)

    def _scan_su(self, args: Sequence[str], depth: int) -> CommandScopeDecision | None:
        """``su [user] -c 'cmd'``：载荷按命令串重解析；无 -c ⇒ 进入登录 shell ⇒ 拒。"""
        if "-c" not in args:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                "su：进入登录 shell，写目标不可静态定位",
            )
        index = args.index("-c")
        payload = args[index + 1] if index + 1 < len(args) else ""
        return self._scan_payload(payload, depth)

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
        # 既无 -c 也无脚本文件 ⇒ 解释器从 stdin 读脚本（``bash < x.sh``），
        # 写目标不可知 ⇒ 拒
        return CommandScopeDecision(
            False,
            "implicit_write_target",
            f"{name}：从 stdin 读脚本，写目标不可静态定位",
        )

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
                # -exec 的命令在转义分号（哨兵）处结束；哨兵之后的谓词
                # （如 -delete）仍属同一条 find，必须继续检查
                end = len(args)
                for offset in range(index + 1, len(args)):
                    if args[offset] == _ESC_SEM:
                        end = offset
                        break
                nested = args[index + 1:end]
                effective, nested_args = self._resolve_command(nested)
                if effective is None:
                    index = end + 1
                    continue
                nested_name = _basename(effective[0])
                if nested_name == "find" or nested_name == "xargs":
                    return CommandScopeDecision(
                        False, "implicit_write_target", "find -exec：写目标不可静态定位"
                    )
                if nested_name in IMPLICIT_WRITE:
                    return CommandScopeDecision(
                        False,
                        "implicit_write_target",
                        f"find -exec {nested_name}：写目标无法静态定位",
                    )
                if nested_name in WRITE_FAMILY:
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
                index = end + 1
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
