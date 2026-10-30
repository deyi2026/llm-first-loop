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
   P1-b 的已知放宽，残余清单见下方「已知残余」。
4. **读侧字面量** ⇒ 不阻断；越界记 ``scope_unverified`` 审计。scope 是写侧授权：
   把读侧封成监狱会阻断解释器与测试执行，与 P1-a 的灵活性目标冲突。
5. 只有 ``scope.declared`` 为真才生效；未受限会话行为零变化。

结构规则（第四轮独立审查 P0-1 的教训：列表式防御必然漏项）
--------------------------------------------------------
- **命令身份必须字面**：命令身份含展开/通配/花括号 ⇒ 不可静态判定 ⇒ 拒；
  载体链的**每一跳**都按这条判定。
- **载荷必须重解析**：载体（``env -S`` / ``sh -c`` / ``su -c`` / ``eval``）与
  ``find -exec`` 的**嵌套命令**都要重新走一遍完整判定，不得只查命令名
  （``find . -exec sh -c 'rm x'`` / ``sudo env -S 'rm x'`` 曾因此被漏检）。
- **选项语义按命令分别建模**：每个载体/命令各有一套选项表——``env -S`` 是载荷型、
  ``exec -a`` 是取值型、``timeout`` 的 duration 是命令前的位置参数、
  ``sudo -u`` 的值不是命令的一部分——不得共用一套通用规则。
- **写工具按动词前缀归类**：写族名单之外还有前缀规则（``rm*``/``mk*``/``unlink*``），
  逐个罗列名字必然漏项（``unlink`` 曾因此漏检）。
- **配置注入按载荷处理**：``git -c/--config-env`` 与 ``GIT_CONFIG_*`` 环境变量都能
  注入可执行配置（alias 的 shell 形态、core.pager…）⇒ 配置值必须重解析。

已知残余（显式声明，不假装已拦）
--------------------------------
- **解释器任意代码**：``python -c 'open("/outside/x","w")'``、``node -e``、
  ``perl -e 'unlink …'``、``awk '…'``、``ruby -e`` 等——受限 child 若能跑解释器，
  就能写到任意路径。这是 P1-a 相对 P1-b 的**已知放宽**（P1-b 直接剔除命令工具），
  由 ``test_interpreter_payload_is_documented_residual`` 钉住。
- **仓库内既有的 git alias**：``.git/config`` 里已定义的 alias 会在 ``git <alias>``
  时执行 shell 命令；闸能看到命令行里的 ``git -c/--config-env`` 注入向量（已拒），
  看不到**命令执行前**就已存在的仓库配置。
- **find 的 ``-exec`` 目标占位符**（``{}``）：find 会把占位符展开成真实路径，
  闸只能判到「不可静态定位」⇒ 拒。

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
        "unlink", "split", "csplit", "sponge", "mkfifo", "mknod", "mkswap",
    }
)

# 写工具按**动词前缀**归类：逐个罗列名字必然漏项（第四轮独立审查抓到
# ``unlink`` 漏检——它不在名单里就走了「按只读放行」的默认路径）。前缀规则覆盖
# 同类工具及其变体：rm/rmdir、mkdir/mkfifo/mknod/mkswap 等创建类工具、unlink。
_WRITE_NAME_PREFIXES = ("rm", "mk", "unlink")

# 输出文件型选项：这些命令**默认只读**，但带 -o/--output 时会写文件
# （``sort -o /outside/x in.txt``）——按命令各自建模，不进写族名单（否则把
# ``sort in.txt`` 这种纯读用法误判成写）。
WRITE_FLAG_OUTPUT = {"sort": ("-o", "--output"), "shuf": ("-o", "--output")}

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

