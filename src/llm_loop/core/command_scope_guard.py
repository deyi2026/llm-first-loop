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

from llm_loop.core.command_options import (
    COMPRESS_OUTPUT_OPTIONS,
    CURL_OPTIONS,
    GIT_EXPORT_OPTIONS,
    GIT_OUTPUT_OPTIONS,
    PATCH_OPTIONS,
    PERL_OPTIONS,
    SCRIPT_OPTIONS,
    SED_OPTIONS,
    SHUF_OUTPUT_OPTIONS,
    SORT_OUTPUT_OPTIONS,
    TAR_OPTIONS,
    TARGET_DIRECTORY_OPTIONS,
    TIME_OPTIONS,
    UNZIP_OPTIONS,
    WGET_OPTIONS,
    scan_options,
)
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

# 输出文件型选项：这些命令**默认只读**，但带 -o/--output（或编译器默认产物）时写文件
# （``sort -o /outside/x in.txt`` / ``gcc a.c``）——不进写族名单（否则把纯读用法
# 误判成写）。第九轮（push 闸）P1-2：取值改走族模型（附着形态 ``-o/x``、
# ``--target-directory=/x`` 不再漏），编译器另有专用的产物判定。
OUTPUT_FLAG_COMMANDS = frozenset(
    {
        "sort", "shuf",
        "gcc", "g++", "cc", "c++", "clang", "clang++", "ld", "rustc",
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
# 第十一轮独立审查 P2-3：``-v/--verbose`` 两项是**死条目**——``_git_action_args``
# 只取位置动作（选项被剥离）⇒ ``git remote -v`` 走的是「无动作 ⇒ 不拦」分支
# ⇒ 名单里的 ``-v/--verbose`` 永远命中不到 ⇒ 删掉（留着会让人误以为
# ``git remote -v`` 是靠这份白名单放行的）。
GIT_REMOTE_READ_ACTIONS = frozenset({"show", "get-url"})

# git worktree 的只读动作（``list`` / ``list --porcelain``）——
# 第四轮审查实测 ``git worktree list`` 曾被整族按写处理而误伤。
GIT_WORKTREE_READ_ACTIONS = frozenset({"list"})

# git reflog 的动作分族（第六轮审查 P2-4）：``git reflog``（无动作）= 读当前 reflog；
# ``show`` = 读历史；``expire`` / ``delete`` = **写**（改写 reflog 文件）。
GIT_REFLOG_READ_ACTIONS = frozenset({"show"})

# git 配置里**值会被当命令/脚本执行或重指执行路径**的键（第九轮 push 闸 P2-1
# 扩集；精确匹配防前缀撞名）。``alias.*`` 前缀另行单独判定。
_GIT_EXEC_CONFIG_KEYS = frozenset(
    {
        "core.pager",
        "core.editor",
        "core.hookspath",
        "core.attributesfile",
        "core.excludesfile",
        "core.pager.command",
        "sequence.editor",
        "diff.external",
        "difftool.path",
        "mergetool.path",
    }
)
# 第十二轮 push 闸 P1-2：**前缀族**可执行配置键——``pager.<sub>``（每子命令
# 分页器，``git -c pager.log='touch /outside/pwn' --pager log`` 单步越界写）、
# ``filter.<drv>.clean/smudge/process``（过滤驱动经 shell 执行）、
# ``diff.<drv>.textconv``（转换命令）、``merge.<drv>.driver``（合并驱动）。
# 与 ``alias.*`` 同理：值被执行 ⇒ 按前缀拦。
_GIT_EXEC_CONFIG_PREFIXES = ("pager.", "gpg.program", "core.sshcommand")
_GIT_EXEC_CONFIG_SUFFIX_RULES = (
    ("diff.", ".textconv"),
    ("merge.", ".driver"),
)
_GIT_FILTER_EXEC_SUFFIXES = frozenset({"clean", "smudge", "process", "command"})


def _git_exec_config_key(lowered: str) -> bool:
    """配置键是否可执行（精确闭集 + 前缀族）。"""
    if lowered in _GIT_EXEC_CONFIG_KEYS:
        return True
    if lowered.startswith("alias.") or lowered.startswith(_GIT_EXEC_CONFIG_PREFIXES):
        return True
    if lowered.startswith("filter."):
        return lowered.rsplit(".", 1)[-1] in _GIT_FILTER_EXEC_SUFFIXES
    for prefix, suffix in _GIT_EXEC_CONFIG_SUFFIX_RULES:
        if lowered.startswith(prefix) and lowered.endswith(suffix):
            return True
    return False

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
        # 第十轮独立审查 P2-4：``-f/--flush`` 是**开关**（不是取值型）——旧表把它
        # 列进 value_options ⇒ ``script -f out.txt cmd`` 会把 ``out.txt`` 当成
        # ``-f`` 的值跳过 ⇒ typescript 写目标漏判 ⇒ 与 SCRIPT_OPTIONS 的
        # ``("--flush", False)`` 自相矛盾。⇒ 对齐 SCRIPT_OPTIONS。
        value_options=frozenset({"-t", "--time", "-c", "--command"}),
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


def _carrier_value_option_hit(token: str, value_options: frozenset[str]) -> bool:
    """载体**取值型选项**命中判定（第十二轮 push 闸 P1-2 补充）。

    ``_carrier_split`` 用它决定是否消费下一个 token 作为选项值——必须与
    ``_is_chdir_option`` 同样支持前缀缩写/粘连形态，否则 ``env --ch /outside …``
    的值被漏消费、沦为载荷命令名，chdir 检测随之落空。
    """
    for option in value_options:
        if token == option or token.startswith(option + "="):
            return True
        if len(option) == 2 and token.startswith(option) and len(token) > 2:
            return True
        if option.startswith("--") and option.startswith(token) and len(token) >= 4:
            # getopt_long 唯一前缀缩写（如 ``--ch`` → ``--chdir``）
            return True
    return False


def _short_cluster_value_option(
    token: str, value_options: frozenset[str], payload_options: frozenset[str]
) -> tuple[int, str, bool]:
    """短选项**簇**里第一个取值型选项的位置、选项名与取值位置。

    GNU getopt 语义：短选项可组合（``-iC`` = ``-i`` + ``-C``），按字符从左到右
    解析；遇到**第一个**取值型选项即停（其后的字符不再当作选项解析）——其值为
    该选项之后的余串（余串非空 ⇒ 值内联在 token 内）或**下一个 argv**。

    返回 ``(字符索引, 选项名, 值内联)``；未命中返回 ``(-1, "", False)``。

    第十三轮（两线并集后实测缺口）：此前只认「token 以该短选项开头」⇒ 组合形态
    ``env -iC /outside rm /etc/x`` 的 ``-iC`` 不命中 ⇒ ``/outside`` 未被消费 ⇒
    被当成载荷命令名 ⇒ 真正的载荷 ``rm /etc/x`` **从未进入分析** ⇒ 越界写放行。
    同类形态：``env -iS 'rm /etc/x'``、``sudo -nD /outside rm /etc/x``。
    """
    if not token.startswith("-") or token.startswith("--") or len(token) < 3:
        return (-1, "", False)
    candidates = value_options | payload_options
    body = token[1:]
    for index, char in enumerate(body):
        flag = "-" + char
        if flag in candidates:
            return (index, flag, bool(body[index + 1:]))
    return (-1, "", False)


def _is_chdir_option(token: str, spec: _CarrierSpec) -> bool:
    """判定 token 是否是**改变工作目录**的载体选项（含组合短选项形态）。

    第七轮独立审查后补（自审发现）：旧实现只做**精确匹配** ⇒
    ``env --chdir=/outside touch x`` 的 cwd 变化未被识别 ⇒ 相对写目标 ``x``
    仍按原 cwd 判定为工作区内 ⇒ **越界写放行**。⇒ 补齐 ``--opt=DIR``
    与短选项粘连形态（``-C/outside``），按 fail-closed 处理。

    第十二轮独立审查 P1-2：getopt_long 接受**唯一前缀缩写** ⇒ ``env --ch
    /outside``（→ --chdir）、``sudo --chd /outside``（→ --chdir）此前不被
    识别 ⇒ cwd 变化未标记 ⇒ 后续相对写目标仍按原 cwd 判定 ⇒ 越界写放行。
    多个候选前缀时仍算命中（fail-closed）。

    第十三轮：组合短选项形态 ``env -iC /outside ...``（= ``-i`` + ``-C``）此前
    同样不被识别 ⇒ 同样的越界写放行。⇒ 只认「簇内**第一个**取值型选项」——
    ``env -uC ...`` 里 ``-u`` 先吃掉 ``C``（``-C`` 从未生效）⇒ 不得误判 chdir。
    """
    options = spec.chdir_options
    for option in options:
        if token == option:
            return True
        if token.startswith(option + "="):
            return True
        if len(option) == 2 and token.startswith(option) and len(token) > 2:
            return True
    for option in options:
        if option.startswith("--") and token.startswith("--") and option.startswith(token):
            return True
    cluster_pos, cluster_flag, _cluster_inline = _short_cluster_value_option(
        token, spec.value_options, spec.payload_options
    )
    if cluster_pos > 0 and cluster_flag in options:
        return True
    return False


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
            # 第十三轮：组合短选项簇（getopt 语义）——``-iC`` = ``-i`` + ``-C``、
            # ``-iS`` = ``-i`` + ``-S``。取值型选项在簇内**非首位**时，其值取
            # **下一个 argv**（余串为空）；余串非空（``-iC/outside``）⇒ 值内联。
            # 此前这类 token 不命中任何取值判定 ⇒ 其值未被消费 ⇒ 被当成载荷命令名
            # ⇒ 真正的载荷命令**从未进入分析** ⇒ 越界写放行（第十三轮实测）。
            cluster_pos, cluster_flag, cluster_inline = _short_cluster_value_option(
                token, spec.value_options, spec.payload_options
            )
            if cluster_pos > 0:
                if cluster_flag in spec.payload_options:
                    # 载荷型：``env -iS 'rm /etc/x'`` ⇒ 值取下一个 argv；
                    # ``env -iSrm /etc/x`` ⇒ 余串内联（``rm`` 是命令串）。
                    if cluster_inline:
                        payload = token[2 + cluster_pos:]
                        trailing = args[index + 1:]
                    else:
                        payload = args[index + 1] if index + 1 < len(args) else ""
                        trailing = args[index + 2:]
                    return payload, trailing, []
                # 取值型（非载荷）：消费下一个 token 作为选项值。
                if cluster_inline:
                    index += 1
                else:
                    index += 2
                continue
            if token == "--":
                options_done = True
                index += 1
                continue
            if token.startswith("-") and token != "-":
                if "=" in token:
                    index += 1
                    continue
                # 第十二轮 push 闸 P1-2（载体值选项缩写）：``env --ch /outside touch x``
                # 里 ``--ch`` 是 ``--chdir`` 的唯一前缀缩写——精确匹配会**漏消费**
                # ``/outside`` ⇒ 它被当成载荷命令名 ⇒ chdir 检测落空 ⇒ 放行。
                if _carrier_value_option_hit(token, spec.value_options):
                    # 分离形态吃下一个 token；粘连/内联（``-C/outside``、
                    # ``--chdir=/x``）值在 token 内，只吃本 token——多吃会把
                    # 载荷命令吞成"选项值"（第十二轮回归修复）。
                    if "=" in token or (len(token) > 2 and token[1] != "-"):
                        index += 1
                    else:
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


def _copy_move_targets(
    name: str, args: Sequence[str], positional: Sequence[str]
) -> tuple[list[str], bool]:
    """cp/mv/install/ln/rsync 的写目标：目标目录 → 备份目录 → 末位操作数。

    rsync 的 ``-t`` 是 ``--times``（布尔开关），只有 cp/mv/install/ln 的 ``-t``
    才是 ``--target-directory``（审查 P1-1；第五轮审查 P1-2 补入 ln：
    ``ln -t DIR`` 把链接建到 DIR 下，原口径漏掉 -t ⇒ 取了错误的写目标）。
    第九轮 P1-2：``-t/outside`` 附着与 ``--target-directory=/outside`` 内联形态
    改走族模型；``ln -T`` 的目标目录取末位操作数。
    """
    if name == "rsync":
        target_dir = _flag_value(args, "--target-directory")
        backup_dir = _flag_value(args, "--backup-dir")
        if backup_dir is not None:
            # 备份目录与目标操作数（dst）**都要判定**（口径见
            # ``_rsync_backup_targets``）。
            return _rsync_backup_targets(backup_dir, target_dir, positional)
    else:
        scan = scan_options(TARGET_DIRECTORY_OPTIONS, args)
        if scan.unresolved:
            return ([], True)
        target_dir = scan.value_of("-t", "--target-directory")
    if target_dir is not None:
        return ([target_dir], not target_dir)
    if name == "ln" and "-T" in args:
        return ([positional[-1]] if positional else [], not positional)
    return (positional[-1:], len(positional) < 2)


def _rsync_backup_targets(
    backup_dir: str, target_dir: str | None, positional: Sequence[str]
) -> tuple[list[str], bool]:
    """rsync ``--backup-dir=DIR`` 的写目标：备份目录 **+** 目标操作数（dst）。

    第十四轮 P0：``--backup-dir=DIR`` 让 rsync 把**被覆盖的旧文件**备份到 DIR
    ⇒ DIR 也是写目标（此前完全没被建模 ⇒ ``rsync -b --backup-dir=/outside/b src
    dst`` 越界写放行）。
    独立审查 P2-2：备份目录**不替代**目标操作数（dst）⇒ 两者都要判定（早退只回
    备份目录会让 ``rsync -b --backup-dir=bk src /outside/dst`` 的越界目标漏判）；
    dst 缺失时仍是隐式写 ⇒ fail-closed。
    """
    targets = [backup_dir]
    if target_dir is not None:
        targets.append(target_dir)
    dst = positional[-1:] if positional else []
    return (targets + dst, not dst)


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
# 第九轮 P1-4：``GIT_CONFIG_PARAMETERS`` 与 COUNT/KEY_*/VALUE_* 等价——它是一串
# 空格分隔的 ``key=value`` 内联配置，git 按它注入配置 ⇒ ``alias.x='!cmd'``
# 同样可执行 ⇒ 与其它三种形态一并拦。
# 会把赋值注入环境的 shell 内建（第十二轮 push 闸 P1-3）：``export``/``declare``/
# ``local``/``readonly``/``setenv`` 的 ``NAME=value`` 操作数与段首前缀赋值等价。
_SHELL_EXPORT_BUILTINS = frozenset({"export", "declare", "local", "readonly", "setenv"})

_GIT_CONFIG_ENV_RE = re.compile(r"^GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+|PARAMETERS)$")
# 第十二轮 push 闸 P1-1：**执行型 git 环境变量**——git 会把这些值经 shell 执行，
# 与 alias 注入同通道（``GIT_EXTERNAL_DIFF='touch /outside/pwn' git diff`` 在
# 只读白名单子命令上即可越界写）。值不含元字符 ⇒ 元字符兜底扫不出 ⇒ 必须按
# **变量名**拦。
_GIT_EXEC_ENV_RE = re.compile(
    r"^GIT_(EXTERNAL_DIFF|PAGER|EDITOR|SSH_COMMAND|ASKPASS)$"
)


def _blocked_assignment(assignments: Sequence[str]) -> CommandScopeDecision | None:
    """环境变量赋值里有「可执行配置注入」⇒ 拒（其余赋值无害，忽略）。

    赋值来源有两处，**都要查**（第五轮独立审查 P0-1）：
    - 段首前缀赋值：``GIT_CONFIG_COUNT=1 git log``；
    - **载体携带的赋值**：``env GIT_CONFIG_COUNT=1 … git log``——``env`` 会把
      ``NAME=VALUE`` 操作数注入子进程环境，与前缀赋值等价。此前 ``env`` 形态
      被当作「跳过赋值」处理，等于漏检同一个注入向量。
    - 第十二轮 P1-1：执行型环境变量（``GIT_EXTERNAL_DIFF``/``GIT_PAGER``/
      ``GIT_EDITOR``/``GIT_SSH_COMMAND``/``GIT_ASKPASS``）单独成类——它们不
      走 ``-c`` 配置通道，但效果等同可执行配置。
    """
    for assignment in assignments:
        name = str(assignment).split("=", 1)[0]
        if _GIT_CONFIG_ENV_RE.match(name):
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：git 配置注入可定义 alias，写目标不可静态定位",
            )
        if _GIT_EXEC_ENV_RE.match(name):
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                f"{name}：git 执行型环境变量（值经 shell 执行），写目标不可静态定位",
            )
    return None


