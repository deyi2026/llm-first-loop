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
WRITE_FLAG_OUTPUT = {
    "sort": ("-o", "--output"),
    "shuf": ("-o", "--output"),
    # 第五轮独立审查 P2-1：编译器/链接器的 ``-o`` 指定输出文件（写目标）。
    "gcc": ("-o",),
    "g++": ("-o",),
    "cc": ("-o",),
    "c++": ("-o",),
    "clang": ("-o",),
    "clang++": ("-o",),
    "ld": ("-o",),
    "rustc": ("-o",),
}

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
        "stash", "submodule", "switch", "tag", "write-tree",
        "commit-tree", "mktree", "hash-object", "update-ref", "update-index",
        "notes", "replace", "sparse-checkout", "format-patch", "bundle",
        "config", "bisect",
        # 第四轮审查实测漏项（封闭名单必然漏项 ⇒ 补齐已知写子命令）：
        "fast-import",  # 写 .git/objects
        "update-server-info",  # 写 .git/info/
        "prune", "prune-packed",  # 改写对象库
        # 第六轮独立审查 P2-4：``reflog`` / ``fast-export`` 从写名单**移出**——
        # ``git reflog``（读当前 reflog）与 ``git fast-export``（导出到 stdout）
        # 是真只读，整族按写处理会误伤正常运维命令。
        # ``reflog`` 的写形态（``expire`` / ``delete``）由动作分族拦（见
        # ``GIT_REFLOG_READ_ACTIONS``）；``fast-export`` 的写形态由
        # ``--import-mark`` 之类的取值选项与输出路径另行判定。
        "filter-branch",  # 重写历史
    }
)

# git remote 的**写**动作（改 .git/config）——``remote`` 自身有读形态
# （``-v`` / ``show`` / ``get-url``），不能整族按写处理。
GIT_REMOTE_WRITE_ACTIONS = frozenset(
    {
        "add", "remove", "rm", "set-url", "rename", "set-head", "prune",
        "update", "set-branches",
    }
)

# git remote 的只读动作（其余动作一律按写处理，fail-closed）
GIT_REMOTE_READ_ACTIONS = frozenset({"-v", "--verbose", "show", "get-url"})

# git worktree 的只读动作（``list`` / ``list --porcelain``）——
# 第四轮审查实测 ``git worktree list`` 曾被整族按写处理而误伤。
GIT_WORKTREE_READ_ACTIONS = frozenset({"list"})

# git reflog 的动作分族（第六轮审查 P2-4）：``git reflog``（无动作）= 读当前 reflog；
# ``show`` = 读历史；``expire`` / ``delete`` = **写**（改写 reflog 文件）。
GIT_REFLOG_READ_ACTIONS = frozenset({"show"})