# 载体（自身不写盘，但会把命令作为参数执行）——**每个载体按自己的选项语义建模**。
@dataclass(frozen=True)
class _CarrierSpec:
    """载体的选项语义——逐个建模，不共用一套通用规则。

    - ``value_options``: 取值型选项（其值是该选项的参数，**不是**命令的一部分）。
      例：``sudo -u root rm x`` 的 ``root``、``exec -a foo rm x`` 的 ``foo``、
      ``timeout -k 5 rm x`` 的 ``5``。
    - ``payload_options``: 载荷型选项（其值是**命令串**，必须按命令串重解析）。
      例：``env -S 'rm x'``（env 会拆词执行，并追加尾操作数）。
    - ``positional_prefix``: 命令之前的位置参数个数（``timeout`` 的 duration）。
    - ``sudo_like``: sudo/doas 类（shell 模式与「无命令」⇒ 进入交互 shell ⇒ 拒）。
    """

    value_options: frozenset[str] = frozenset()
    payload_options: frozenset[str] = frozenset()
    positional_prefix: int = 0
    sudo_like: bool = False


CARRIER_SPECS: dict[str, _CarrierSpec] = {
    # env：``-S/--split-string`` 的值是**命令串**，其余是普通取值选项
    "env": _CarrierSpec(
        value_options=frozenset({"-u", "--unset", "-C", "--chdir"}),
        payload_options=frozenset({"-S", "--split-string"}),
    ),
    # sudo/doas：可提权。shell 模式（-s/-i/--login）与「无命令」⇒ 进入交互 shell ⇒ 拒
    "sudo": _CarrierSpec(
        value_options=frozenset(
            {
                "-u", "--user", "-g", "--group", "-p", "--prompt", "-C", "--close-from",
                "-D", "--chdir", "-h", "--host", "-r", "--role", "-t", "--type",
                "-U", "--other-user",
            }
        ),
        sudo_like=True,
    ),
    "doas": _CarrierSpec(sudo_like=True),
    # exec：``-a NAME`` 覆盖 argv[0]（取值型）；``-c``/``-l`` 是布尔开关
    "exec": _CarrierSpec(value_options=frozenset({"-a"})),
    # timeout：选项可出现在 duration 前后（GNU getopt 置换）；duration 是命令前的位置参数
    "timeout": _CarrierSpec(
        value_options=frozenset({"-k", "--kill-after", "-s", "--signal"}),
        positional_prefix=1,
    ),
    "stdbuf": _CarrierSpec(
        value_options=frozenset({"-i", "--input", "-o", "--output", "-e", "--error"})
    ),
    "nice": _CarrierSpec(value_options=frozenset({"-n", "--adjustment"})),
    "ionice": _CarrierSpec(
        value_options=frozenset(
            {"-c", "--class", "-n", "--classdata", "-p", "--pid", "-t", "--ignore"}
        )
    ),
    "watch": _CarrierSpec(value_options=frozenset({"-n", "--interval"})),
    # time：``-o FILE`` 的值是**写目标**（不是命令的一部分）——由调用方单独判定
    "time": _CarrierSpec(value_options=frozenset({"-o", "--output"})),
    "nohup": _CarrierSpec(),
    "command": _CarrierSpec(),
    "builtin": _CarrierSpec(),
    "setsid": _CarrierSpec(),
    "busybox": _CarrierSpec(),
}

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

# 段分隔运算符（shlex 不产生 "\n"，留着是死条目——第三轮审查 P2-4）
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "|&"})

# 写重定向（含 fd 合并形式 + "<>" 读写打开——第三轮审查 P2-4）
_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
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
    """扫描不可静态判定的构造（命令替换 / 分组 / heredoc / 进程替换）。命中即返回说明。"""
    for token in tokens:
        if token == "$" or "$(" in token or "`" in token:
            return f"command_substitution: {token}"
        if token in ("(", ")", "{", "}"):
            return f"grouping_construct: {token}"
        if token in ("<<", "<<-"):
            return f"heredoc_construct: {token}"
        # 进程替换 ``<(cmd)`` / ``>(cmd)``：shlex(punctuation_chars) 会把它粘成单个
        # token，裸 "(" 匹配不到 ⇒ 里面的命令会被当普通词放过（第三轮审查 P0-1）
        if "<(" in token or ">(" in token:
            return f"process_substitution: {token}"
    return ""