# sed 命令位置扫描（第九轮 push 闸 P1-1）：``s``/``w``/``e`` 前面可以带
# **地址前缀**（``/re/``、``\d+``、``$``、``\c``、``\re\``，可组成 ``a,b`` 范围、
# ``first~step``、``addr!`` 取反），也能跟在换行分隔的命令之后——旧实现只认
# ``;{}``/行首紧跟命令字符 ⇒ ``2s/a/b/w /outside/x``、``sed '/re/w /outside/x'``
# 这类带地址写命令整体漏检 ⇒ 越界写放行。改为逐字符扫命令位置 + 消费地址前缀。
_SED_COMMAND_SEPARATORS = ";{}\n"
# 无参数单字母命令（第十轮 push 闸 P2-4：GNU sed 允许其后**紧邻**下一条命令
# ——``sed 'pw /outside/x' in`` 里 ``p`` 之后直接是 ``w``，无任何分隔符；BSD
# sed 拒绝该形态〔本机实测〕，守卫按 GNU 宽语义保守覆盖）。``l`` 在 GNU 可带
# 可选文件参数（``l /outside/x`` 把清单写入文件），不入此列——按写目标提取。
_SED_NO_ARG_COMMANDS = frozenset("pndDgGhHPqx=")


def _sed_skip_one_address(text: str, start: int) -> int:
    """从 ``start`` 起消费一个 sed 地址，返回消费后的下标（无地址则原样返回）."""
    length = len(text)
    if start >= length:
        return start
    char = text[start]
    if char == "$":
        return start + 1
    if char.isdigit():
        cursor = start
        while cursor < length and text[cursor].isdigit():
            cursor += 1
        return cursor
    if char == "\\":
        # ``\c``（GNU 单字符地址）或 ``\regex\``（定界正则）
        if start + 1 < length and text[start + 1].isalpha():
            return start + 2
        if start + 1 >= length:
            return start
        delimiter = text[start + 1]
        cursor = start + 2
        while cursor < length:
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == delimiter:
                return cursor + 1
            cursor += 1
        return start  # 未闭合 ⇒ 不当地址
    if char == "/":
        cursor = start + 1
        while cursor < length:
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == "/":
                return cursor + 1
            cursor += 1
        return start
    return start


def _sed_command_start_positions(text: str) -> list[int]:
    """返回 sed 脚本中**命令字符**的候选起始下标（地址前缀已被消费）."""
    positions: list[int] = []
    index = 0
    length = len(text)
    boundary = True  # 脚本开头即命令位置
    while index < length:
        char = text[index]
        if char in _SED_COMMAND_SEPARATORS:
            boundary = True
            index += 1
            continue
        if char in " \t":
            index += 1
            continue
        if boundary:
            cursor = _sed_skip_one_address(text, index)
            if cursor == index and not char.isalpha():
                boundary = False
                index += 1
                continue
            # 范围地址 ``a,b`` 与 GNU ``first~step``
            if cursor > index and cursor < length and text[cursor] == ",":
                second = _sed_skip_one_address(text, cursor + 1)
                if second > cursor + 1:
                    cursor = second
            if cursor < length and text[cursor] == "~":
                step = cursor + 1
                while step < length and text[step].isdigit():
                    step += 1
                if step > cursor + 1:
                    cursor = step
            if cursor < length and text[cursor] == "!":
                cursor += 1
            while cursor < length and text[cursor] in " \t":
                cursor += 1
            positions.append(cursor)
            # GNU sed：无参数单字母命令之后可以**紧邻**下一条命令（无分隔符）
            # ——``pw FILE`` / ``nw FILE`` / ``pd``。命令位置后保持 boundary。
            boundary = cursor < length and text[cursor] in _SED_NO_ARG_COMMANDS
            index = cursor + 1 if boundary else cursor
            continue
        index += 1
    return positions