# git **只读**子命令（白名单）——名单外的子命令一律按写处理（fail-closed）。
# 封闭写名单会漏项（``git remote add`` / ``git fast-import`` 实测曾放行），
# 第四轮审查改为：读白名单放行 + 其余按写目标不可定位拒绝。
GIT_READ_SUBCOMMANDS = frozenset(
    {
        "status", "log", "diff", "show", "rev-parse", "rev-list", "ls-files",
        "ls-tree", "ls-remote", "cat-file", "blame", "annotate", "describe",
        "shortlog", "show-branch", "for-each-ref",
        "grep", "check-ignore", "check-attr", "check-ref-format",
        "var", "version", "help", "count-objects", "merge-base", "name-rev",
        "verify-commit", "verify-tag", "whatchanged", "diff-tree",
        "diff-index", "diff-files", "symbolic-ref", "cherry", "archive",
        "remote", "worktree",
        # 第六轮独立审查 P2-4：``reflog``（读当前 reflog）与 ``fast-export``
        # （导出对象流到 stdout）此前被整族按写处理而误伤 ⇒ 补进只读白名单；
        # ``reflog`` 的写形态（``expire`` / ``delete``）由下面的动作分族拦。
        "reflog", "fast-export", "fast-export-v2",
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
    # 会**改变工作目录**的选项（env 的 -C/--chdir、sudo 的 -D/--chdir）。
    # 这些选项换目录后，其后命令的相对写目标不能再按原 cwd 解析
    # （第五轮独立审查 P1-1）⇒ 命中即置 cwd 位移标记。
    chdir_options: frozenset[str] = frozenset()


CARRIER_SPECS: dict[str, _CarrierSpec] = {
    # env：``-S/--split-string`` 的值是**命令串**，其余是普通取值选项
    "env": _CarrierSpec(
        value_options=frozenset({"-u", "--unset", "-C", "--chdir"}),
        payload_options=frozenset({"-S", "--split-string"}),
        chdir_options=frozenset({"-C", "--chdir"}),
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
        chdir_options=frozenset({"-D", "--chdir"}),
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
    # script：``script FILE cmd…`` —— FILE 是 typescript 写目标，cmd 是被执行的命令
    "script": _CarrierSpec(
        value_options=frozenset({"-t", "--time", "-c", "--command", "-f", "--flush"}),
    ),
}

# shell 解释器（-c 载荷按命令串重解析；脚本文件写目标不可静态定位 ⇒ 拒）
SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "fish"})

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

    第六轮独立审查 P1-3：``-c`` 的 **key** 决定配置语义 —— ``alias.*`` 是
    **可执行 alias**（``alias.log='!cmd'`` 会让 ``git log`` 执行任意 shell 命令），
    其载荷的**执行时机与工作目录**不可静态确定 ⇒ 不能只按"载荷写目标是否在
    scope 内"判定（``!rm -rf ./x`` 的相对路径恰在 scope 内 ⇒ 曾被放行）。
    为此保留 key，返回 ``[(key, value, 是否环境变量引用)]``。
    """
    values: list[tuple[str, str, bool]] = []
    args = [str(a) for a in args]
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("-c", "--config-env"):
            if index + 1 < len(args):
                if token == "--config-env":
                    values.append(("", args[index + 1], True))
                else:
                    raw = args[index + 1]
                    key, _, value = raw.partition("=")
                    values.append((key, value, False))
            index += 2
            continue
        if token.startswith("--config-env="):
            values.append(("", token.split("=", 1)[1], True))
            index += 1
            continue
        if token.startswith("-c") and len(token) > 2:
            key, _, value = token[2:].partition("=")
            values.append((key, value, False))
            index += 1
            continue
        index += 1
    return values


# 环境变量注入：GIT_CONFIG_COUNT/KEY_*/VALUE_* 能在**不改 .git/config** 的前提下
# 注入 git alias（alias 的值以 ! 开头即 shell 命令）⇒ 写目标不可静态定位 ⇒ 拒。
_GIT_CONFIG_ENV_RE = re.compile(r"^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)$")


def _blocked_assignment(assignments: Sequence[str]) -> CommandScopeDecision | None:
    """环境变量赋值里有「可执行配置注入」⇒ 拒（其余赋值无害，忽略）。

    赋值来源有两处，**都要查**（第五轮独立审查 P0-1）：
    - 段首前缀赋值：``GIT_CONFIG_COUNT=1 git log``；
    - **载体携带的赋值**：``env GIT_CONFIG_COUNT=1 … git log``——``env`` 会把
      ``NAME=VALUE`` 操作数注入子进程环境，与前缀赋值等价。此前 ``env`` 形态
      被当作「跳过赋值」处理，等于漏检同一个注入向量。
    """
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


def _sed_subst_commands(script: str) -> list[tuple[str, str]]:
    """解析 sed 脚本里的 ``s`` 替换命令，返回 [(标志串, 写目标)]。

    标志串里含 ``w`` ⇒ 替换命令把模式空间写入**目标**（紧随标志的文件名）；
    含 ``e`` ⇒ 替换命令把替换文本当 shell 命令执行。

    逐字符解析而非正则：``s`` 命令的分隔符是动态的（``s|a|b|`` / ``s,a,b,``），
    正则的 ``[^\\]`` 会跨越分隔符造成误判（第四轮审查实测）。
    """
    text = str(script)
    results: list[tuple[str, str]] = []
    index = 0
    length = len(text)
    while index < length:
        # 只在命令位置识别 s（前一个非空字符须为 ; { } 或行首）
        if text[index] != "s":
            index += 1
            continue
        previous = text[:index].rstrip()
        if previous and previous[-1] not in ";{}" and not previous.endswith("\\n"):
            index += 1
            continue
        if index + 1 >= length:
            break
        delimiter = text[index + 1]
        if delimiter.isalnum() or delimiter in "\\":
            index += 1
            continue
        # 跳过 pattern（到下一个未转义分隔符）
        cursor = index + 2
        pattern_end = -1
        while cursor < length:
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == delimiter:
                pattern_end = cursor
                break
            cursor += 1
        if pattern_end < 0:
            break
        # 跳过 replacement（到下一个未转义分隔符）
        cursor = pattern_end + 1
        replacement_end = -1
        while cursor < length:
            char = text[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == delimiter:
                replacement_end = cursor
                break
            cursor += 1
        if replacement_end < 0:
            break
        # 标志段：到空白或分隔符为止
        cursor = replacement_end + 1
        flag_start = cursor
        while cursor < length and not text[cursor].isspace() and text[cursor] != delimiter:
            cursor += 1
        flags = text[flag_start:cursor]
        target = ""
        if "w" in flags:
            target = text[cursor:].strip().split()[0] if text[cursor:].strip() else ""
        results.append((flags, target))
        index = cursor
    return results


def _sed_script_write_targets(script: str) -> list[str]:
    """sed 脚本里写出的文件列表（``w FILE`` 命令 + ``s///w FILE`` 标志）。"""
    text = str(script)
    targets = list(_SED_WRITE_RE.findall(text))
    for flags, target in _sed_subst_commands(text):
        if "w" in flags and target:
            targets.append(target)
    return targets


def _sed_script_executes(script: str) -> bool:
    """sed 脚本是否含 ``s///e``（把替换文本当 shell 命令执行）。"""
    return any("e" in flags for flags, _target in _sed_subst_commands(str(script)))


# ed/ex 脚本里的 ``w FILE`` 命令（写文件）——ed 的一行一条命令。
_ED_WRITE_RE = re.compile(r"(?:^|\n)\s*w\s+(\S+)")


def _ed_script_write_targets(script: str) -> list[str]:
    """ed/ex 内联脚本里 ``w FILE`` 命令写出的文件列表（没有则空表）。"""
    return list(_ED_WRITE_RE.findall(str(script)))


def _sed_script_sources(args: Sequence[str]) -> tuple[list[str], bool]:
    """收集 sed 的脚本正文，返回 (脚本列表, 是否有脚本来自文件因而不可静态定位)。

    脚本可能来自：位置参数首位（``sed 'w /outside/x' in``）、``-e SCRIPT`` /
    ``--expression=SCRIPT``（第四轮审查实测 ``--expression=`` 曾放行）、
    ``-f FILE`` / ``--file=FILE``（脚本在文件里 ⇒ 写目标不可静态定位 ⇒ fail-closed）。
    """
    scripts: list[str] = []
    from_file = False
    positional = _non_flag_args(args)
    index = 0
    raw = [str(a) for a in args]
    while index < len(raw):
        token = raw[index]
        if token in ("-e", "--expression") and index + 1 < len(raw):
            scripts.append(raw[index + 1])
            index += 2
            continue
        if token.startswith("--expression="):
            scripts.append(token.split("=", 1)[1])
            index += 1
            continue
        if token in ("-f", "--file"):
            from_file = True
            index += 2
            continue
        if token.startswith("--file="):
            from_file = True
            index += 1
            continue
        index += 1
    if not scripts and positional:
        scripts.append(positional[0])
    return scripts, from_file


_PERL_CLUSTER_RE = re.compile(r"^-([A-Za-z]{1,3})(\..*)?$")


def _perl_inplace(args: Sequence[str]) -> bool:
    """perl 是否带就地编辑开关（``-i``）。

    perl 的短开关可**聚集**成单个 argv（``-pi`` / ``-pie`` / ``-pi.bak``），
    ``-i`` 也在其中。只认 ``startswith("-i")`` 会漏掉聚集形态
    （第五轮独立审查 P0-3：``perl -pi -e 's/a/b/' /outside/x`` 曾放行）。

    判定规则：
    - ``-i`` 精确形态；
    - ``-i.<后缀>``（``-i.bak``：就地编辑 + 备份后缀）；
    - 聚集形态 ``-<开关…>i<开关…>``，可带后缀（``-pi`` / ``-pie`` / ``-pi.bak``）。

    第六轮独立审查 P2-3 的两处修正：
    - **簇长上限 3**：perl 对 ``-version`` / ``-Mstrict`` 这类多字母 token 按
      **长选项名**处理（``perl -version`` 打印版本号），不是开关簇 ⇒ 旧口径
      （"整串都是单字母就当簇"）会把 ``-version``（含 i）误判成就地编辑。
    - **带后缀的簇**（``-pi.bak``）：旧的 ``isalpha()`` 门槛会把含 ``.`` 的簇
      整段跳过 ⇒ ``-pi.bak`` 曾被漏掉。
    """
    for token in args:
        text = str(token)
        if not text.startswith("-") or text.startswith("--"):
            continue
        match = _PERL_CLUSTER_RE.match(text)
        if match is None:
            continue
        if "i" in match.group(1):
            return True
    return False


def _tar_mode(args: Sequence[str], positional: Sequence[str], letter: str) -> bool:
    """tar 是否处于给定模式（``x``=解包 / ``c``=创建）。

    认三种形态：
    - 完整形态：``-x`` / ``--extract`` / ``-c`` / ``--create``；
    - 粘连形态：``-xf`` / ``-czf``（字母出现在短选项串里）；
    - **老式无横线写法**：``tar xf a.tar`` / ``tar cf ARCHIVE …``（首词含该字母）。
    """
    long = {"x": "--extract", "c": "--create"}[letter]
    if any(str(a) == long for a in args):
        return True
    if any(
        str(a).startswith("-")
        and not str(a).startswith("--")
        and letter in str(a)[1:]
        for a in args
    ):
        return True
    if positional:
        first = str(positional[0])
        if (
            not first.startswith("-")
            and len(first) <= 4
            and first.isalpha()
            and letter in first
            and (letter != "c" or "x" not in first)
        ):
            return True
    return False


def _tar_archive(args: Sequence[str], positional: Sequence[str]) -> str | None:
    """tar 创建模式的归档文件路径（``None``=不可静态定位）。

    认三种形态：
    - ``-f ARCHIVE`` / ``--file ARCHIVE`` / ``--file=ARCHIVE``（`_flag_value`）；
    - **粘连短选项簇**里的 ``f``（``-cvf ARCHIVE`` / ``-czf ARCHIVE``）——第六轮独立
      审查 P1-1：`_flag_value` 是 token 精确匹配，认不出粘连簇 ⇒ 回退逻辑取错操作数
      （粘连形态里 ``positional[0]`` **就是**归档），真实越界归档写被放行；
    - 老式无横线写法 ``tar cf ARCHIVE …``（首词是开关串，归档是第 2 个位置参数）。
    """
    archive = _flag_value(args, "-f", "--file")
    if archive is not None:
        return archive
    for index, token in enumerate(args):
        text = str(token)
        if not text.startswith("-") or text.startswith("--"):
            continue
        cluster = text[1:]
        if "f" not in cluster:
            continue
        # 粘连簇：``-cvf`` 末位是 f ⇒ 值取下一个 token；``-cvfARCHIVE`` 则是内嵌值
        if cluster.endswith("f"):
            if index + 1 < len(args):
                return str(args[index + 1])
            return ""
        return cluster[cluster.index("f") + 1 :]
    if len(positional) >= 2:
        first = str(positional[0])
        if (
            not first.startswith("-")
            and len(first) <= 4
            and first.isalpha()
            and "c" in first
            and "x" not in first
        ):
            return str(positional[1])
    return None


def _tar_write_targets(args: Sequence[str], positional: Sequence[str]) -> tuple[list[str], bool]:
    """tar 的写目标。

    - **解包模式**（``x``）：写目标来自**归档内部路径**（不可静态定位），除非给了
      ``-C`` 目录（第三轮审查 P0-5）；
    - **创建模式**（``c``）：写目标是**归档文件**（见 `_tar_archive`）——第五轮独立
      审查 P0-4：``tar -c --file=/outside/x.tar a`` 把归档写到 ``--file`` 指定的路径，
      此前只把位置参数当写目标 ⇒ 越界写放行；
    - 其余模式：第 1 个位置参数。
    """
    if _tar_mode(args, positional, "x"):
        dest = _flag_value(args, "-C", "--directory")
        return ([dest] if dest else [], not dest)
    if _tar_mode(args, positional, "c"):
        archive = _tar_archive(args, positional)
        if archive is not None:
            return ([archive], not archive)
        # 创建模式但归档名不可静态定位 ⇒ 拒
        return ([], True)
    return (positional[:1], not positional)


def _download_write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """curl / wget 的写目标。

    - 指定输出文件/目录 ⇒ 那是写目标；
    - ``curl -O/--remote-name/--remote-name-all`` ⇒ 按**远端名**落盘到当前目录，
      文件名不可静态定位（第五轮独立审查 P1-3：``--remote-name-all`` 曾被漏掉）；
    - wget 无输出选项 ⇒ 按 URL 派生文件名写到当前目录 ⇒ 同样不可静态定位。
    """
    if name == "curl":
        out = _flag_value(args, "-o", "--output")
        if out is not None:
            return ([out], not out)
        out_dir = _flag_value(args, "--output-dir")
        if out_dir is not None:
            return ([out_dir], not out_dir)
        if "-O" in args or "--remote-name" in args or "--remote-name-all" in args:
            return ([], True)
        return ([], False)
    out = _flag_value(args, "-O", "--output-document")
    if out is not None:
        return ([out], not out)
    out_dir = _flag_value(args, "-P", "--directory-prefix")
    if out_dir is not None:
        return ([out_dir], not out_dir)
    return ([], True)


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
        # rsync 的 -t 是 --times（布尔开关），只有 cp/mv/install/ln 的 -t 才是
        # --target-directory（审查 P1-1；第五轮审查 P1-2 补入 ln：
        # ``ln -t DIR`` 把链接建到 DIR 下，原口径漏掉 -t ⇒ 取了错误的写目标）
        flags = ("-t", "--target-directory") if name in ("cp", "mv", "install", "ln") else ("--target-directory",)
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
        # 第四轮审查：脚本来源扩到 ``-e`` / ``--expression=`` / ``-f`` 三种形态，
        # 并新增 ``s///w FILE`` 与 ``s///e`` 两个变体。
        scripts, from_file = _sed_script_sources(args)
        script_targets: list[str] = []
        for script in scripts:
            script_targets.extend(_sed_script_write_targets(script))
            if _sed_script_executes(script):
                # ``s///e`` 把替换文本当 shell 命令执行 ⇒ 写目标不可静态定位
                return ([], True)
        if from_file:
            # ``-f FILE``：脚本正文在文件里 ⇒ 无法静态定位写目标 ⇒ fail-closed
            return ([], True)
        if script_targets:
            return (script_targets, False)
        return ([], False)
    if name == "perl":
        # perl -i（就地编辑）改写**输入文件**；无 -i 时是解释器残余（见残余清单）。
        # 第五轮独立审查 P0-3：``-i`` 可与其它开关**聚集**（``-pi`` / ``-pie`` /
        # ``-i.bak``）——只认 ``startswith("-i")`` 会漏掉 ``perl -pi -e …``。
        if _perl_inplace(args):
            return (positional[1:], len(positional) < 2)
        return ([], False)
    if name in ("ex", "ed"):
        # ed/ex 的命令脚本来自 ``-c SCRIPT``（内联）或 **stdin**。
        # 内联脚本：解析其中的 ``w FILE`` 写目标；
        # stdin 脚本：写目标不可静态定位 ⇒ fail-closed
        # （第四轮审查实测 ``ed`` 会把模式空间落盘）。
        scripts: list[str] = []
        raw = [str(a) for a in args]
        index = 0
        while index < len(raw):
            token = raw[index]
            if token in ("-c", "--command") and index + 1 < len(raw):
                scripts.append(raw[index + 1])
                index += 2
                continue
            index += 1
        script_targets: list[str] = []
        for script in scripts:
            script_targets.extend(_ed_script_write_targets(script))
        edited = [a for a in _non_flag_args(args) if a not in scripts]
        if script_targets:
            return (script_targets + edited, False)
        if not scripts:
            # 脚本来自 stdin ⇒ 写目标不可静态定位（fail-closed）。
            # 被编辑文件是**已知路径**，调用方先按已知目标判定（给精确理由），
            # 目标合规后再由 implicit 兜底拒绝。
            return (edited, True)
        return (edited, False)
    if name == "dd":
        outputs = [a.split("=", 1)[1] for a in args if a.startswith("of=")]
        return (outputs, not outputs)
    if name == "tar":
        return _tar_write_targets(args, positional)
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
    if name in ("curl", "wget"):
        return _download_write_targets(name, args)
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
            # 纯写重定向段（``> FILE`` / ``2> FILE`` / ``&> FILE`` …）没有命令词，
            # 但**照样写盘**——写目标必须照样校验（第四轮实测：`> /outside/f` 曾放行）。
            if assignments and _blocked_assignment(assignments) is not None:
                return _blocked_assignment(assignments)
            for target in write_redirects:
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
            self._audit_literals(read_redirects)
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
        if spec.chdir_options:
            # 第五轮独立审查 P1-1：``env -C DIR`` / ``sudo -D DIR`` 会改变工作目录，
            # 其后命令的相对写目标不能再按原 cwd 解析（原口径按原 cwd 判定 ⇒
            # ``env -C /outside touch x`` 把 ``/outside/x`` 误判为工作区内相对路径）。
            # 第六轮独立审查 P2-1：只看**载体自身选项区**（命令名之前）——
            # 整段扫描会把内层命令的同名选项误认（``env grep -C 2 pat`` 的 ``-C``
            # 是 grep 的上下文行数，不是 env 的 chdir）。
            carrier_args = [str(a) for a in cmd_tokens[1:]]
            option_zone = carrier_args[: len(carrier_args) - len(rest)] if rest else carrier_args
            if any(a in spec.chdir_options for a in option_zone):
                self.cwd_unstable = True
        if name == "env":
            # 第五轮独立审查 P0-1：``env NAME=VALUE cmd`` 会把赋值注入子进程环境，
            # 与段首前缀赋值等价（``GIT_CONFIG_*`` 能注入可执行 alias）。
            # ``_carrier_split`` 跳过 env 的赋值操作数 ⇒ 必须在**跳过前**取回它们。
            # 第六轮独立审查 P2-2：只看**载体自身选项区**（命令名之前）的赋值 ——
            # 整段扫描会把内层命令的操作数误认成注入（``env ls GIT_CONFIG_COUNT=1``
            # 里那是 ls 的参数，不是 env 的环境变量赋值）。
            carrier_args = [str(a) for a in cmd_tokens[1:]]
            option_zone = carrier_args[: len(carrier_args) - len(rest)] if rest else carrier_args
            carried = [a for a in option_zone if _is_assignment(a)]
            blocked = _blocked_assignment(carried)
            if blocked is not None:
                return blocked
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
        if name == "script":
            # 第五轮独立审查 P2-1：``script FILE cmd…``（BSD/GNU script）把会话
            # 录制**写入 FILE**，同时执行 cmd ⇒ 两处都是写面：
            #   - FILE 是可定位的写目标（须过 scope 判定）；
            #   - cmd 是被执行的命令（须按命令链重解析）。
            # 第六轮独立审查 P1-2：载荷有两种形态 ——
            #   (a) ``script -c CMD [FILE]``：CMD 由**选项**携带；
            #   (b) ``script FILE cmd…``：cmd 是 FILE 之后的位置参数。
            # 此前只按 (b) 取 cmd_tokens[2:] ⇒ (a) 形态下 CMD 被整体漏扫。
            payload_cmd = _flag_value(cmd_tokens[1:], "-c", "--command")
            if payload_cmd is not None:
                return self._scan_command_chain(shlex.split(payload_cmd), depth)
            positionals = [str(a) for a in _non_flag_args(cmd_tokens[1:])]
            if positionals:
                ok, reason, detail = self._check_target(positionals[0])
                if not ok:
                    return CommandScopeDecision(
                        False, reason, detail, tuple(self.unverified)
                    )
            return self._scan_command_chain(cmd_tokens[2:], depth)
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
            # 判定顺序：**先查已知写目标**（能给精确理由：越界/不在允许清单），
            # 全部合规后才用 implicit 兜底（写目标确实不可静态定位）。
            # 第四轮审查实测：``ed /outside/x.py`` 曾因先判 implicit 而丢掉精确理由。
            for target in targets:
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
            if implicit:
                return CommandScopeDecision(
                    False, "implicit_write_target", f"{name}：写目标无法静态定位"
                )
        return None

    def _scan_git(self, args: Sequence[str], depth: int) -> CommandScopeDecision | None:
        """git：写子命令 ⇒ 拒；``-c/--config-env`` 注入的配置值可能是可执行载荷 ⇒ 重解析。

        ``git -c alias.pwn='!rm /outside/x' pwn`` 的 alias 值是 shell 命令，
        ``-c core.pager='rm …'`` 同理——配置值必须按命令串重解析（第四轮审查 P1-4）。
        """
        for key, value, is_env_ref in _git_config_values(args):
            if is_env_ref:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    "git --config-env：配置值来自环境变量，写目标不可静态定位",
                )
            # 第六轮独立审查 P1-3：``alias.*`` 是**可执行 alias** ——
            # ``alias.log='!cmd'`` 让任意读子命令（log/status/…）执行 shell 命令，
            # 其执行时机与工作目录不可静态确定 ⇒ 一律拒（不论载荷写目标是否在 scope 内）。
            # ``core.pager`` 同属可执行载荷（``core.pager='sh -c "rm -rf ./x"'``
            # 会在每次分页时执行）⇒ 同样拒（第六轮审查 P1-3 补充实测）。
            if key.lower().startswith("alias.") or key.lower() == "core.pager":
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git -c {key}=…：注入可执行载荷，写目标不可静态定位",
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
        if sub not in GIT_READ_SUBCOMMANDS:
            # 第四轮审查：封闭写名单必然漏项（``git remote add`` / ``git
            # fast-import`` 实测曾放行）⇒ 改为读白名单放行、其余按写处理。
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"git {sub}：子命令不在只读白名单内，写目标不可静态定位",
            )
        if sub == "symbolic-ref":
            # 第五轮独立审查 P1-4：``symbolic-ref`` 在读白名单里，但
            # ``git symbolic-ref HEAD refs/heads/x`` 是**写形态**（改写 .git/HEAD）。
            # 读形态只有 1 个位置参数（``git symbolic-ref HEAD``）；写形态是
            # 「名字 + 新值」2 个位置参数，或带 ``--delete``/``-d``。
            actions = [str(a) for a in _non_flag_args(args[1:])]
            if "--delete" in args or "-d" in args or len(actions) >= 2:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git symbolic-ref {actions[0] if actions else ''}：写形态改写 .git/HEAD，写目标不可静态定位",
                )
        if sub == "reflog":
            # 第六轮独立审查 P2-4：``git reflog``（无动作）/ ``git reflog show`` 是读；
            # ``expire`` / ``delete`` 改写 reflog 文件 ⇒ 写形态按写目标不可定位拒。
            actions = [str(a) for a in _non_flag_args(args[1:])]
            if actions and not any(a in GIT_REFLOG_READ_ACTIONS for a in actions):
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git reflog {actions[0]}：写目标不可静态定位",
                )
        if sub == "remote":
            # ``git remote`` 有读形态（-v / show / get-url）与写形态
            # （add / set-url / remove …）——按动作分族，名单外按写处理。
            actions = [str(a) for a in _non_flag_args(args[1:])]
            read_forms = [a for a in actions if a in GIT_REMOTE_READ_ACTIONS]
            write_forms = [a for a in actions if a in GIT_REMOTE_WRITE_ACTIONS]
            if write_forms:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git remote {write_forms[0]}：写目标不可静态定位",
                )
            if not read_forms and actions:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git remote {actions[0]}：动作未列入只读白名单，写目标不可静态定位",
                )
        if sub == "worktree":
            # ``git worktree list`` 是只读形态；``add`` / ``remove`` / ``prune``
            # 会写工作树 ⇒ 名单外动作按写处理。
            actions = [str(a) for a in _non_flag_args(args[1:])]
            read_forms = [a for a in actions if a in GIT_WORKTREE_READ_ACTIONS]
            if not read_forms:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git worktree {actions[0] if actions else ''}：写目标不可静态定位",
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
            if token in ("-fprint", "-fprintf", "-fls", "-fprint0"):
                # 第五轮独立审查 P0-2：``-fprint0`` 与 ``-fprint`` 同族（落盘），
                # 此前只认 ``-fprint/-fprintf/-fls`` ⇒ ``find . -fprint0 /outside/x`` 放行。
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