def _strip_fd_prefixes(tokens: list[str]) -> list[str]:
    """去掉段首的 fd 号前缀（``2> file`` 里的 ``2``）。"""
    index = 0
    while index < len(tokens) and tokens[index].isdigit():
        index += 1
    return tokens[index:]


def _carrier_split(
    name: str, args: Sequence[str], spec: _CarrierSpec
) -> tuple[str | None, list[str], list[str]]:
    """把载体参数拆成 (载荷命令串 or None, 载荷后的尾操作数, 命令及其原始参数)。

    - 载荷型选项（``env -S 'cmd'``）的值是**命令串**：必须按命令串重解析；env 会把
      尾操作数**追加**到该命令尾部（shebang 语义），故尾操作数必须与载荷一起
      重解析（``env -S 'rm' /outside/x`` 会执行 ``rm /outside/x``）。
    - 取值型选项与其值整体跳过（值不是命令的一部分：``sudo -u root rm x`` 的
      ``root``、``exec -a foo rm x`` 的 ``foo``、``timeout -k 5 rm x`` 的 ``5``）。
    - 布尔选项单独跳过。
    - **只解析载体自己的选项**：命令及其参数**原样**交给下一层——内层命令的选项
      必须由内层命令自己的语义解析（``sudo env -S 'rm x'`` 里的 ``-S`` 是 env 的
      载荷型选项，不是 sudo 的布尔开关；按外层语义吞掉它会丢掉载荷语义）。
    - 命令之前的位置参数（``timeout`` 的 duration）被跳过。
    """
    payload: str | None = None
    trailing: list[str] = []
    args = [str(a) for a in args]
    index = 0
    positionals_seen = 0
    options_done = False
    while index < len(args):
        token = args[index]
        if not options_done:
            hit = False
            for flag in spec.payload_options:
                if token == flag:
                    payload = args[index + 1] if index + 1 < len(args) else ""
                    trailing = args[index + 2:]
                    hit = True
                    break
                if token.startswith(flag + "="):
                    payload = token.split("=", 1)[1]
                    trailing = args[index + 1:]
                    hit = True
                    break
                if len(flag) == 2 and token.startswith(flag) and len(token) > 2:
                    # 粘连形态：``-S'cmd'`` ⇒ ``-Scmd``
                    payload = token[2:]
                    trailing = args[index + 1:]
                    hit = True
                    break
            if hit:
                return payload, trailing, []
            if token == "--":
                options_done = True
                index += 1
                continue
            if token.startswith("-") and token != "-":
                if "=" in token:
                    index += 1
                    continue
                if token in spec.value_options:
                    index += 2
                    continue
                index += 1
                continue
            if name == "env" and _is_assignment(token):
                index += 1
                continue
        # 位置参数：命令之前的那几个是前导位置参数（timeout 的 duration）
        if positionals_seen < spec.positional_prefix:
            positionals_seen += 1
            index += 1
            continue
        return None, [], args[index:]
    return None, [], []


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


def _is_write_name(name: str) -> bool:
    """命令名是否是写盘工具：写族名单命中，或命中写动词前缀规则。

    名单外默认按只读处理是**放行**方向——写工具漏进名单＝漏检（第四轮独立审查
    抓到 ``unlink`` 漏检）。故除名单外还有**前缀规则**（rm*/mk*/unlink*），
    覆盖同类工具及其变体。
    """
    base = _basename(name)
    return base in WRITE_FAMILY or base.startswith(_WRITE_NAME_PREFIXES)


def _config_value(raw: str) -> str:
    """``key=value`` ⇒ ``value``（无 ``=`` 时为空——git 会拒绝这种配置）。"""
    if "=" not in raw:
        return ""
    return raw.split("=", 1)[1]