def _sed_subst_commands(script: str) -> list[tuple[str, str]]:
    """解析 sed 脚本里的 ``s`` 替换命令，返回 [(标志串, 写目标)]。

    标志串里含 ``w`` ⇒ 替换命令把模式空间写入**目标**（紧随标志的文件名）；
    含 ``e`` ⇒ 替换命令把替换文本当 shell 命令执行。

    逐字符解析而非正则：``s`` 命令的分隔符是动态的（``s|a|b|`` / ``s,a,b,``），
    正则的 ``[^\\]`` 会跨越分隔符造成误判（第四轮审查实测）。命令位置（含地址
    前缀消费）由 `_sed_command_start_positions` 统一给出（第九轮 P1-1）。
    """
    text = str(script)
    results: list[tuple[str, str]] = []
    length = len(text)
    # 命令位置来自统一扫描器（地址前缀/换行分隔都被消费）——第九轮 P1-1：
    # ``2s/a/b/w F``、``sed '/re/s/a/b/w F'`` 不再因"前一个字符不是 ;{}"漏检。
    starts = {position for position in _sed_command_start_positions(text) if position < length}
    index = 0
    while index < length:
        # 只在命令位置识别 s
        if text[index] != "s" or index not in starts:
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
            # 第九轮 P1-2：未闭合的 ``s``（分隔符没配对）此前 ``break`` ⇒ 脚本
            # **后半段整体不再扫描** ⇒ 其后的 ``w FILE`` / ``e CMD`` 漏检 ⇒
            # 改为继续扫（fail-closed 方向）。
            index += 1
            continue
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
            # 第九轮 P1-2：同上——未闭合的 ``s`` 不再中断整段扫描。
            index += 1
            continue
        # 标志段：只吃 sed 替换命令的真实标志字符（``g`` / ``p`` / 次数数字 /
        # ``w FILE`` / ``e`` / ``i`` / ``I`` / ``M`` / ``m``）——``;`` 之类字符是
        # **下一条命令**的分隔符，不属于本命令的标志（第七轮审查 P2-2：旧实现扫到
        # 空白/分隔符为止 ⇒ ``s/a/b/g; x`` 的标志被读成 ``g;``，``;w`` / ``;e``
        # 会被误算进同一条 s 命令）。
        cursor = replacement_end + 1
        flag_start = cursor
        target = ""
        while cursor < length:
            char = text[cursor]
            if char.isdigit() or char in "gpwneimIM":
                if char == "w":
                    # ``w FILE``：文件名紧随其后（空白分隔，或 ``;`` 之前）
                    rest = text[cursor + 1 :].lstrip()
                    if rest.startswith(";"):
                        rest = rest[1:].lstrip()
                    target = rest.split()[0] if rest.split() else ""
                cursor += 1
                continue
            break
        flags = text[flag_start:cursor]
        results.append((flags, target))
        index = cursor
    return results


def _sed_script_write_targets(script: str) -> list[str]:
    """sed 脚本里写出的文件列表（``w FILE`` 命令 + ``s///w FILE`` 标志）。"""
    text = str(script)
    targets: list[str] = []
    length = len(text)
    # 独立 ``w FILE`` 命令：在命令位置（地址前缀后）识别——第九轮 P1-1，
    # ``2w /outside/x`` / ``/re/w /outside/x`` 与换行后的 ``w`` 一并覆盖。
    for position in _sed_command_start_positions(text):
        # 第九轮 P1-3：GNU sed 的 ``W FILE``（把模式空间的**第一行**写入文件）
        # 同样是写命令 ⇒ 与 ``w`` 一并识别。
        if position >= length or text[position] not in ("w", "W"):
            continue
        rest = text[position + 1 :].lstrip()
        if not rest or rest.startswith(";"):
            continue
        token = rest.split()[0]
        if token and token not in targets:
            targets.append(token)
    # GNU sed 的 ``l FILE``（第十轮 push 闸 P2-4）：清单命令带可选文件参数时
    # 把模式空间写入该文件——仅当**空白分隔**（``l /outside/x``）；紧邻字母
    # （``lq``）是下一条命令而非文件名。
    for position in _sed_command_start_positions(text):
        if position >= length or text[position] != "l":
            continue
        if position + 1 >= length or text[position + 1] not in " \t":
            continue
        rest = text[position + 1 :].lstrip()
        if not rest or rest.startswith(";") or rest.startswith("\n"):
            continue
        token = rest.split()[0]
        if token and token not in targets:
            targets.append(token)
    for flags, target in _sed_subst_commands(text):
        if "w" in flags and target:
            targets.append(target)
    return targets


def _sed_script_executes(script: str) -> bool:
    """sed 脚本是否含 shell 执行（``s///e`` 标志 或 独立 ``e COMMAND`` 命令）。"""
    text = str(script)
    if any("e" in flags for flags, _target in _sed_subst_commands(text)):
        return True
    length = len(text)
    for position in _sed_command_start_positions(text):
        if position >= length or text[position] != "e":
            continue
        rest = text[position + 1 :]
        # 第十轮独立审查 P1-2：独立 ``e`` 命令的**分隔符**形态（``e;`` / ``e}`` /
        # ``e``+换行）此前只认 ``rest[0] in " \t"`` ⇒ ``e;`` 这类写法被漏掉 ⇒
        # ``sed 'e;w /outside/x' in`` 被放行。⇒ 分隔符/结尾一律判为「执行」。
        if not rest or rest[0] in " \t;}\n":
            return True
    return False


# 第十一轮独立审查 P1-1：ed/ex 内联脚本的写/执行形态再补——**多字母写命令**
# （``wq`` / ``wn`` / ``wa`` / ``wall`` / ``x`` / ``xit`` / ``xall``）此前完全没建模
# ⇒ ``ex -c 'wq /outside/x' f`` / ``ex -c 'x /outside/x' f`` 不产生任何写目标 ⇒
# 放行；``ex +'w /outside/x' f``（``+cmd`` **启动通道**）整个脚本根本没被扫。
# ⇒ 改为按**命令词**建模：写命令集合 / 执行命令集合 / 确定无害集合；
#    命令位置的词若不在任何集合里 ⇒ 其写目标不可静态定位 ⇒ fail-closed。
# 第十二轮 push 闸 P2-1：删除已被命令词模型取代的死正则（``_ED_WRITE_RE`` /
# ``_ED_WRITE_CMD_RE``）——留着会让后续审查/复用误判实际生效的判定路径。
_ED_PIPE_CMD_RE = re.compile(r"^[^\s]*\s*[wre]\s*!(\S.*)$")
_ED_WRITE_COMMANDS = frozenset(
    {"w", "W", "wq", "wn", "wa", "wall", "x", "xit", "xall", "save", "saveas"}
)
# 第十二轮 push 闸 P2-5：``s/a/b/`` / ``y/ab/cd/`` 这类**定界符参数形态**是
# 缓冲区内替换/转写（不落盘），且是 ex 最常用形态——按首尾定界符识别放行，
# 不再落到「未建模 ⇒ fail-closed」分支（数值地址形态本就能命中）。
_ED_DELIMITED_FORMS = frozenset({"s", "y", "m", "g", "v"})
# ``e CMD`` 在 ex 里是**执行 shell 命令**（不是 vim 的 ``:e file``）⇒ 执行类。
_ED_EXEC_COMMANDS = frozenset({"!", "e", "sh", "shell", "normal", "norm"})
_ED_SAFE_COMMANDS = frozenset(
    {
        "p", "P", "n", "N", "q", "Q", "r", "s", "g", "v", "y", "u", "U", "m",
        "t", "z", "=", "#", "&", "~", "k", "h", "f",
        # 缓冲区内的编辑命令（只改内存里的缓冲区，落盘要靠 ``w``/``x`` ⇒ 已被
        # 写命令集合单独建模）
        "d", "c", "a", "i", "I", "j",
        "set", "put", "pu", "copy", "co", "move", "retab", "resize", "redraw",
        "red", "new", "newer", "vnewer", "split", "sp", "vsplit", "vsp", "file",
        "buffers", "ls", "ll", "windo", "winc", "wincmd", "help", "version",
        "ver", "scriptnames", "syntax", "syn", "hi", "highlight", "map", "nmap",
        "vmap", "noremap", "nnoremap", "unmap", "nunmap", "print", "quit",
        "read", "edit", "substitute", "global", "vglobal", "undo", "redo",
        "yank", "delete", "join",
    }
)


def _ed_command_word(line: str) -> str:
    """ex 命令行 → 命令词（去掉地址前缀与尾部的 ``!``）。

    地址前缀（``1`` / ``1,2`` / ``$`` / ``%``）按「首个字母之前的那段」处理；
    **模式地址**（``/re/w``）在语法上与命令词不可区分 ⇒ 这类行会落到
    「未建模命令」⇒ fail-closed（宁可多拦，不放行）。
    """
    parts = line.split()
    if not parts:
        return ""
    head = parts[0]
    index = 0
    while index < len(head) and not head[index].isalpha() and head[index] != "!":
        index += 1
    return head[index:].rstrip("!")


def _ed_write_argument(line: str) -> str | None:
    """写命令后的文件参数（``w FILE`` / ``wq FILE`` / ``x FILE`` …）；没有则 ``None``。"""
    parts = line.split()
    if len(parts) < 2:
        return None
    tail = parts[-1]
    if tail.startswith(">>"):
        tail = tail[2:].strip()
    return tail or None