def _git_config_values(args: Sequence[str]) -> list[tuple[str, bool]]:
    """git ``-c KEY=VALUE`` / ``--config-env`` 注入的配置。

    配置值可能是**可执行载荷**：``alias.pwn='!rm /outside/x'`` 会让 ``git pwn``
    执行 shell 命令；``core.pager='rm …'`` 同理。返回
    ``[(配置值, 是否是环境变量引用)]``；``--config-env`` 的值是环境变量名，
    其内容静态不可知 ⇒ 调用方直接拒。
    """
    values: list[tuple[str, bool]] = []
    args = [str(a) for a in args]
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("-c", "--config-env"):
            if index + 1 < len(args):
                if token == "--config-env":
                    values.append((args[index + 1], True))
                else:
                    values.append((_config_value(args[index + 1]), False))
            index += 2
            continue
        if token.startswith("--config-env="):
            values.append((token.split("=", 1)[1], True))
            index += 1
            continue
        if token.startswith("-c") and len(token) > 2:
            values.append((_config_value(token[2:]), False))
            index += 1
            continue
        index += 1
    return values


# 环境变量注入：GIT_CONFIG_COUNT/KEY_*/VALUE_* 能在**不改 .git/config** 的前提下
# 注入 git alias（alias 的值以 ! 开头即 shell 命令）⇒ 写目标不可静态定位 ⇒ 拒。
_GIT_CONFIG_ENV_RE = re.compile(r"^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)$")


def _blocked_assignment(assignments: Sequence[str]) -> CommandScopeDecision | None:
    """前置环境变量赋值里有「可执行配置注入」⇒ 拒（其余赋值无害，忽略）。"""
    for assignment in assignments:
        name = str(assignment).split("=", 1)[0]
        if _GIT_CONFIG_ENV_RE.match(name):
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：git 配置注入可定义 alias，写目标不可静态定位",
            )
    return None


# sed 脚本里的 ``w FILE`` 命令（写文件）。只在命令位置（行首或 ; { } 之后）匹配，
# 避免把 ``s/w/x/`` 这类替换里的字母误判成命令。
_SED_WRITE_RE = re.compile(r"(?:^|[;{}])\s*w\s+(\S+)")


def _sed_script_write_targets(script: str) -> list[str]:
    """sed 脚本里 ``w FILE`` 命令写出的文件列表（没有则空表）。"""
    return [match for match in _SED_WRITE_RE.findall(str(script))]