def _ed_delimited_form_safe(word: str) -> bool:
    """ex 定界符参数形态的静态安全判定（第十二轮 push 闸 P2-5）。

    - ``s/a/b/`` / ``y/ab/cd/``：缓冲区内替换/转写——ex 的 s/y **没有** w 旗标
      （那是 sed 的语法），落盘必须另走 ``w``（已被写命令集合建模）⇒ 安全；
    - ``g/re/CMD`` / ``v/re/CMD``：全局执行器——``CMD`` 可以是 ``w`` 等任意命令
      ⇒ 只放行确定的读/缓冲区单命令（``p``/``d``/``q``/``#``），其余 fail-closed。
    """
    if not word or len(word) < 3:
        return False
    head = word[0]
    delimiter = word[1]
    if head in ("s", "y"):
        return word[-1] == delimiter
    if head in ("g", "v"):
        parts = word[1:].split(delimiter, 2)
        return len(parts) == 3 and parts[2] in ("p", "d", "q", "#", "")
    return False


def _ed_script_write_targets(script: str) -> tuple[list[str], bool]:
    """ed/ex 内联脚本的写目标 + 是否含**未建模/执行**命令（⇒ fail-closed）。

    第八轮 P1-4：ex 支持**竖线链**（``%s/a/b/|w /outside/x|q``），旧实现只按
    ``^``/换行 锚定 ``w`` ⇒ 链中的 ``w`` 漏检 ⇒ 越界写被放行 ⇒ 改为按 ``|`` 与
    换行切分后逐条判定（两者都是 ex 的命令分隔符）。

    第十轮独立审查 P1-1：只认 ``w FILE`` 一种形态 ⇒ 漏掉 ``w! FILE`` /
    ``w >> FILE`` / ``save FILE`` / ``saveas FILE``，且把 ``w !CMD``（管道给
    shell）当成相对文件名 ⇒ 落在 scope 内 ⇒ 放行。

    第十一轮独立审查 P1-1：再漏**多字母写命令**（``wq`` / ``wn`` / ``wa`` /
    ``wall`` / ``x`` / ``xit`` / ``xall``）⇒ 一并建模；并改为「**未建模命令一律
    fail-closed**」——命令位置的词若不在写/执行/安全三个集合里，其写目标不可
    静态定位 ⇒ 判隐式写目标。
    """
    targets: list[str] = []
    unsafe = False
    for chunk in re.split(r"[|\n]", str(script)):
        line = chunk.strip()
        if not line or line.startswith('"'):
            continue
        if _ED_PIPE_CMD_RE.match(line):
            # 管道给 shell ⇒ 载荷里的写目标不可静态定位 ⇒ fail-closed
            unsafe = True
            continue
        word = _ed_command_word(line)
        if word in _ED_EXEC_COMMANDS:
            unsafe = True
            continue
        if word in _ED_WRITE_COMMANDS:
            argument = _ed_write_argument(line)
            if argument is None:
                # 写回当前缓冲区（原文件）——不是新文件，由调用方按被编辑文件判定
                continue
            targets.append(argument)
            continue
        if word in _ED_SAFE_COMMANDS:
            continue
        if _ed_delimited_form_safe(word):
            continue
        unsafe = True
    return targets, unsafe


def _sed_write_targets(args: Sequence[str]) -> tuple[list[str], bool]:
    """sed 的写目标（第七轮独立审查 P1-1 修订：选项按 getopt 两种形态解析）。

    旧实现只做 **token 精确匹配**（``-e`` / ``--expression=`` / ``-f`` / ``--file=``），
    漏掉 getopt 的两种形态：
    - **粘连簇**：``sed -nf helper.sed in``（``-n`` 开关 + ``-f`` 取值）——
      整段 token 被跳过 ⇒ 脚本文件不被扫 ⇒ 越界写被放行；
    - **长选项唯一前缀缩写**：``--fi``（= ``--file``）/ ``--expressio=``——同理漏检。

    ⇒ 改用 **族模型**（``llm_loop.core.command_options``）按 getopt 语义解析。

    判定：
    - 就地编辑（``-i`` / ``--in-place``）⇒ 写目标是**输入文件**（脚本不是被编辑文件）；
    - 脚本来自 ``-e`` / ``--expression`` ⇒ 扫脚本里的 ``w FILE``；
    - 脚本来自文件（``-f`` / ``--file``）⇒ 写目标不可静态定位 ⇒ fail-closed；
    - 未识别的选项 ⇒ 脚本来源不可静态定位 ⇒ fail-closed。
    """
    scan = scan_options(SED_OPTIONS, args)
    if scan.unresolved:
        # 未识别的选项 ⇒ 脚本来源与写目标不可静态定位 ⇒ fail-closed
        return ([], True)
    option_scripts = [
        event.value
        for event in scan.events
        if event.name in ("--expression", "-e") and event.value
    ]
    from_file = scan.has("--file", "-f")
    operands = list(scan.operands)
    scripts = list(option_scripts)
    if not scripts and operands:
        scripts = [operands[0]]
    if from_file:
        # ``-f FILE``：脚本正文在文件里 ⇒ 无法静态定位写目标 ⇒ fail-closed
        # （第八轮 P1-1：旧实现让 ``-i`` 分支先返回 ⇒ ``sed -i -f FILE in`` 绕过了
        #  这条 fail-closed ⇒ 脚本里的 ``w /outside/x`` 被放行 ⇒ 越界写）
        return ([], True)
    targets: list[str] = []
    for script in scripts:
        targets.extend(_sed_script_write_targets(script))
        if _sed_script_executes(script):
            # ``s///e`` / 独立 ``e CMD`` 把内容当 shell 命令执行 ⇒ 写目标不可静态定位
            return ([], True)
    if scan.has("--in-place", "-i"):
        # 就地编辑改写的是**输入文件**：脚本（位置参数首位）不算被编辑文件
        edited = operands if option_scripts else operands[1:]
        return (edited + targets, len(edited) < 1)
    return (targets, False)


def _perl_write_targets(args: Sequence[str]) -> tuple[list[str], bool]:
    """perl 的写目标（第七轮独立审查 P1-3 修订：簇长上限漏检聚集形态）。

    旧实现用 ``^-([A-Za-z]{1,3})(\\..*)?$``（**簇长上限 3**）识别就地编辑开关，
    而 perl 的短开关可**任意聚集**（``-lpie`` / ``-pain``）⇒ 上限外的聚集形态被
    整段跳过 ⇒ 越界就地编辑被放行。
    ⇒ 改用族模型按 getopt 语义拆簇（取值型开关吃掉簇内其余字母，如 ``-Mstrict``）。
    """
    scan = scan_options(PERL_OPTIONS, args)
    if scan.has("-i"):
        # 被编辑的是**输入文件**：程序（位置参数首位，或 ``-e`` 的值）不算被编辑文件
        operands = list(scan.operands)
        edited = operands if scan.has("-e", "-E") else operands[1:]
        return (edited, len(edited) < 1)
    if scan.unresolved:
        # 未知短字母可能自己就取值 ⇒ 不能排除簇里藏着 ``-i`` ⇒ fail-closed
        return ([], True)
    return ([], False)


def _tar_mode(args: Sequence[str], positional: Sequence[str], letter: str) -> bool:
    """tar 是否处于给定模式（``x``=解包 / ``c``=创建）。

    认四种形态：
    - 完整形态：``-x`` / ``--extract`` / ``-c`` / ``--create``；
    - 粘连形态：``-xf`` / ``-czf``（字母出现在短选项串里）；
    - **长选项唯一前缀缩写**：``--extrac``（= ``--extract``）——第七轮独立审查 P1-1：
      旧实现只做 token 精确匹配 ⇒ ``--extrac`` 曾放行真实解包写；
    - **老式无横线写法**：``tar xf a.tar`` / ``tar cf ARCHIVE …``（首词含该字母）。
    """
    long = {"x": "--extract", "c": "--create"}[letter]
    scan = scan_options(TAR_OPTIONS, args)
    if scan.has(long):
        return True
    if scan.has(f"-{letter}"):
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


def _tar_mode_known(args: Sequence[str], positional: Sequence[str]) -> bool:
    """tar 的模式是否可静态确定（显式模式选项，或旧式首词写法）。

    第八轮 P1-2：旧实现回退到「第一个位置参数」⇒ **模式未知**时（典型：某个
    取值型选项把模式字母吞进自己的值里，如 ``-Z`` 取值吞掉后面的 ``xf``）会按
    「建档」处理 ⇒ 真实解包写被放行 ⇒ 改为模式未知即 fail-closed。

    可用性代价：``tar a.tar b``（默认建档，未写显式模式）会被拦 —— 已登记为残余。
    """
    if any(_tar_mode(args, positional, letter) for letter in ("x", "c")):
        return True
    scan = scan_options(TAR_OPTIONS, args)
    return scan.has(
        "--list",
        "--append",
        "--update",
        "--delete",
        "--get",
        "-t",
        "-r",
        "-u",
    )


def _tar_archive(args: Sequence[str], positional: Sequence[str]) -> str | None:
    """tar 创建模式的归档文件路径（``None``=不可静态定位）。

    认三种形态：
    - ``-f ARCHIVE`` / ``--file ARCHIVE`` / ``--file=ARCHIVE``；
    - **粘连短选项簇**里的 ``f``（``-cvf ARCHIVE`` / ``-czf ARCHIVE`` / ``-cvfARCHIVE``）
      ——第六轮独立审查 P1-1：token 精确匹配认不出粘连簇 ⇒ 回退逻辑取错操作数
      （粘连形态里 ``positional[0]`` **就是**归档），真实越界归档写被放行；
    - 老式无横线写法 ``tar cf ARCHIVE …``（首词是开关串，归档是第 2 个位置参数）。
    """
    scan = scan_options(TAR_OPTIONS, args)
    archive = scan.value_of("-f", "--file")
    if archive is not None:
        return archive
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
      ``-C`` 目录（第三轮审查 P0-5）或 ``--one-top-level`` 目录（第七轮 P1-1 补充：
      它同样决定落盘根目录）；
    - **创建模式**（``c``）：写目标是**归档文件**（见 `_tar_archive`）——第五轮独立
      审查 P0-4：``tar -c --file=/outside/x.tar a`` 把归档写到 ``--file`` 指定的路径，
      此前只把位置参数当写目标 ⇒ 越界写放行；
    - 其余模式：第 1 个位置参数。
    """
    scan = scan_options(TAR_OPTIONS, args)
    if scan.unresolved:
        # 第八轮 P1-2/P1-5：未识别的选项 ⇒ 模式与写目标不可静态定位 ⇒ fail-closed。
        # （旧实现回退到「第一个位置参数」⇒ ``tar -Zxf a.tar`` 这类**簇截断**
        #  （``Z`` 不在表里 ⇒ 后续 ``x``/``f`` 被丢弃）会让归档路径逃逸判定被绕过）
        return ([], True)
    if scan.has("-F", "--info-script"):
        # 第八轮 P1-2：``-F FILE`` 让 tar **执行**该脚本 ⇒ 载荷不可静态定位
        return ([], True)
    if scan.has("-I", "--use-compress-program"):
        # 第十一轮独立审查 P2-1：``-I/--use-compress-program PROG`` 让 tar
        # **执行**该程序 ⇒ 与 ``-F/--info-script`` 同类的执行载荷 ⇒ 口径必须
        # 一致（此前只当普通取值选项 ⇒ 程序被无检查地执行）。
        return ([], True)
    if not _tar_mode_known(args, positional):
        # 第八轮 P1-2：模式不可静态确定 ⇒ 写目标不可静态定位 ⇒ fail-closed
        return ([], True)
    snapshot = scan.value_of("-g", "--listed-incremental", "--incremental")
    # 第十四轮 P0：``--checkpoint-action=exec=CMD`` 让 tar 在每个检查点
    # **执行** CMD ⇒ 载荷不可静态定位 ⇒ fail-closed（与 ``-F/--info-script``、
    # ``-I/--use-compress-program`` 同一口径）。
    checkpoint = scan.value_of("--checkpoint-action")
    if checkpoint is not None and checkpoint.startswith("exec="):
        return ([], True)
    # 第十四轮 P0：``--index-file=FILE`` 让 tar 写**索引文件** ⇒ FILE 是写目标。
    index_file = scan.value_of("--index-file")
    if _tar_mode(args, positional, "x"):
        # 第十二轮 push 闸 P1-1：tar 的多个 ``-C`` 各自作用于其后的成员 ⇒
        # **逐个都判**（此前只回最后一个：``tar -xf a.tar -C /outside m -C src``
        # 会拿 src 判定而 /outside 逃逸）。
        dirs = scan.values_of("-C", "--directory")
        if not dirs:
            top = scan.value_of("--one-top-level")
            dirs = [top] if top else []
        return (list(dirs) + ([index_file] if index_file else []), not dirs)
    if _tar_mode(args, positional, "c"):
        archive = _tar_archive(args, positional)
        if archive is not None:
            # 第八轮 P1-2：``-g FILE``（快照文件）在建档时被写入 ⇒ 也是写目标
            targets = [archive] + ([snapshot] if snapshot else [])
            if index_file:
                targets.append(index_file)
            return (targets, not archive)
        # 创建模式但归档名不可静态定位 ⇒ 拒
        return ([], True)
    return (positional[:1], not positional)


def _download_write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """curl / wget 的写目标（第七轮独立审查 P1-1：选项按 getopt 两种形态解析）。

    - 指定输出文件/目录 ⇒ 那是写目标；
    - ``curl -O/--remote-name/--remote-name-all`` ⇒ 按**远端名**落盘到当前目录，
      文件名不可静态定位（第五轮独立审查 P1-3：``--remote-name-all`` 曾被漏掉；
      第七轮 P1-1：``--remote-name-a`` 这类唯一前缀缩写也曾被漏掉）；
    - 其余**会落盘文件**的选项（头文件 / 追踪 / cookie jar / 会话日志等）同样计入；
    - wget 无输出选项 ⇒ 按 URL 派生文件名写到当前目录 ⇒ 同样不可静态定位。
    """
    if name == "curl":
        scan = scan_options(CURL_OPTIONS, args)
        if scan.unresolved:
            # 第八轮 P1-5：未识别的选项 ⇒ 写目标不可静态定位 ⇒ fail-closed
            # （此前 curl/wget 族不消费 ``scan.unresolved`` ⇒ 与 sed/perl 两套口径）
            return ([], True)
        targets: list[str] = []
        for flag in (
            "-o",
            "--output",
            "--output-dir",
            "-D",
            "--dump-header",
            "--trace",
            "--trace-ascii",
            "--trace-config",
            "-c",
            "--cookie-jar",
            "--stderr",
            "--libcurl",
            "--etag-save",
            "--json",
            "--crt-file",
            # 第十四轮：``--alt-svc FILE`` / ``--hsts FILE`` **会落盘文件**
            # （Alt-Svc 缓存 / HSTS 缓存）⇒ 此前登记成开关 ⇒ 其 FILE 变成位置
            # 参数 ⇒ 写目标从未被定位（实测靠 fail-closed 兜住，拒因不准）。
            "--alt-svc",
            "--hsts",
        ):
            # 第十二轮独立审查 P1-1：curl 的多个 ``-o`` **逐个都写**（每个 URL
            # 一个文件）⇒ 全部取值都要判，不能只看第一个。
            targets.extend(scan.values_of(flag))
        # 第十四轮 P0 + 独立审查 P1-1：隐式写只认 ``-O/--remote-name/
        # --remote-name-all``（按**远端名**落盘到 cwd ⇒ 文件名不可静态定位）。
        # ``-J/--remote-header-name`` **只在配合 -O 时**才决定文件名（curl
        # 文档：--remote-header-name 仅在 --remote-name 生效）；``--create-dirs``
        # 只是给**已判定**的显式目标建父目录 ⇒ 二者本身都不引入不可定位的写。
        # 此前把三者一并算作隐式写 ⇒ ``curl --create-dirs -o dl/f.bin URL`` 这类
        # 本应放行的形态被误拒（可用性回归）。
        implicit = scan.has("-O", "--remote-name", "--remote-name-all")
        if targets:
            return (targets, any(not target for target in targets) or implicit)
        if implicit:
            return ([], True)
        return ([], False)
    scan = scan_options(WGET_OPTIONS, args)
    if scan.unresolved:
        # 第八轮 P1-5：未识别的选项 ⇒ 写目标不可静态定位 ⇒ fail-closed
        return ([], True)
    targets = []
    for flag in (
        "-O",
        "--output-document",
        "--output-file",
        # 第八轮 P1-5：``-a/--append-output FILE`` 是**追加日志文件**（写目标）——
        # 旧实现把 ``-a`` 当开关 ⇒ ``wget -a /outside/log URL`` 的写盘被放行。
        "-a",
        "--append-output",
        "-P",
        "--directory-prefix",
        # 第十四轮：``--save-cookies FILE`` 写 cookie jar ⇒ 写目标。
        "--save-cookies",
    ):
        value = scan.value_of(flag)
        if value is not None:
            targets.append(value)
    if targets:
        return (targets, any(not target for target in targets))
    if scan.has("--backups"):
        # ``--backups`` 会为下载文件生成 ``.1`` 备份 ⇒ 写目标不可静态定位
        return ([], True)
    return ([], True)


# ── 编译器/链接器产物判定（第九轮 push 闸 P1-2）─────────────────────────────
# 旧口径对 ``-o`` 做 token 精确匹配 ⇒ 附着形态（``-o/outside/x``）、内联形态
# （``--output=/outside/x``）与**默认产物**（``gcc a.c`` → ``a.out``）都漏检。
# 编译选项族过于庞大，无法用 FamilyOptions 单表穷举（``-MF`` 等双字母取值选项
# 也不是单字母簇），改按**前缀逐 token 归类**：取值型输出/依赖选项给静态目标，
# 依赖开关与未识别选项 fail-closed（写目标不可静态定位）。

_COMPILER_VALUE_FLAGS = (
    "-o", "--output",            # 输出文件
    "-MF", "-MJ", "-aux-info",   # 依赖/清单产物（取值）
    "-dumpdir", "-dumpbase", "-dumpbase-ext",
    "-x", "-std",                # 语言/方言（取值，非写）
)
_COMPILER_DEP_BOOL_FLAGS = ("-MD", "-MMD", "-MP", "-MV", "-save-temps", "-save-temps=cwd", "-save-temps=obj")
_COMPILER_STAGE_FLAGS = ("-c", "-E", "-S", "-fsyntax-only")
_COMPILER_WRITING_F_PREFIXES = (
    "-fprofile", "-ftest-coverage", "-fopt-info", "-flto", "-frepo", "-fplugin",
)
# 良性 ``-f*`` 前缀白名单（第十轮 P1-1：``-f`` 整族放行会漏 ``-fdump-tree-all``
# / ``-fcallgraph-info`` 等写盘旗标——改为白名单制，名单外 ``-f*`` 一律 fail-closed）。
_COMPILER_BENIGN_F_PREFIXES = (
    "fsyntax-only", "ffast-math", "fno-", "fPIC", "fpic", "fPIE", "fpie",
    "fcommon", "fstack-protector", "fvisibility", "fcolor-diagnostics",
    "fdiagnostics-", "fmessage-length", "fwrapv", "freestanding", "fhosted",
    "fsigned-char", "funsigned-char", "fshort-enums", "fstrict-aliasing",
    "funroll-loops", "finline", "fmerge-constants", "fbuiltin", "fprintf",
    "fexceptions", "frtti", "fpermissive", "finput-charset", "fexec-charset",
)
# 驱动器透传前缀（第十轮 P1-1）：``-Wl,-o,FILE`` / ``-Wa,-o,FILE`` /
# ``-Wp,FILE=…`` 把目标传给链接器/汇编器/预处理器——必须按段解析。
_COMPILER_PASSTHROUGH_PREFIXES = ("-Wl,", "-Wa,", "-Wp,", "-Wl=", "-Wa=", "-Wp=")
# 命中即 implicit 的执行/改写面旗标（第十轮 P1-1：``-B``/``-Xlinker``/``-Xclang``
# / ``-wrapper`` 改执行路径或透传任意参数——曾整族躺在良性前缀里放行）。
_COMPILER_EXEC_SURFACE_FLAGS = ("-B", "-Xlinker", "-Xclang", "-wrapper", "-wrapper=")
_COMPILER_BENIGN_PREFIXES = (
    "-I", "-L", "-l", "-D", "-U", "-m", "-O", "-g", "-s", "-v",
    "-pedantic", "-pipe", "-pthread", "-A", "-shared", "-static",
    "-idirafter", "-imacros", "-include", "-isystem", "-iquote", "-undef",
    "-ansi", "-traditional", "-std",
    # 第九轮 P1-1：长形态的只读/无害选项——``--version``/``--help`` 只打印信息，
    # ``--target``/``--sysroot``/``--gcc-toolchain``/``--param`` 只改查找路径。
    "--version", "--help", "--verbose", "--target", "--sysroot",
    "--gcc-toolchain", "--param", "-x",
)


# 第十四轮：组合短选项里，取值型选项**之前**允许出现的布尔短选项字母。
# 只收**确定不带值**的字母（``-w``/``-v``/``-c``）；``-g``/``-O``/``-f``/``-m``/
# ``-W``/``-l``/``-L``/``-I``/``-D`` 都是**附着值**族（``-Wall``、``-g3``、
# ``-ofoo``）⇒ 不得当作布尔前缀，否则 ``-lo``（``-l`` 的值 o）会被误读成 ``-o``。
_COMPILER_CLUSTER_BOOL_LETTERS = frozenset({"w", "v", "c"})


def _compiler_token_value(raw: list[str], flag: str) -> str | None:
    """取值型编译选项的值：``-o x`` / ``-ox`` / ``-o=x`` / ``--output=x`` 形态.

    返回 ``None`` = 选项未出现；空串 = 出现但值不可静态定位（fail-closed）。
    """
    # 第十二轮独立审查 P1-1：旧实现遇到第一个命中就 return ⇒ ``gcc -o a -o
    # /outside/x`` 只判了 ``a`` ⇒ 而 gcc 实际写的是**最后一个** ⇒ 越界写放行。
    # ⇒ 改为取最后一个命中。
    found: str | None = None
    for index, token in enumerate(raw):
        if token == flag:
            found = raw[index + 1] if index + 1 < len(raw) else ""
        elif token.startswith(flag + "=") and len(token) > len(flag) + 1:
            found = token[len(flag) + 1 :]
        elif token.startswith(flag + "/") and len(token) > len(flag) + 1:
            # ``-o/outside/x``：斜杠是**值的首字符**（getopt 附着值），不是分隔符
            found = token[len(flag) :]
        elif (
            len(flag) == 2
            and not flag.startswith("--")
            and len(token) > 2
            and token[0] == "-"
            and token[1] in _COMPILER_CLUSTER_BOOL_LETTERS
            and token[2] == flag[1]
            and (len(token) == 3 or token[3] in "/=")
        ):
            # 第十四轮 P0：组合短选项（getopt 语义）——``-wo/outside/x`` =
            # ``-w``（布尔）+ ``-o``（取值，值为余串）。此前只认「token 以
            # ``-o`` 开头」⇒ ``-wo...`` 整族不命中 ⇒ 产物落点从未被判定 ⇒
            # 越界写放行。余串为空（``-wo``）⇒ 值取下一个 argv。
            if len(token) > 3:
                found = token[3:]
            else:
                found = raw[index + 1] if index + 1 < len(raw) else ""
    return found


def _compiler_has_unmodeled_flag(raw: list[str]) -> bool:
    """是否存在无法归类的选项 token（可能自带写面）⇒ fail-closed.

    第十轮 P1-1：``-W``/``-w``/``-f``/``-B``/``-Xlinker``/``-Xclang``/``-wrapper``
    不再整族放行——透传形态（``-Wl,`` 族）交 `_compiler_passthrough_targets`，
    ``-f*`` 走白名单，执行面旗标交 `_compiler_exec_surface`。
    """
    known_values = _COMPILER_VALUE_FLAGS + ("-emit", "--crate-type", "--edition")
    benign_f = tuple("-f" + prefix for prefix in _COMPILER_BENIGN_F_PREFIXES)
    for token in raw:
        if not token.startswith("-") or token == "-":
            continue
        if token in _COMPILER_STAGE_FLAGS or token in _COMPILER_DEP_BOOL_FLAGS:
            continue
        if token.startswith(_COMPILER_WRITING_F_PREFIXES):
            continue  # 写面标志，另行按 implicit 处理
        if token.startswith(_COMPILER_PASSTHROUGH_PREFIXES):
            continue  # 由 _compiler_passthrough_targets 按段解析
        if any(
            token == flag
            or token.startswith(flag + "=")
            or (token.startswith(flag + "/") and len(flag) <= 3)
            for flag in known_values
        ):
            continue
        if token.startswith(("-W", "-w")) and not token.startswith(_COMPILER_EXEC_SURFACE_FLAGS):
            continue  # 诊断/静默族——无写面（透传形态已先行分流）
        if token.startswith(benign_f):
            continue
        if token.startswith(_COMPILER_BENIGN_PREFIXES):
            continue
        return True
    return False


def _compiler_exec_surface(raw: list[str]) -> bool:
    """执行/改写面旗标出现（``-B``/``-Xlinker``/``-Xclang``/``-wrapper``）。"""
    for token in raw:
        for flag in ("-B", "-Xlinker", "-Xclang"):
            if token == flag or (flag == "-B" and token.startswith("-B")):
                return True
        if token == "-wrapper" or token.startswith("-wrapper="):
            return True
    return False


def _compiler_passthrough_targets(token: str) -> tuple[list[str], bool]:
    """``-Wl,-o,FILE`` / ``-Wa,-o,FILE`` / ``-Wp,FILE=…`` 透传段解析.

    返回 (静态写目标, 是否含不可静态定位段)。段内 ``-o``/``--output`` 的**下一段**
    是输出文件；其余任何段（``--as-needed``/``-rpath`` 等）都是驱动器未知语义
    ⇒ fail-closed（本轮从宽到收紧紧：宁可误拒合法链接旗标，不放行透传写面）。
    """
    body = token.split(",", 1)[1] if "," in token else token.split("=", 1)[1]
    segments = [seg for seg in body.replace("=", ",").split(",") if seg]
    targets: list[str] = []
    implicit = False
    for index, segment in enumerate(segments):
        if segment in ("-o", "--output"):
            if index + 1 < len(segments):
                targets.append(segments[index + 1])
            else:
                implicit = True
        elif index > 0 and segments[index - 1] in ("-o", "--output"):
            continue  # 已作为输出值消费
        else:
            implicit = True
    return (targets, implicit)


def _compiler_write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """编译器/链接器（gcc/clang/ld/rustc 族）的 (静态写目标, 隐式写目标)."""
    raw = [str(a) for a in args]
    if any(token in ("--version", "--help") for token in raw):
        # 信息型旗标让编译器**先于任何输出**退出（第九轮回归修复）
        return ([], False)
    output = _compiler_token_value(raw, "-o")
    if output is None:
        output = _compiler_token_value(raw, "--output")
    # 第十二轮 push 闸 P1-2：透传目标**先收集**——``gcc -o a.out -Wl,-o,/outside/x``
    # 里 ld 的最后一个 -o 生效，不能因驱动 -o 命中静态目标就早退漏掉透传段。
    passthrough_targets: list[str] = []
    passthrough_implicit = False
    for token in raw:
        if token.startswith(_COMPILER_PASSTHROUGH_PREFIXES):
            targets_, implicit_ = _compiler_passthrough_targets(token)
            passthrough_targets.extend(targets_)
            passthrough_implicit = passthrough_implicit or implicit_
    # 执行面/未归类旗标先判定——``-Xlinker -o -c src/a.c`` 里 ``-Xlinker``
    # 透传任意驱动参数，不能因 ``-o`` 命中静态目标就早退放行（第十轮修复）。
    surface_implicit = (
        _compiler_exec_surface(raw)
        or _compiler_has_unmodeled_flag(raw)
        or _compiler_token_value(raw, "--emit") is not None
        or any(token in _COMPILER_DEP_BOOL_FLAGS for token in raw)
        or any(token.startswith(_COMPILER_WRITING_F_PREFIXES) for token in raw)
    )
    if output is not None:
        return (
            [output] + passthrough_targets,
            not output or surface_implicit or passthrough_implicit,
        )
    targets: list[str] = passthrough_targets
    for flag in ("-MF", "-MJ", "-aux-info", "-dumpdir", "-dumpbase"):
        value = _compiler_token_value(raw, flag)
        if value:
            targets.append(value)
    implicit = bool(targets) or passthrough_implicit
    if (
        any(token in _COMPILER_DEP_BOOL_FLAGS for token in raw)
        or any(token.startswith(_COMPILER_WRITING_F_PREFIXES) for token in raw)
        or _compiler_token_value(raw, "--emit") is not None
        or _compiler_has_unmodeled_flag(raw)
        or _compiler_exec_surface(raw)
    ):
        implicit = True
    if any(token in _COMPILER_STAGE_FLAGS for token in raw):
        if "-E" in raw or "-fsyntax-only" in raw:
            return (targets, implicit)
        sources = [token for token in raw if not token.startswith("-")]
        suffix = ".o" if "-c" in raw else ".s"
        if sources:
            targets.append(str(os.path.splitext(sources[0])[0]) + suffix)
        else:
            implicit = True
        return (targets, implicit)
    if name == "rustc":
        # 产物名随 --crate-type/--emit 变（a / liba.rlib / a.s …）⇒ 不可静态定位
        return (targets, True)
    # gcc/clang/ld 的链接默认产物：cwd 下的 a.out（静态可判）
    targets.append("a.out")
    return (targets, implicit)


def _write_targets(name: str, args: Sequence[str]) -> tuple[list[str], bool]:
    """返回 (静态写目标列表, 是否存在无法静态定位的隐式写目标)."""
    positional = _non_flag_args(args)
    if name in ("gcc", "g++", "cc", "c++", "clang", "clang++", "ld", "rustc"):
        # 第九轮 P1-2：编译器族改专用产物判定（附着 -o / 默认产物 / 依赖文件）
        return _compiler_write_targets(name, args)
    if name in ("sort", "shuf"):
        # 第九轮 P1-2：``-o/x`` 附着形态与 ``--output=`` 内联形态改走族模型；
        # 未识别选项按 fail-closed（第八轮 P1-5 统一口径）。
        family = SORT_OUTPUT_OPTIONS if name == "sort" else SHUF_OUTPUT_OPTIONS
        scan = scan_options(family, args)
        if scan.unresolved:
            return ([], True)
        out = scan.value_of("-o", "--output")
        if out is not None:
            return ([out], not out)
        return ([], False)
    if name in ("cp", "mv", "install", "ln", "rsync"):
        # 目标目录 / 备份目录 / 末位操作数的判定口径见
        # ``_copy_move_targets``（rsync 的 -t 是 --times 布尔开关，只有
        # cp/mv/install/ln 的 -t 才是 --target-directory——审查 P1-1、第五轮
        # 审查 P1-2 补入 ln：``ln -t DIR`` 把链接建到 DIR 下）。
        return _copy_move_targets(name, args, positional)
    if name in (
        "rm", "rmdir", "mkdir", "touch", "tee", "truncate", "shred",
        # 第四轮审查补入：这些工具的写目标就是命名参数（可静态定位）
        "unlink", "mkfifo", "mknod", "mkswap",
    ):
        return (positional, False)
    if name == "patch":
        # patch 的 -o/--output 是**输出文件**（第三轮审查 P0-8；第九轮 P1-1 改走
        # 族模型 ⇒ getopt 附着形态 ``-oFILE`` 也能识别）
        out = scan_options(PATCH_OPTIONS, args).value_of("-o", "--output")
        if out is not None:
            return ([out], not out)
        # patch 无目标文件 ⇒ 从 stdin 读补丁并改写文件（目标不可静态定位）
        return (positional, not positional)
    if name in ("chmod", "chown", "chgrp"):
        return (positional[1:], len(positional) < 2)
    if name == "sed":
        # 第七轮独立审查 P1-1：选项改按 **getopt 两种形态**（粘连簇 / 唯一前缀缩写）
        # 解析 ⇒ 统一走族模型（``llm_loop.core.command_options``）。
        return _sed_write_targets(args)
    if name == "perl":
        # perl -i（就地编辑）改写**输入文件**；无 -i 时是解释器残余（见残余清单）。
        # 第七轮独立审查 P1-3：簇长上限 3 会漏掉 ``-lpie`` / ``-pain`` 这类聚集形态。
        return _perl_write_targets(args)
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
        # 第十一轮独立审查 P1-1：``+cmd`` **启动通道**同样是脚本
        # （``ex +'w /outside/x' f`` ⇒ ex 把该串当第一条 ex 命令执行）⇒ 此前
        # 完全没被扫 ⇒ 越界写放行。
        scripts.extend(
            token[1:]
            for token in raw
            if token.startswith("+")
            and len(token) > 1
            # 第十二轮独立审查 P2-3：``ex +5 f`` 的 ``+5`` 是**初始行号**，不是
            # 命令 ⇒ 不进脚本通道（否则被当成未建模命令词 ⇒ 白白被拦）。
            and not token[1:].isdigit()
        )
        script_targets: list[str] = []
        script_executes = False
        for script in scripts:
            targets, executes = _ed_script_write_targets(script)
            script_targets.extend(targets)
            script_executes = script_executes or executes
        edited = [
            a
            for a in _non_flag_args(args)
            if a not in scripts and not a.startswith("+")
        ]
        # 第十轮独立审查 P1-1：脚本含**执行**（``w !CMD`` / ``r !CMD`` / ``e CMD``）
        # ⇒ 载荷里的写目标不可静态定位 ⇒ fail-closed（此前只判写文件目标 ⇒
        # ``ed -c 'w !rm -rf /outside/x' f`` 被放行）。
        implicit = script_executes or not scripts
        return (script_targets + edited, implicit)
    if name == "dd":
        outputs = [a.split("=", 1)[1] for a in args if a.startswith("of=")]
        return (outputs, not outputs)
    if name == "tar":
        return _tar_write_targets(args, positional)
    if name == "unzip":
        # 第九轮 P1-1：``-d DIR`` 是解包目录（写目标）——改走族模型 ⇒ 附着形态
        # ``-dDIR`` 也能识别
        dest = scan_options(UNZIP_OPTIONS, args).value_of("-d", "--directory")
        return ([dest] if dest else [], not dest)
    if name == "zip":
        return (positional[:1], not positional)
    if name in ("gzip", "xz", "bzip2", "zstd"):
        # zstd 的 -o/--output 是**输出文件**（第三轮审查 P0-9；第九轮 P1-1 改走
        # 族模型 ⇒ 附着形态 ``-oFILE`` 也能识别）
        out = scan_options(COMPRESS_OUTPUT_OPTIONS, args).value_of("-o", "--output")
        if out is not None:
            return ([out], not out)
        if any(a in ("-c", "--stdout", "--to-stdout") for a in args):
            return ([], False)
        # 就地解压（-d）改写**输入文件**；压缩写的是新文件（保守按输入文件判）
        return (positional[:1], not positional)
    if name in ("curl", "wget"):
        return _download_write_targets(name, args)
    return ([], True)


def _git_fast_export_marks(args: Sequence[str]) -> str | None:
    """``git fast-export --export-marks=FILE`` 的 marks 文件名。

    返回 ``None`` = 没有该选项；返回空串 = 有该选项但文件名不可静态定位。
    """
    scan = scan_options(GIT_EXPORT_OPTIONS, args)
    if not scan.has("--export-marks"):
        return None
    return scan.value_of("--export-marks") or ""


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


def _git_subcommand_args(args: Sequence[str]) -> list[str]:
    """子命令**及其之后**的 token（第九轮 push 闸 P2-2：全局选项前置时 ``args[1:]``
    会错位——``git -c k=v symbolic-ref HEAD`` 是**读**形态，旧口径把 ``k=v``
    计进动作清单 ⇒ 误判为 2 参数写形态）。调用方 ``_git_action_args`` 自行
    剥掉首 token（子命令）——保持包含式语义与其前提一致。"""
    sub = _git_subcommand(args)
    if not sub:
        return list(args)
    try:
        return [str(a) for a in args[args.index(sub) :]]
    except ValueError:
        return list(args)


def _git_long_option_hit(args: Sequence[str], canonical: str) -> bool:
    """git parse-options 的**唯一前缀缩写**命中（第十二轮独立审查 P1-3）。

    ``git symbolic-ref --del HEAD`` 是写形态（改写 .git/HEAD）⇒ 此前只做
    精确匹配 ⇒ 被当成 1 参读形态放行 ⇒ 越界写逃逸。⇒ 命中规则：完全相等 /
    ``--opt=VAL`` / **canonical 以 token 开头**（``--del`` → ``--delete``）。
    多个候选前缀时仍算命中（fail-closed）。
    """
    for token in args:
        if token == canonical or token.startswith(canonical + "="):
            return True
        if token.startswith("--") and canonical.startswith(token):
            return True
    return False


def _symbolic_ref_is_write_form(args: Sequence[str], actions: Sequence[str]) -> bool:
    """``git symbolic-ref`` 的**写形态**判定（改名 / 删除 / 批量）。

    第五轮独立审查 P1-4：读形态只有 1 个位置参数（``git symbolic-ref HEAD``）；
    写形态是「名字 + 新值」2 个位置参数，或带 ``--delete``/``-d``。
    第十三轮：``--stdin`` 是**批量写形态**（stdin 里可含 create/delete/update
    ref 命令）⇒ 与 --delete 同列拒（此前只认 --delete/-d 与 2 个位置参数 ⇒
    ``--stdin`` 被当成读形态放行）。
    第十四轮 P0 + 独立审查 P2-3：``-d`` 可**粘连**（``-dq HEAD``）⇒ 精确匹配
    ``"-d" in args`` 漏掉粘连形态；但前缀匹配 ``token.startswith("-d")`` 会
    **误拒**未来新增的 ``-d*`` 读选项 ⇒ 只认精确 ``-d`` 与 ``-d`` + 已知短
    选项簇（见 ``_git_delete_flag_hit``）；其余 ``-d*``（如 ``-dHEAD``）在 git
    里是**未知选项**（parse-options 因 ``-H`` 未知而报错、不产生任何副作用）。
    """
    return (
        _git_long_option_hit(args, "--delete")
        or _git_long_option_hit(args, "--stdin")
        or any(_git_delete_flag_hit(token) for token in args)
        or len(actions) >= 2
    )


def _git_delete_flag_hit(token: str) -> bool:
    """``git symbolic-ref`` 的**删除形态**：精确 ``-d`` 或 ``-d`` + 已知短选项簇。

    第十四轮独立审查 P2-3：此前用 ``token.startswith("-d")`` ⇒ 未来若新增
    ``-d*`` **读**选项会被误拒（可用性回归）⇒ 收窄为：``-d`` 本身、以及 ``-d``
    后紧跟 symbolic-ref 已知短选项（``-q``/``-m``/``-s``）的组合形态。
    其余 ``-d*``（如 ``-dHEAD``）在 git 里是**未知选项**（parse-options 因
    ``-H`` 未知而报错、命令不产生任何副作用）⇒ 不按删除形态拒。
    """
    if token == "-d":
        return True
    if not token.startswith("-d") or len(token) == 2:
        return False
    return all(char in "qms" for char in token[2:])


def _git_action_args(args: Sequence[str]) -> list[str]:
    """子命令**之后**的非选项参数（动作清单）。

    第九轮 P1-1（自审新发现）：``_git_subcommand_args`` 返回的是「子命令及其之后」
    的 token ⇒ 直接把它当动作清单会把**子命令自己**算成动作 ⇒
    ``git reflog``（动作被判成 ``reflog``）、``git symbolic-ref HEAD``（动作被判成
    2 个 ⇒ 误判写形态）、``git remote -v``（``-v`` 是标志形，被非选项过滤掉 ⇒
    动作清单为空却仍按未知动作拒）三条**读形态**被误拦。
    """
    tokens = _git_subcommand_args(args)
    return [str(a) for a in _non_flag_args(tokens[1:])]


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

    def _scan_script_command(
        self, cmd_tokens: Sequence[str], depth: int
    ) -> CommandScopeDecision | None:
        """script 载体的写面判定（第五轮 P2-1 / 第七轮 P1-2 / 第八轮 P1-3、P1-5）。

        第五轮独立审查 P2-1：``script FILE cmd…``（BSD/GNU script）把会话
        录制**写入 FILE**，同时执行 cmd ⇒ 两处都是写面：
          - FILE 是可定位的写目标（须过 scope 判定）；
          - cmd 是被执行的命令（须按命令链重解析）。
        第六轮独立审查 P1-2：载荷有两种形态 ——
          (a) ``script -c CMD [FILE]``：CMD 由**选项**携带；
          (b) ``script FILE cmd…``：cmd 是 FILE 之后的位置参数。
        此前只按 (b) 取 cmd_tokens[2:] ⇒ (a) 形态下 CMD 被整体漏扫。
        """
        scan = scan_options(SCRIPT_OPTIONS, cmd_tokens[1:])
        if scan.unresolved:
            # 第八轮 P1-5：未识别的选项 ⇒ 写目标不可静态定位 ⇒ fail-closed
            # （此前 script 族不消费 ``scan.unresolved`` ⇒ 与 sed/perl 两套口径）
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                "script：未识别的选项 ⇒ 写目标不可静态定位",
                tuple(self.unverified),
            )
        # 第十四轮 P0：``script -T -c 'CMD'`` 里 ``-T``（--log-timing，**必填
        # 值**）会把 ``-c`` 吃成自己的值（getopt：取值型选项的下一个 argv 即其
        # 值，即使它长得像选项）⇒ 载荷通道 ``-c`` 消失 ⇒ 真正的命令串退化成
        # 位置参数（只当 script 的 typescript 写目标）⇒ 越界写可逃逸。
        # 该处解析存在歧义 ⇒ 按 fail-closed 拦，不给「载荷被吞」的形态任何机会。
        for event in scan.events:
            if event.name and event.value in ("-c", "--command"):
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    "script：取值型选项吞掉了载荷选项（-c/--command）⇒ 载荷命令不可静态定位",
                    tuple(self.unverified),
                )
        payload_cmd = scan.value_of("-c", "--command")
        operands = list(scan.operands)
        # 第八轮 P1-3：script 自己写的**日志/计时**文件同样是写目标
        # （``-t/--log-timing``、``-T/--log-timing``、``-B/--log-io``、
        #  ``-I/--log-in``、``--log-in``、``--log-io``、``--log-out``）。
        log_targets = [
            event.value
            for event in scan.events
            if event.name
            in (
                "--log-timing",
                "--log-in",
                "--log-io",
                "--log-out",
                "-t",
                "-T",
                "-B",
                "-I",
                "-L",
            )
            and event.value
        ]
        if payload_cmd is not None:
            # 第七轮独立审查 P1-2：``script -c CMD FILE`` 的 **FILE 是 typescript
            # 写目标**——此前在 ``-c`` 分支提前 return ⇒ FILE 从未被判定。
            # 无 FILE 时 GNU script 写当前目录的 ``typescript`` ⇒ 同为写目标。
            typescript = operands[0] if operands else "typescript"
            for target in [typescript, *log_targets]:
                ok, reason, detail = self._check_target(target)
                if not ok:
                    return CommandScopeDecision(
                        False, reason, detail, tuple(self.unverified)
                    )
            try:
                payload_tokens = shlex.split(payload_cmd)
            except ValueError:
                # 第九轮 P2-3：载荷串引号不闭合 ⇒ 无法重解析 ⇒ 写目标不可静态定位
                # ⇒ fail-closed（此前 ValueError 会冒泡成未捕获异常 ⇒ 判定崩掉）。
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    "script：载荷命令串无法解析 ⇒ 写目标不可静态定位",
                    tuple(self.unverified),
                )
            return self._scan_command_chain(payload_tokens, depth)
        if operands:
            ok, reason, detail = self._check_target(operands[0])
            if not ok:
                return CommandScopeDecision(
                    False, reason, detail, tuple(self.unverified)
                )
        else:
            # 第十一轮独立审查 P2-2：无 FILE 时 script 写当前目录的
            # ``typescript`` ⇒ 该默认写目标此前从未被判定 ⇒ 越界写可经
            # 「无 FILE 的 script」逃逸。
            ok, reason, detail = self._check_target("typescript")
            if not ok:
                return CommandScopeDecision(
                    False, reason, detail, tuple(self.unverified)
                )
        for target in log_targets:
            ok, reason, detail = self._check_target(target)
            if not ok:
                return CommandScopeDecision(
                    False, reason, detail, tuple(self.unverified)
                )
        return self._scan_command_chain(operands[1:], depth)

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
            if any(_is_chdir_option(a, spec) for a in option_zone):
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
            out = scan_options(TIME_OPTIONS, cmd_tokens[1:]).value_of("-o", "--output")
            if out:
                ok, reason, detail = self._check_target(out)
                if not ok:
                    return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
        if name == "script":
            return self._scan_script_command(cmd_tokens, depth)
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
        if name in _SHELL_EXPORT_BUILTINS:
            # 第十二轮 push 闸 P1-3：``export GIT_EXTERNAL_DIFF=…; git diff`` 用
            # shell 内建**跨段注入**执行型 git 环境变量——与段首前缀赋值同向量，
            # 必须走同一个 `_blocked_assignment` 判定（``declare -x`` 同理）。
            blocked = _blocked_assignment(
                [str(a) for a in args if "=" in str(a)]
            )
            if blocked is not None:
                return blocked
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
        if _is_write_name(name) or name in OUTPUT_FLAG_COMMANDS:
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

    def _check_fast_export_marks(self, args: Sequence[str]) -> CommandScopeDecision | None:
        """``git fast-export --export-marks=FILE`` 的写目标判定。

        第七轮独立审查 P1-4：``git fast-export`` 是只读子命令，但 ``--export-marks``
        会写 marks 文件 ⇒ 该文件必须过 scope 判定（此前完全未判定 ⇒ 越界写放行）。

        返回 ``None`` = 没有写目标（放行）。
        """
        marks = _git_fast_export_marks(args)
        if marks is None:
            return None
        if not marks:
            return CommandScopeDecision(
                False,
                "implicit_write_target",
                "git fast-export --export-marks：marks 文件名不可静态定位",
            )
        ok, reason, detail = self._check_target(marks)
        if not ok:
            return CommandScopeDecision(False, reason, detail, tuple(self.unverified))
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
            # 第九轮 push 闸 P2-1：可执行配置键集合扩为闭集（精确匹配，避免
            # 误伤 ``core.bigFileThreshold`` 这类前缀撞名）——``core.editor``/
            # ``sequence.editor`` 在 commit/tag 等场景被当命令执行；
            # ``core.hooksPath`` 把钩子目录重指到任意可执行脚本；
            # ``core.attributesFile``/``core.excludesFile`` 影响外部过滤器路径。
            lowered = key.lower()
            if _git_exec_config_key(lowered):
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
        if sub in ("fast-export", "fast-export-v2"):
            # 第七轮独立审查 P1-4：``git fast-export`` 是只读子命令，但
            # ``--export-marks=FILE`` 会**写 marks 文件** ⇒ 写目标须过 scope 判定。
            marks_decision = self._check_fast_export_marks(args)
            if marks_decision is not None:
                return marks_decision
        if sub == "symbolic-ref":
            # 第五轮独立审查 P1-4：``symbolic-ref`` 在读白名单里，但写形态
            # （改名 / 删除 / 批量）会改写 .git/HEAD ⇒ 判定口径见
            # ``_symbolic_ref_is_write_form``（含 ``-d`` 粘连簇的精确建模）。
            actions = _git_action_args(args)
            if _symbolic_ref_is_write_form(args, actions):
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git symbolic-ref {actions[0] if actions else ''}：写形态改写 .git/HEAD，写目标不可静态定位",
                )
        if sub == "reflog":
            # 第六轮独立审查 P2-4：``git reflog``（无动作）/ ``git reflog show`` 是读；
            # ``expire`` / ``delete`` 改写 reflog 文件 ⇒ 写形态按写目标不可定位拒。
            actions = _git_action_args(args)
            if actions and not any(a in GIT_REFLOG_READ_ACTIONS for a in actions):
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git reflog {actions[0]}：写目标不可静态定位",
                )
        if sub == "remote":
            # ``git remote`` 有读形态（-v / show / get-url）与写形态
            # （add / set-url / remove …）——按动作分族，名单外按写处理。
            actions = _git_action_args(args)
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
            actions = _git_action_args(args)
            read_forms = [a for a in actions if a in GIT_WORKTREE_READ_ACTIONS]
            if not read_forms:
                return CommandScopeDecision(
                    False,
                    "implicit_write_target",
                    f"git worktree {actions[0] if actions else ''}：写目标不可静态定位",
                )
        if sub in GIT_OUTPUT_SUBCOMMANDS:
            out = scan_options(GIT_OUTPUT_OPTIONS, args).value_of("--output", "-o")
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