def _write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """返回 (静态写目标列表, 是否存在无法静态定位的隐式写目标)."""
    positional = _non_flag_args(args)
    if name in WRITE_FLAG_OUTPUT:
        # ``sort -o FILE in`` / ``shuf -o FILE in``：输出文件就是写目标
        out = _flag_value(args, *WRITE_FLAG_OUTPUT[name])
        if out is not None:
            return ([out], not out)
        return ([], False)
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
    if name in (
        "rm", "rmdir", "mkdir", "touch", "tee", "truncate", "shred",
        # 第四轮审查补入：这些工具的写目标就是命名参数（可静态定位）
        "unlink", "mkfifo", "mknod", "mkswap",
    ):
        return (positional, False)
    if name == "patch":
        # patch 的 -o/--output 是**输出文件**（第三轮审查 P0-8）
        out = _flag_value(args, "-o", "--output")
        if out is not None:
            return ([out], not out)
        # patch 无目标文件 ⇒ 从 stdin 读补丁并改写文件（目标不可静态定位）
        return (positional, not positional)
    if name in ("chmod", "chown", "chgrp"):
        return (positional[1:], len(positional) < 2)
    if name == "sed":
        # ``-i`` / ``-i.bak`` / ``--in-place`` / ``--in-place=.bak`` 都是就地编辑
        # （第三轮审查 P0-6：只认精确 "-i" 会漏掉带后缀形态）
        if any(
            str(a) == "-i"
            or str(a).startswith("-i.")
            or str(a) == "--in-place"
            or str(a).startswith("--in-place=")
            for a in args
        ):
            return (positional[1:], len(positional) < 2)
        # sed 脚本里的 ``w FILE`` 命令会把模式空间写进 FILE（第三轮审查 P0-7）
        script_targets = _sed_script_write_targets(positional[0] if positional else "")
        if script_targets:
            return (script_targets, False)
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
        # 解包的写目标来自**归档内部路径**（不可静态定位），除非给了 -C 目录；
        # ``-x`` / ``--extract`` / ``-xf`` 等粘连形态与 tar 的**老式无横线**写法
        # （``tar xf a.tar``）都要认（第三轮审查 P0-5）
        extract = any(
            str(a) == "-x"
            or str(a) == "--extract"
            or (
                str(a).startswith("-")
                and not str(a).startswith("--")
                and "x" in str(a)[1:]
            )
            for a in args
        )
        if not extract and positional:
            first = str(positional[0])
            if (
                not first.startswith("-")
                and len(first) <= 4
                and first.isalpha()
                and "x" in first
            ):
                extract = True
        if extract:
            dest = _flag_value(args, "-C", "--directory")
            return ([dest] if dest else [], not dest)
        return (positional[:1], not positional)
    if name == "unzip":
        dest = _flag_value(args, "-d", "--directory")
        return ([dest] if dest else [], not dest)
    if name == "zip":
        return (positional[:1], not positional)
    if name in ("gzip", "xz", "bzip2", "zstd"):
        # zstd 的 -o/--output 是**输出文件**（第三轮审查 P0-9）
        out = _flag_value(args, "-o", "--output")
        if out is not None:
            return ([out], not out)
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
        assignments: list[str] = []
        while cmd_tokens and _is_assignment(cmd_tokens[0]):
            assignments.append(cmd_tokens.pop(0))
        if not cmd_tokens:
            return None
        blocked = _blocked_assignment(assignments)
        if blocked is not None:
            return blocked
        decision = self._scan_command_chain(cmd_tokens, depth)
        if decision is not None:
            return decision
        for target in write_redirects:
            ok, reason, detail = self._check_target(target)
            if not ok:
                return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        self._audit_literals(cmd_tokens + read_redirects)
        return None

    # ── 命令链判定（载体逐层剥离 ⇒ 末端命令分类）─────────────────────────

    def _scan_command_chain(
        self, cmd_tokens: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        """载体链判定：逐层剥离载体（**每个载体按自己的选项语义**），末端命令分类。

        载荷型载体（``env -S`` / ``sh -c`` / ``su -c`` / ``eval``）的载荷**按命令串
        重解析**；``find -exec`` 的嵌套命令**按命令 token 重解析**。两者都不得只查
        命令名——第四轮独立审查 P0-1：只查命令名会漏掉载荷里的写命令
        （``find . -exec sh -c 'rm x'`` / ``sudo env -S 'rm x'``）。
        """
        if not cmd_tokens:
            return None
        name = _basename(cmd_tokens[0])
        if any(marker in name for marker in _IDENTITY_MARKERS):
            return CommandScopeDecision(
                False,
                "command_identity_not_literal",
                f"{cmd_tokens[0]}：命令身份含展开/通配，不可静态判定",
            )
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
        if name == "cd" or name == "pushd":
            self.cwd_unstable = True
        if name == "eval":
            return self._scan_eval(cmd_tokens[1:], depth)
        if name == "su":
            return self._scan_su(cmd_tokens[1:], depth)
        spec = CARRIER_SPECS.get(name)
        if spec is None:
            return self._scan_leaf_command(name, cmd_tokens[1:], depth)
        payload, trailing, rest = _carrier_split(name, cmd_tokens[1:], spec)
        if payload is not None:
            joined = " ".join([payload, *trailing])
            return self._scan_payload(joined, depth)
        if spec.sudo_like:
            decision = self._scan_sudo_like(name, cmd_tokens[1:], depth)
            if decision is not None:
                return decision
        if name == "time":
            # ``time -o FILE cmd``：FILE 是**写目标**（不是命令的一部分）
            out = _flag_value(cmd_tokens[1:], "-o", "--output")
            if out:
                ok, reason, detail = self._check_target(out)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        if not rest:
            # 载体自身没有可执行的命令 ⇒ 不写盘（timeout 只给 duration 是用法错误）
            return None
        return self._scan_command_chain(rest, depth)

    def _scan_leaf_command(
        self, name: str, args: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        """末端命令分类：写族 / git / find / 解释器。"""
        if name in SHELL_INTERPRETERS:
            return self._scan_interpreter(name, args, depth)
        if name == "find":
            return self._scan_find(args, depth)
        if name == "xargs":
            return CommandScopeDecision(
                False, "implicit_write_target", "xargs：写目标来自 stdin，不可静态定位"
            )
        if name == "git":
            return self._scan_git(args, depth)
        if name in IMPLICIT_WRITE:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：写目标不可静态定位（构建/安装族）",
            )
        if _is_write_name(name) or name in WRITE_FLAG_OUTPUT:
            targets, implicit = _write_targets(name, args)
            if implicit:
                return CommandScopeDecision(
                    False, "implicit_write_target", f"{name}：写目标无法静态定位"
                )
            for target in targets:
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        return None

    def _scan_git(self, args: Sequence[str], depth: int) -> CommandScopeDecision | None:
        """git：写子命令 ⇒ 拒；``-c/--config-env`` 注入的配置值可能是可执行载荷 ⇒ 重解析。

        ``git -c alias.pwn='!rm /outside/x' pwn`` 的 alias 值是 shell 命令，
        ``-c core.pager='rm …'`` 同理——配置值必须按命令串重解析（第四轮审查 P1-4）。
        """
        for value, is_env_ref in _git_config_values(args):
            if is_env_ref:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    "git --config-env：配置值来自环境变量，写目标不可静态定位",
                )
            body = value
            if body.startswith("!"):
                # alias 的 shell 形态（``alias.pwn='!rm /outside/x'``）
                body = body[1:]
            if not body:
                continue
            decision = self._scan_payload(body, depth)
            if decision is not None and not decision.allowed:
                return decision
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
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
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

    def _scan_sudo_like(
        self, name: str, args: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        """sudo/doas：shell 模式（-s/-i/--login）或无命令 ⇒ 进入交互 shell ⇒ 拒。

        与 ``su`` 无 -c 的口径一致（第三轮审查 P1-1）：sudo-capable 主机上，
        受限 child 若能起交互 shell，写侧 scope 就整个失效。
        """
        shell_modes = {"-s", "-i", "--login", "-is", "-si", "-ii", "-ss"}
        for token in args:
            if str(token) in shell_modes:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"{name} {token}：进入交互 shell，写目标不可静态定位",
                )
        spec = CARRIER_SPECS[name]
        _payload, _trailing, rest = _carrier_split(name, args, spec)
        if not rest:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：无命令 ⇒ 进入 shell，写目标不可静态定位",
            )
        return None

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
        """``find`` 自身的删除与落盘动作（-delete / -fprint / -exec）。

        ``-exec`` 的**嵌套命令整条重解析**（含载荷：``-exec sh -c 'rm x'``）——
        只按嵌套命令的**名字**匹配写族会漏掉载荷里的写命令（第四轮独立审查 P0-1）。
        """
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
            if token in ("-exec", "-execdir", "-ok", "-okdir"):
                # -exec/-execdir/-ok/-okdir 都会执行一条命令；-ok/-okdir 只是多问
                # 一次确认（第三轮审查 P1-2）
                # -exec 的命令在转义分号（哨兵）处结束；哨兵之后的谓词
                # （如 -delete）仍属同一条 find，必须继续检查
                end = len(args)
                for offset in range(index + 1, len(args)):
                    if args[offset] == _ESC_SEM:
                        end = offset
                        break
                nested = [str(a) for a in args[index + 1:end]]
                nested_name = _basename(nested[0]) if nested else ""
                if nested_name in ("find", "xargs"):
                    return CommandScopeDecision(
                        False, "implicit_write_target", "find -exec：写目标不可静态定位"
                    )
                # 嵌套命令**整条重解析**（载荷也重解析）——第四轮审查 P0-1：
                # 旧实现只按命令名匹配 WRITE_FAMILY，``-exec sh -c 'rm x'`` 被漏检
                decision = self._scan_command_chain(nested, depth + 1)
                if decision is not None:
                    return decision
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
