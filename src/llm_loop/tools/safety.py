"""灾难性安全硬边界 CatastrophicGuard（design.md §2.1.3.5 机制四 / FR-SAFE）.

唯一允许程序硬阻断的边界（FR-SAFE-01）: 只拦截不可逆删除/系统破坏，
其余一切如实反馈放行（FR-SAFE-03）。边界刻意保持极小（FR-SAFE-03）。

如实标注（P0-1, 2026-08-15，审计发现 #3 修复）：本机制是**已知灾难模式的
硬阻断 + 全量阻断审计**，不是完备沙箱——它拦截常见的不可逆破坏形态
（rm -rf 根/主目录本体、mkfs、dd 写块设备、fork bomb、curl 管道执行、写系统
关键区、find 删除载荷（按起点目标语义判定）、shell/python 载荷中的上述行为），
不能证明任意命令无副作用。需要更强隔离时请叠加 EXEC_MODE 分级与系统级沙箱
（纵深防御）。确属必要的被阻断操作走提权闭环（escalation_request → web 人工
审批 → 一次性令牌重发；见 tools/escalation.py）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)


# ── P2-5（2026-10-25）：审计哈希链 + 破坏性操作 fail-closed ──
# 目的不是"防篡改"（本地 AI 有写权限，理论上能重写整条链），而是**可检测**：
# 任何一行被改/删/插，verify_audit_chain 会指出断点，事后取证有依据。
def _audit_entry_hash(prev_hash: str, body: dict) -> str:
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + "\n" + payload).encode("utf-8")).hexdigest()


def _last_chain_hash(path: Path) -> str:
    """读文件尾部最后一条带 entry_hash 的记录，避免整文件读取。"""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 16384))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(tail.strip().splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        h = rec.get("entry_hash")
        if isinstance(h, str) and len(h) == 64:
            return h
    return ""


def verify_audit_chain(path: str | Path) -> tuple[bool, int, str]:
    """校验 JSONL 审计链，返回 (ok, 破坏行号(1-based；0=完好), 说明)."""
    p = Path(path)
    if not p.exists():
        return True, 0, "no audit file"
    prev = ""
    for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return False, idx, "invalid json"
        if rec.get("prev_hash") != prev:
            return False, idx, "prev_hash mismatch"
        body = {k: v for k, v in rec.items() if k != "entry_hash"}
        if rec.get("entry_hash") != _audit_entry_hash(prev, body):
            return False, idx, "entry_hash mismatch"
        prev = str(rec["entry_hash"])
    return True, 0, "ok"


_DESTRUCTIVE_SURFACE_RE = re.compile(
    r"(?:\brm\b|\bchmod\b|\bchown\b|\bshred\b|\btruncate\b|\bdd\b|\bmv\b"
    r"|git\s+clean|find\b[^|;]*(?:-delete|-exec)|(?:^|\s)>>?\s*\S)",
    re.IGNORECASE,
)


def _is_destructive_surface(command: str) -> bool:
    """命令是否会改动/删除磁盘状态（用于"必须留审计"的判定，不求完备）."""
    return bool(_DESTRUCTIVE_SURFACE_RE.search(command or ""))



@dataclass(frozen=True)
class BlockDecision:
    """一次灾难性阻断判定结果."""

    blocked: bool
    reason: str = ""
    evidence: str = ""  # 判定依据（FR-SAFE-02 阻断信息透明）


# N6（2026-10-25 第四轮红队）：解释器名单单一事实源。
# 管道/here-doc 正则与 _INTERPRETER_NAMES 曾各自维护、互相漂移（deno/bun 只在
# 管道正则里、载荷集合里没有）。awk/gawk 是常见文本处理器，不进管道直拦名单。
_INTERPRETER_PIPE_EXTRA = ("perl", "ruby", "node", "nodejs", "php", "osascript", "deno", "bun")
_INTERPRETER_PIPE_ALTS = r"(?:ba|z|k|da|a)?sh|python[0-9.]*|" + "|".join(_INTERPRETER_PIPE_EXTRA)

# 不可逆删除 / 系统破坏的最小灾难性模式集合（design.md §2.1.3.5）
_CATASTROPHIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # rm -rf 的路径目标只能经下方完整 token + canonical path 判定:
    # 前缀 regex 不知道 HOME 子路径、.. 或符号链接的真实目标，既可误拦也可漏拦。
    # _scan_tokens 负责 rm、常用执行前缀与嵌套 shell；其余灾难行为正则不变。
    # 格式化 / 建文件系统
    ("mkfs/format 格式化磁盘", re.compile(r"(mkfs\.|mkfs\s|format\s+[a-z]:|newfs)", re.IGNORECASE)),
    # dd 写块设备（P0-1，2026-10-25：允许 `//` 这类重复斜杠，堵住 of=/dev//sda）
    (
        "dd 写入块设备",
        re.compile(
            r"dd\b[^|;]*\bof=//*dev//*(?:sd|hd|vd|nvme|disk|rdisk|mapper|dm-)",
            re.IGNORECASE,
        ),
    ),
    # fork bomb
    ("fork bomb", re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", re.IGNORECASE)),
    # curl/wget 管道直连执行
    ("curl/wget 下载直连执行", re.compile(r"(curl|wget)[^|;]*\|\s*(ba)?sh\b", re.IGNORECASE)),
    # 任意"下载/解码/构造后直连解释器"：审计不可见，等价于黑盒执行（P0-1 复核）
    # 2026-10-25 红队补洞：原正则只认 sh 族，`| base64 -d | python3` 可绕。
    # N6（第四轮）：解释器类名改用 _INTERPRETER_PIPE_ALTS 单一事实源。
    (
        "任意管道直连解释器执行",
        re.compile(
            rf"\|\s*(?:sudo\s+)?(?:{_INTERPRETER_PIPE_ALTS})\b",
            re.IGNORECASE,
        ),
    ),
    # here-doc 交给解释器：脚本体不进 argv，围栏看不到真实动作
    # 2026-10-25 红队补洞：原正则只认 sh 族，`python3 <<'EOF'` 可绕。
    # N6（第四轮）：deno/bun 与管道正则同步（原先 here-doc 名单漏了它们）。
    (
        "here-doc 交给解释器执行",
        re.compile(
            rf"\b(?:{_INTERPRETER_PIPE_ALTS})\b[^|;]*<<",
            re.IGNORECASE,
        ),
    ),
    # 磁盘级抹除/分区（磁盘工具族；macOS 的 diskutil 与 Linux 的 fdisk/gpt/wipefs）
    (
        "磁盘抹除/分区级命令",
        re.compile(
            r"\b(?:diskutil\s+(?:eraseDisk|eraseVolume|partitionDisk|zeroDisk|secureErase|reformat)"
            r"|fdisk|gpt\s+(?:destroy|remove)|parted|wipefs)\b",
            re.IGNORECASE,
        ),
    ),
    # 写系统关键区（P0-1，2026-10-25：从 6 个固定文件名扩展到关键目录；
    # /dev/null 与普通 /dev/std* 不在块设备名单内，仍放行）
    (
        "写入系统关键区",
        re.compile(
            r"(?:>\s*|>>\s*|tee\s+(?:-a\s+)?)"
            r"(?://*(?:etc|boot|System|Library)/\S+"
            r"|//*dev//*(?:sd|hd|vd|nvme|disk|rdisk|mapper|dm-)\w*)",
            re.IGNORECASE,
        ),
    ),
]

# rm -rf 的灾难性目标（变量展开 + ~ 展开后判定，审计发现 #3：$HOME/${HOME}/~ 绕过修复）
# P0（2026-10-26）：补 /Users——macOS 多用户区，语义等价 Linux 的 /home。原先缺失，
# 隔离 HOME（CI 把 HOME 指到 /tmp/xxx）下 rm -rf /Users、rm -rf /Users/*、
# rmSync(/Users/<u>/…)、Deno.remove("/Users/<u>") 全部漏拦；真实 HOME 下靠下方
# "HOME 祖先"分支兜住纯属环境耦合侥幸。全平台生效：Linux 上 /Users 非真实系统
# 目录、无正当删除场景，误拦风险为零。
_SYSTEM_DIRS = ("/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/var", "/home", "/Users")

# P0-1（2026-10-25）：凭证目录本体被删即不可逆地失去身份/密钥，
# 不再享受 HOME 子路径豁免。
_CREDENTIAL_SUBDIRS = (".ssh", ".aws", ".gnupg", ".docker", ".kube")

# 主机系统顶层目录本体：macOS 的 /private 等不在 _SYSTEM_DIRS 中，
# 但 `rm -rf /private` 与删 /etc 同级灾难（/etc、/var 只是它的子目录）。
_HOST_TOPLEVEL_PROTECTED = (
    "/private",
    "/System",
    "/Library",
    "/Applications",
    "/Volumes",
    "/cores",
)

# 临时目录根：目标的字面拼写（相对/绝对）不应改变"临时区可清理"的判定。
_TEMP_ROOTS = ("/private/var/folders", "/private/tmp", "/tmp")

# glob 元字符：`rm -rf /*` 这类目标不做展开，只按字面前缀判定危险度。
_GLOB_CHARS = re.compile(r"[*?\[]")

# python -c 载荷的不可逆破坏分级（审计发现 #3 补洞 + EVO-20260923-c58a0bb1 修正 3）:
# - 递归级（rmtree/removedirs/内嵌 rm -rf/mkfs/dd→块设备）: 无条件硬拦——
#   灾难规模与 shell 层同构，不因拼写形式（python vs rm）改变判定。
# - 单文件级（os.remove/os.unlink/os.rmdir/Path(...).unlink/rmdir）: 仅当
#   **字面目标**命中灾难目录时拦；与 shell 层 `rm /tmp/x` 放行对齐——
#   单文件删除非灾难规模，拦截不应取决于载荷语言。
_PY_RECURSIVE_DANGER = re.compile(
    r"(shutil\.rmtree|os\.removedirs|rm\s+-[a-z]*r[a-z]*f|mkfs\b|dd\b.*of=/dev/)",
    re.IGNORECASE,
)
# 单文件删除调用 + 提取首个字符串字面量实参（动态目标不判——单文件规模）
_PY_SINGLE_FILE_CALL = re.compile(
    r"(?:os\.(?:remove|unlink|rmdir)|\.(?:unlink|rmdir))\s*\(\s*(['\"])(.*?)\1",
    re.IGNORECASE,
)
# 递归删除调用 + 首个字符串字面量目标（P0-1 复核：区分"调用"与"字符串里的文本"）
_PY_RMTREE_CALL = re.compile(
    r"(?:shutil\.rmtree|os\.removedirs)\s*\(\s*(['\"])(.*?)\1",
    re.IGNORECASE,
)
# 递归删除"调用点"（不看参数）——沿用项目既有策略：递归级调用一律拦，
# 因为目标可能是动态拼接；先剥掉字符串字面量，避免 print("...rmtree(...)") 误判。
_PY_RMTREE_CALL_SITE = re.compile(r"(?:shutil\.rmtree|os\.removedirs)\s*\(", re.IGNORECASE)
_PY_STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", re.DOTALL)
# 真正把字符串交给 shell 的调用点；没有它，"载荷里出现删除命令"只是数据
_PY_SHELL_CALL = re.compile(
    r"(?:os\.(?:system|popen)|subprocess\.(?:run|call|Popen|check_output|check_call)|pty\.spawn)",
    re.IGNORECASE,
)
# N9（第四轮红队）：shell 调用的字符串实参（整串交给 shell 执行的命令行）
_PY_SHELL_CALL_LITERAL = re.compile(
    r"(?:os\.(?:system|popen)|subprocess\.(?:run|call|Popen|check_output|check_call)"
    r"|pty\.spawn)\s*\(\s*(?P<q>['\"])(?P<arg>.*?)(?P=q)",
    re.IGNORECASE | re.DOTALL,
)

# 复合命令切分边界（审计发现 #3：;/&&/||/| 拼接绕过修复——见 _split_tokenized）


def _normalize_ansi_c_quotes(command: str) -> str:
    """把 bash `$'...'`（ANSI-C quoting）还原为其字面内容，再做判定.

    终审红队 M1（2026-10-25）：`sh -c $'rm -rf /etc'` 的分词结果是单个
    `$'rm -rf /etc'` token，载荷递归看到的是带 `$'` 前缀的裸词，既不命中
    rm 正则，也在旧实现里触发 TypeError。这里只做引号剥离与常见转义还原，
    不执行任何代码；还原后统一走原有正则+分词两层判定。
    """

    def _repl(m: re.Match[str]) -> str:
        inner = (
            m.group(1)
            .replace("\\'", "'")
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\r", "\r")
        )
        # 还原成"一个带引号的 shell 词"，保持 argv 结构不变：
        # `sh -c $'rm -rf /etc'` 的载荷仍是单个 token，交给 _shell_payload 递归。
        escaped = inner.replace("\\", "\\\\").replace("'", "\\'")
        return "'" + escaped + "'"

    return re.sub(r"\$'((?:[^'\\]|\\.)*)'", _repl, command)


def _expand(command: str) -> str:
    """$VAR/${VAR} + ~ 展开（判定在展开后的真实目标上进行）.

    注意 os.path.expanduser 只展开字符串开头的 ~——命令中 ~ 出现在空白/运算符后
    （rm -rf ~/data），需按词边界补展开（词中 hello~world 不动，防误改）。
    """
    # P0-1 复核：`rm${IFS}-rf${IFS}/etc` 用 IFS 拼词绕过空白分隔——先归一为空格
    # 再进分词；这是 shell 语义里的"空白"，不是普通变量。
    command = re.sub(r"\$\{IFS\}|\$IFS\b", " ", command)
    expanded = os.path.expandvars(command)
    home = os.path.expanduser("~")
    if "~" in expanded and home != "~":
        expanded = re.sub(r"(^|(?<=[\s;|&'\"=]))~(?=[/\s'\"]|$)", lambda m: m.group(1) + home, expanded)
    return expanded


def _newline_split_normalize(command: str) -> str:
    """引号外换行（\\n、\\r）归一为 ";"（N1，2026-10-25 第四轮红队）.

    shell 语义里换行与 ";" 同为命令分隔符；旧逻辑把它当空白，
    `cd /etc\\nrm -rf .` 合并成一组后 rm 不在执行位。引号内换行保留
    （那是载荷文本，由载荷递归层再归一）；反斜杠转义按 shell 规则跳一字
    （单引号内不转义，双引号内仅 \\" \\\\ \\$ \\`）。
    """
    out: list[str] = []
    i = 0
    n = len(command)
    quote: str | None = None
    while i < n:
        ch = command[i]
        if quote == '"' and ch == "\\" and i + 1 < n and command[i + 1] in '"\\$`':
            out.append(ch)
            out.append(command[i + 1])
            i += 2
            continue
        if quote is None and ch == "\\" and i + 1 < n:
            out.append(ch)
            out.append(command[i + 1])
            i += 2
            continue
        if quote is None and ch in "'\"":
            quote = ch
            out.append(ch)
        elif quote is not None and ch == quote:
            quote = None
            out.append(ch)
        elif quote is None and ch in "\n\r":
            out.append(";")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _split_tokenized(command: str) -> list[list[str]]:
    """按 ; && || | 切分复合命令为 token 组（引号语义保留——载荷内的 ; 不切断）.

    shlex punctuation_chars 模式把 ;|& 作为独立边界 token；引号不配对等异常
    回退纯字符切分（保守：切错了也逐段过同一套判定，不漏整体正则层）。
    """
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";|&")
        lex.whitespace_split = True
        raw = list(lex)
    except ValueError:
        return [_tokens(p) for p in re.split(r"&&|\|\||[;|]", command) if p.strip()]
    groups: list[list[str]] = []
    cur: list[str] = []
    for t in raw:
        if re.fullmatch(r"[;&|]+", t):
            if cur:
                groups.append(cur)
                cur = []
        else:
            cur.append(t)
    if cur:
        groups.append(cur)
    return groups


def _tokens(sub: str) -> list[str]:
    """shlex 分词（引号归并）；分词失败回退空白切分（fail-open 到保守判定）."""
    try:
        return shlex.split(sub, posix=True)
    except ValueError:
        return sub.split()


def _rm_recursive_force(tokens: list[str]) -> bool:
    """rm 标志聚合判定：-r/-f 可分散为多个标志位（-r -f）或合并（-rf/-fr）."""
    recursive = force = False
    for t in tokens[1:]:
        if t == "--":
            break
        if t.startswith("--"):
            recursive = recursive or t == "--recursive"
            force = force or t == "--force"
        elif t.startswith("-") and len(t) > 1:
            body = t[1:].lower()
            recursive = recursive or "r" in body
            force = force or "f" in body
    return recursive and force


def _rm_targets(tokens: list[str]) -> list[str]:
    """rm 的非标志参数（-- 分隔符之后的全部算目标，分隔符本身不算）."""
    out: list[str] = []
    seen_sep = False
    for t in tokens[1:]:
        if seen_sep:
            out.append(t)
        elif t == "--":
            seen_sep = True
        elif not t.startswith("-"):
            out.append(t)
    return out


def _cf(path: str) -> str:
    """路径比较键：normpath + casefold（macOS 默认卷大小写不敏感，/Users/YYJ 即家目录）."""
    return os.path.normpath(path or "/").casefold()


def _same(a: str, b: str) -> bool:
    return _cf(a) == _cf(b)


def _within(path: str, root: str) -> bool:
    """path 是否等于 root 或位于其子树（大小写归一；root='/' 仅匹配根自身）."""
    p, r = _cf(path), _cf(root)
    if r == "/":
        return p == "/"
    return p == r or p.startswith(r + "/")


_CWD_UNKNOWN = "\x00cwd-unknown"
# 写入块设备的路径（realpath 归一后匹配；/dev/null 等字符设备不在此列）
_DEVICE_PATH_RE = re.compile(
    r"^/dev/(?:sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+|disk\d+|rdisk\d+|mapper/|dm-\d+|md\d+)"
)


def _normalized_device_target(token: str) -> str | None:
    """token 若指向块设备节点则返回归一化路径（dd of=/dev/./disk0 → /dev/disk0）."""
    raw = token[3:] if token.startswith("of=") else token
    if not raw.startswith("/") or "/dev" not in raw:
        return None
    try:
        real = os.path.realpath(raw)
    except (OSError, ValueError):
        real = raw
    if _DEVICE_PATH_RE.match(real):
        return real
    return None


def _is_dangerous_rm_target(target: str, cwd: str | None = None) -> bool:
    """根 / 主目录本体 / 系统关键目录（含子路径）.

    EVO-20260923-c58a0bb1（accepted）修正 1: 主目录**子路径**不再按
    拼写前缀一票否决——同一目标写成 `./dir` 放行、写成绝对路径就拦，
    拦截结果取决于拼写而非目标语义，对诚实工作流只制造中断，对
    恶意主体无防护增益。主目录**本体**与系统关键目录（含子路径）
    保持不可逆全量定位拦。
    工作区相对路径（./build 等）与 /tmp 不在此列——边界极小纪律，
    会话内正常清理由 AI 自主裁决，程序只拦不可逆系统级破坏。
    """
    t = target.rstrip("/")
    if t in ("", "/") or "\x00" in t:
        return True
    # P0-1 复核补洞：`cd / && <删除> *` 这类复合命令里，相对目标必须按
    # **该段执行时的有效 cwd** 解析；否则 realpath(".") 永远指向进程初始 cwd，
    # 删根命令被当成"工作区内清理"放行。
    if cwd == _CWD_UNKNOWN and t and not os.path.isabs(t):
        # 2026-10-25 红队补洞：`cd $(echo /etc) && rm -rf .` / pushd / popd 之后
        # cwd 静态不可知，相对目标无法证明安全（"." 可能就是 /etc）→ fail-closed。
        return True
    if cwd is not None and t and not os.path.isabs(t):
        t = os.path.join(cwd, t)
    # Realpath (strict=False) 解析存在的 symlink 前缀、相对路径和 ..，
    # 不做任何磁盘写入。/etc -> /private/etc 与 /var -> /private/var
    # 等 OS 别名必须被同一权威目标判定覆盖。
    canonical = os.path.realpath(t).rstrip("/") or "/"
    home = os.path.realpath(os.path.expanduser("~")).rstrip("/") or "/"
    if canonical == "/" or _same(canonical, home):
        return True

    # —— P0-1（2026-10-25）新增语义：不只看"是不是根"，还看"删掉会失去什么" ——
    # 1) 凭证目录：~/.ssh 等被删即不可逆地失去身份，不再享受 HOME 子路径豁免
    for name in _CREDENTIAL_SUBDIRS:
        cred = os.path.join(home, name)
        if _within(canonical, cred):
            return True
    cwd_real = os.path.realpath(cwd or os.getcwd()).rstrip("/") or "/"
    # 4) cwd 的祖先（如从 repo 内 `rm -rf ..`）：一次删除抹掉当前项目。
    #    必须早于临时区豁免：临时区内的 `rm -rf ..` 同样会一次抹掉当前工作
    #    目录的父级（含其它会话/进程的数据），不属于"会话内清理"。
    if cwd_real != "/" and not _same(canonical, cwd_real) and _within(cwd_real, canonical):
        return True
    # 5) 临时区目标：判定与字面拼写（相对/绝对）无关，一律视为会话内可清理。
    #    必须早于 /private 子树判定——否则 /private/tmp/* 全被当成系统区误杀；
    #    也必须早于下方 3) HOME 祖先判定（P0，2026-10-26）：CI/测试常把 HOME
    #    隔离进 /tmp（如 /tmp/cihome-fix），此时 /private/tmp 是 HOME 的祖先，
    #    若 3) 先行，cd /tmp 后的 rm -rf * 会被误判为"删 HOME 祖先"而拦。
    #    HOME 本体与凭证目录已由上方判定先拦，不受此顺序影响。
    for root in (tempfile.gettempdir(), *_TEMP_ROOTS):
        root_real = os.path.realpath(root).rstrip("/") or "/"
        if root_real != "/" and _within(canonical, root_real):
            return False
    # 3) HOME 的祖先（如 /Users）：一次删除抹掉整台机器的多用户区。
    #    排在 5) 之后（P0，2026-10-26）：隔离 HOME 位于临时区内时，其祖先链是
    #    临时区根——属"会话内可清理"面（5 已放行），不按灾难拦。
    if home != "/" and not _same(canonical, home) and _within(home, canonical):
        return True
    # 2) 主机系统顶层目录本体（macOS 的 /private 等 OS 别名不在 _SYSTEM_DIRS）
    # P0-1 复核：/System/Library、/Library/Preferences 等同属灾难面，按子树判定
    if any(_within(canonical, root) for root in _HOST_TOPLEVEL_PROTECTED):
        return True
    # 只有真正 canonical HOME 严格子路径获豁免。HOME/../../etc、
    # HOME 内指向 /etc 的符号链接不会被原始字符串前缀误放行。
    if home != "/" and not _same(canonical, home) and _within(canonical, home):
        return False
    # 原有契约允许执行目录内的 ./build、find . 和普通相对文件清理。
    # pytest/macOS 的工作目录可能在 /private/var/... 临时沙箱下；
    # 不应因为 OS 临时目录的父路径属于 /var 就把局部相对清理全部误拦。
    # 只豁免真实目标仍在 cwd 内（无 '..' 逃逸、无指向系统目录的 symlink）
    # 且 cwd 本身不是受保护系统区的相对操作。
    if not os.path.isabs(t):
        cwd = os.path.realpath(cwd or os.getcwd()).rstrip("/") or "/"
        local_target = os.path.normpath(os.path.join(cwd, t))
        if (
            cwd != "/"
            and _same(canonical, local_target)
            and _within(canonical, cwd)
        ):
            temp_root = os.path.realpath(tempfile.gettempdir()).rstrip("/") or "/"
            temp_scoped = cwd == temp_root or cwd.startswith(temp_root + "/")
            protected_cwd = any(_within(cwd, os.path.realpath(d)) for d in _SYSTEM_DIRS)
            if temp_scoped or not protected_cwd:
                return False
    return any(_within(canonical, os.path.realpath(d)) for d in _SYSTEM_DIRS)


# 第四轮红队 M3（2026-10-25）：少数系统文件的权限/属主被改就会直接锁死主机
# （登录、sudo、SSH 配置）。它们不适用"必须是 -R"的前提。
_CRITICAL_SYSTEM_FILES = (
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/pam.d",
    "/etc/ssh/sshd_config",
    "/etc/hosts",
    "/etc/resolv.conf",
    "/private/etc/passwd",
    "/private/etc/shadow",
    "/private/etc/sudoers",
    "/private/etc/pam.d",
)


def _is_critical_system_file(target: str, cwd: str | None = None) -> bool:
    """目标是否为系统关键文件（含其子树，realpath 归一）."""
    t = target.rstrip("/")
    if not t:
        return False
    if cwd == _CWD_UNKNOWN and not os.path.isabs(t):
        return False
    if cwd is not None and not os.path.isabs(t):
        t = os.path.join(cwd, t)
    canonical = os.path.realpath(t).rstrip("/")
    return any(canonical == f or canonical.startswith(f + "/") for f in _CRITICAL_SYSTEM_FILES)


def _cwd_after_cd(tokens: list[str], cwd: str | None) -> str | None:
    """返回执行到下一段时的有效 cwd（仅识别简单 `cd/pushd <path>`）.

    无法静态解析时返回 `_CWD_UNKNOWN`（不是 None）：下游据此对相对目标
    fail-closed。2026-10-25 红队补洞：
      - `cd $(echo /etc) && rm -rf .`：命令替换目标不可知；
      - `pushd /etc; rm -rf .`：pushd 同样改 cwd；
      - `popd`：回到栈中路径，静态不可知。
    旧实现这些情况一律返回 None，下游把 None 当"按进程初始 cwd 判定"，
    `.` 于是被当成工作区内清理而放行。
    """
    toks = _execution_tokens(tokens)
    if not toks:
        return cwd
    cmd = toks[0]
    if cmd == "popd":
        return _CWD_UNKNOWN
    if cmd not in {"cd", "pushd"}:
        return cwd
    if cwd == _CWD_UNKNOWN:
        return _CWD_UNKNOWN
    operands = [t for t in toks[1:] if not t.startswith("-")]
    if len(operands) != 1:
        return _CWD_UNKNOWN
    target = operands[0]
    if (
        "$" in target
        or "`" in target
        or target.startswith("(")
        or target == "-"
        or _GLOB_CHARS.search(target)
    ):
        return _CWD_UNKNOWN
    base = cwd or os.getcwd()
    return os.path.realpath(os.path.join(base, os.path.expanduser(target)))


def _recursive_flag(tokens: list[str]) -> bool:
    """chmod/chown/chgrp 是否带递归标志（-R / --recursive）."""
    return any(
        t == "--recursive" or (t.startswith("-") and not t.startswith("--") and "R" in t[1:])
        for t in tokens[1:]
    )


def _glob_dangerous_target(target: str, cwd: str | None = None) -> bool:
    """通配目标按字面前缀判定危险度（P0-1，2026-10-25）.

    `rm -rf /*`、`rm -rf /Users/*`、`rm -rf ~/*` 的字面目标本身不存在，
    realpath 判定会全部放行。这里只取第一个元字符之前的前缀，把它当作
    真实目录来判定——不展开通配（展开会随磁盘内容变化，判定不可复现）。

    裸通配（`*`、`?`）没有前缀，危险度取决于 cwd：cwd 为 `/` 或 HOME 时
    `.` 会命中 `_is_dangerous_rm_target` 的根/主目录分支。
    """
    if not _GLOB_CHARS.search(target):
        return False
    head = _GLOB_CHARS.split(target, maxsplit=1)[0]
    base = head or "." if head.endswith("/") or head == "" else os.path.dirname(head) or "."
    return _is_dangerous_rm_target(base, cwd)


def _split_grouping(tokens: list[str]) -> list[str]:
    """把 `(cd /x` / `rm -rf .)` / `{` 这类分组符从词上剥掉（只影响判定视图）."""
    out: list[str] = []
    for t in tokens:
        while t and t[0] in "({":
            t = t[1:]
        # 只剥"纯分组后缀"：`rm -rf .)` 要剥，`print('rm -rf /')` 不能剥
        if t and t[-1] in ")}" and "'" not in t and '"' not in t and t.count("(") == 0 and t.count("{") == 0:
            t = t[:-1]
        if t:
            out.append(t)
    return out


# 条件/循环关键字：它们不是被执行命令本身，剥掉后继续看真正的命令
_LEAD_KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "time", "!"})
# 包装器：选项解析后剩下的才是被包装命令
_WRAPPERS = frozenset({"timeout", "nice", "stdbuf", "watch", "xargs"})
# 需要吞掉一个参数的短选项（-n 5 / -s KILL / -I {} …）
_WRAPPER_OPTS_WITH_ARG = frozenset({"-n", "-s", "-o", "-e", "-I", "-L", "-P", "-d", "-a", "-u", "-g"})
# N3（第四轮红队）：env 剥离选项后首 token 需要重新分词的特征（空白/元字符）
_ENV_SPLIT_HINT = re.compile(r"[\s;&|<>`$(*?]")
# env -S 载荷无法分词时的哨兵 token（_scan_tokens 识别后按不可判定 fail-closed）
_ENV_PAYLOAD_UNPARSABLE = "\x00env-payload-unparsable"


def _execution_tokens(tokens: list[str]) -> list[str]:
    """剥掉执行前缀（赋值、包装器、分组符、条件关键字），返回真正被执行的命令词.

    这仍是"已知形态"归一，不是 shell 解释器（静态判定不可能穷尽动态拼装）。
    因此对无法归一的形态（变量 argv0 + 递归删除标志、eval/here-doc）走 fail-closed，
    而不是假装看清了。P0-1 复核新增：X=1 前缀、busybox/timeout/nice/stdbuf/watch/xargs、
    `(`/`{`/if-then-do-while 关键字。
    """
    parts = _split_grouping(list(tokens))
    for _ in range(12):
        if not parts:
            break
        # 前缀赋值：X=1 rm -rf /etc
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[0]):
            parts = parts[1:]
            continue
        cmd = os.path.basename(parts[0]).lower()
        if cmd in {"command", "builtin", "exec", "nohup"} or cmd in _LEAD_KEYWORDS:
            parts = parts[1:]
        elif cmd == "eval":
            # eval 把余下参数拼回一条命令：交回外层按整串重新分词
            return ["eval " + " ".join(parts[1:])] if len(parts) > 1 else []
        elif cmd == "sudo":
            idx = 1
            while idx < len(parts):
                opt = parts[idx]
                if opt == "--":
                    idx += 1
                    break
                if opt in {"-u", "-g", "-h", "-p", "-C", "-r", "-t"}:
                    idx += 2
                elif opt.startswith("-"):
                    idx += 1
                else:
                    break
            parts = parts[idx:]
        elif cmd == "env":
            # N3（2026-10-25 第四轮红队）：env -S/--split-string 把一个字符串
            # 当**完整命令行**执行——`env -S 'rm -rf /etc'` 剥离后剩单个含空白
            # token，rm 永远不在执行位。-S 载荷语义与 sh -c 同构，交给 eval 式
            # 整串重扫（;&&| 切分语义由 _scan_command 重建）；无法分词按
            # 不可静态判定 fail-closed（哨兵 token 交 _scan_tokens 阻断）。
            idx = 1
            while idx < len(parts):
                opt = parts[idx]
                if opt == "--":
                    idx += 1
                    break
                if opt in {"-u", "--unset"}:
                    idx += 2
                elif opt == "-S" or opt == "--split-string":
                    payload = parts[idx + 1] if idx + 1 < len(parts) else ""
                    return ["eval " + payload] if payload else [_ENV_PAYLOAD_UNPARSABLE]
                elif opt.startswith("-S") or opt.startswith("--split-string="):
                    payload = opt.split("=", 1)[1] if "=" in opt else opt[2:]
                    return ["eval " + payload] if payload else [_ENV_PAYLOAD_UNPARSABLE]
                elif opt.startswith("-") or "=" in opt:
                    idx += 1
                else:
                    break
            parts = parts[idx:]
            # 兜底：剥离后首 token 仍含空白/元字符（整条命令行被打包成单
            # token 的其它形态）→ 同样 eval 式整串重扫；无法分词 fail-closed。
            if parts and _ENV_SPLIT_HINT.search(parts[0]):
                try:
                    shlex.split(parts[0], posix=True)
                except ValueError:
                    return [_ENV_PAYLOAD_UNPARSABLE]
                return ["eval " + parts[0]]
        elif cmd == "busybox":
            parts = parts[1:]  # 下一个词是 applet 名（rm/sh/...）
        elif cmd in _WRAPPERS:
            idx = 1
            while idx < len(parts):
                opt = parts[idx]
                if opt == "--":
                    idx += 1
                    break
                if opt.startswith("-"):
                    idx += 2 if opt in _WRAPPER_OPTS_WITH_ARG and idx + 1 < len(parts) else 1
                    continue
                if cmd in {"timeout", "watch", "nice"} and re.fullmatch(r"[0-9.]+[smhd]?", opt):
                    idx += 1
                    continue
                break
            parts = parts[idx:]
        else:
            break
    if parts:
        parts[0] = os.path.basename(parts[0])
    return parts


# N6（第四轮）：bun/deno 补入（原先只在管道正则里，名单漂移）；
# awk/gawk 在此集合内但刻意不进 _INTERPRETER_PIPE_ALTS（文本处理常客）。
_INTERPRETER_NAMES = frozenset(
    {"ruby", "node", "nodejs", "perl", "awk", "gawk", "php", "osascript", "bun", "deno"}
)
_INTERPRETER_EVAL_FLAGS = frozenset({"-e", "-E", "--eval", "-c"})
# N5（第四轮）：php -r 直接执行代码串；ruby 的 -r 是 require（吃参数），不通用
_PHP_EVAL_FLAGS = frozenset({"-r"})
# 2026-10-25 红队补洞：补 rmSync/rm_rf/fs.rm 等"递归删除 API 调用点"，
# 否则 node -e / ruby -e 的等价删除不受载荷判定覆盖。
_PAYLOAD_DESTRUCTIVE = re.compile(
    r"(?:\brm\s+-|rmtree|removedirs|rmSync|rm_rf|rm_r\b|unlinkSync|removeSync|fs\.rm"
    r"|Deno\.remove|unlink|os\.remove|shutil\.|system\s*\(|exec[a-z]*\s*\(|spawn[a-z]*\s*\(|popen"
    r"|\bchmod\b|\bchown\b|\bchgrp\b)",
    re.IGNORECASE,
)
# 递归删除"调用点"（不看参数）：目标可能动态拼接，命中即 fail-closed
_RECURSIVE_CALL_SITE = re.compile(
    r"(?:rmtree|removedirs|rmSync|rm_rf|rm_r\b|fs\.rm(?:Sync)?|Deno\.remove(?:Sync)?|rm\s+-[a-z]*r)",
    re.IGNORECASE,
)
# 载荷里的目标拼接/变量：静态不可判定，与递归删除调用点同时出现即拦
_DYNAMIC_TARGET_HINT = re.compile(r"['\"]\s*(?:\+|\.)\s*['\"]|\$\{?[A-Za-z_(]|#\{")
_SHELL_NAMES = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "ksh93", "mksh", "ash", "fish", "yash", "tcsh", "csh"}
)
_QUOTED = re.compile(r"'([^']{1,200})'|\"([^\"]{1,200})\"")


def _interpreter_payload(tokens: list[str]) -> str | None:
    """取解释器 -e/-c 载荷（python 另有专门分支，这里覆盖 ruby/node/perl/awk 等）.

    N4（第四轮红队）：awk/gawk 无 -e 也执行——首个非选项操作数就是程序文本
    （`awk 'BEGIN{system("rm -rf /etc")}'`），按载荷判定。
    N5（第四轮）：php -r 执行代码串（-r 仅对 php 视为 eval 标志）。
    N6（第四轮）：deno eval '<code>' 子命令形态；bun -e 走通用标志分支。
    """
    if not tokens:
        return None
    name = os.path.basename(tokens[0]).lower()
    if name not in _INTERPRETER_NAMES:
        return None
    flags = _INTERPRETER_EVAL_FLAGS | (_PHP_EVAL_FLAGS if name == "php" else frozenset())
    if name == "deno":
        for i, t in enumerate(tokens[1:], 1):
            if t == "eval":
                return " ".join(tokens[i + 1:]) if i + 1 < len(tokens) else None
        return None
    for i, t in enumerate(tokens[1:], 1):
        if t in flags and i + 1 < len(tokens):
            return " ".join(tokens[i + 1:])
        if t.startswith("-e") and len(t) > 2:
            return t[2:]
        if name == "php" and t.startswith("-r") and len(t) > 2:
            return t[2:]
    # N4：awk/gawk 裸程序——首个非选项操作数（其后操作数是数据文件）
    if name in ("awk", "gawk"):
        for t in tokens[1:]:
            if t == "--":
                continue
            if not t.startswith("-"):
                return t
    return None


def _paren_args(payload: str, start: int) -> str | None:
    """从 start 起提取调用点括号内实参文本（N8，2026-10-25 第四轮红队）.

    start 跳过空白后不是 "(" → None（括号省略调用 / shell 文本形态，
    交由通用字面量与分词判定）；括号不闭合 → 返回剩余全文（截断载荷
    按保守面继续判定）。
    """
    i = start
    n = len(payload)
    while i < n and payload[i] in " \t\r\n":
        i += 1
    if i >= n or payload[i] != "(":
        return None
    depth = 0
    for j in range(i, n):
        ch = payload[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return payload[i + 1:j]
    return payload[i + 1:]


def _payload_deletes_dangerous(payload: str, cwd: str | None) -> str | None:
    """载荷里出现破坏动词 + 灾难目标字面量 → 返回命中的目标（否则 None）."""
    if not _PAYLOAD_DESTRUCTIVE.search(payload):
        return None
    # 2026-10-25 红队补洞：目标靠拼接/变量构造时，字面量判定看不见真实路径
    # （`system("rm","-rf","/e"."tc")`），按不可静态判定 fail-closed。
    if _DYNAMIC_TARGET_HINT.search(payload):
        return "载荷目标含动态拼接/变量（不可静态判定）"
    # N8（2026-10-25 第四轮红队）：递归删除调用点只看**括号内实参**的字面量
    # ——`FileUtils.rm_rf(Dir.home)` 曾因无关字符串 "fileutils" 使"目标非字面量
    # fail-closed"失效。括号内无任何字面量 → fail-closed。
    for m in _RECURSIVE_CALL_SITE.finditer(payload):
        inner = _paren_args(payload, m.end())
        if inner is None:
            # 括号省略形态（Ruby `rm_rf Dir.home`）：取调用点后的实参片段
            tail = payload[m.end():].lstrip()
            seg = re.split(r"[);\n]", tail, maxsplit=1)[0]
            seg_wo = re.sub(r"\{[^{}]*\}", "", _QUOTED.sub("", seg))
            if re.search(r"[A-Za-z_$@]", seg_wo):
                return "递归删除调用点参数含动态表达式（括号省略）"
            continue
        inner_literals = [mm.group(1) or mm.group(2) or "" for mm in _QUOTED.finditer(inner)]
        if not inner_literals:
            return "递归删除调用点但目标非字面量"
        # 第五轮红队（2026-10-25）：括号内"字面量 + 动态表达式"混排
        # （`rm_rf Dir.home.join("x")`）曾因存在小字面量 "x" 被判为静态安全。
        # 去掉字面量与选项对象（{recursive:true}）后仍有标识符/变量 → fail-closed。
        residual = _QUOTED.sub("", inner)
        residual = re.sub(r"\{[^{}]*\}", "", residual)
        if re.search(r"[A-Za-z_$@]", residual):
            return "递归删除调用点参数含动态表达式"
        for lit in inner_literals:
            if lit and _is_dangerous_rm_target(_expand(lit), cwd):
                return lit
    for m in _QUOTED.finditer(payload):
        literal = m.group(1) or m.group(2) or ""
        if literal and _is_dangerous_rm_target(_expand(literal), cwd):
            return literal
    # 无引号形态：按词取绝对路径再判定
    for tok in re.split(r"\s+", payload):
        tok = tok.strip("'\",()[]{};")
        if (tok.startswith("/") or tok.startswith("~")) and _is_dangerous_rm_target(
            _expand(tok), cwd
        ):
            return tok
    return None


def _find_start_points(tokens: list[str]) -> list[str]:
    """find 的起点路径（EVO-20260923-c58a0bb1 修正 2）.

    POSIX 语义: 起点是 find 后、表达式区前的非选项参数；-H/-L/-P/-O/-D
    为可前置的全局选项。遇到第一个非全局选项的 '-' token 即进入表达式区，
    其后的 -newer/-name 等参数不再误判为起点。无显式起点 = 隐含 '.'。
    """
    starts: list[str] = []
    for t in tokens[1:]:
        if t in ("-H", "-L", "-P") or re.fullmatch(r"-O\d?", t) or t.startswith("-D"):
            continue
        if t.startswith("-"):
            break
        starts.append(_expand(t))
    return starts or ["."]


def _tar_remove_files_targets(tokens: list[str]) -> list[str]:
    """tar --remove-files 的被删源视图（N10，2026-10-25 第四轮红队）.

    -C <dir>（含捆绑短选项串里的 C）改变其后成员的解析根；-f/--file 的
    归档参数不是被删源。返回待判定目标：最后一个 -C 目录 + 各成员按其
    生效 -C 解析后的路径。
    """
    rest = tokens[1:]
    i = 0
    n = len(rest)
    cdir: str | None = None
    members: list[tuple[str, str | None]] = []
    while i < n:
        t = rest[i]
        if t == "--":
            members.extend((u, cdir) for u in rest[i + 1:])
            break
        if t in ("-C", "--directory") and i + 1 < n:
            cdir = rest[i + 1]
            i += 2
            continue
        if t.startswith("--directory="):
            cdir = t.split("=", 1)[1]
            i += 1
            continue
        if t == "--file" or t.startswith("--file="):
            i += 1  # 归档参数（= 形式自带）不是被删源
            continue
        if t.startswith("--"):
            i += 1
            continue
        if t.startswith("-") and len(t) > 1:
            body = t[1:]
            i += 1
            skip_arg = False
            k = 0
            while k < len(body):
                ch = body[k]
                k += 1
                if ch == "f":
                    if k >= len(body):
                        skip_arg = True  # 归档文件在下一词
                    break
                if ch == "C":
                    if k >= len(body) and i < n:
                        cdir = rest[i]
                        skip_arg = True
                    break
            if skip_arg:
                i += 1
            continue
        members.append((t, cdir))
        i += 1
    out: list[str] = []
    if cdir:
        out.append(cdir)
    for member, base in members:
        out.append(member if (os.path.isabs(member) or not base) else os.path.join(base, member))
    return out


def _shell_payload(tokens: list[str]) -> str | None:
    """sh 族（sh/bash/zsh/dash/ksh/fish…）的 `-c` 载荷字符串.

    2026-10-25 红队补洞：原实现只认 sh/bash/zsh 的独立 `-c`，
    `dash -c`、`ksh -c`、`bash -lc` 都能绕；改为"shell 名集合 + 含 c 的短选项"。
    """
    if not tokens:
        return None
    name = os.path.basename(tokens[0]).lower()
    if name not in _SHELL_NAMES:
        return None
    for i, tok in enumerate(tokens[1:], start=1):
        if tok == "--":
            break
        if tok == "-c" or (tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:]):
            if i + 1 < len(tokens):
                return tokens[i + 1]
            return None
    return None


def _python_payload(tokens: list[str]) -> str | None:
    """python/python3/python3.13… -c 的载荷字符串."""
    if not tokens:
        return None
    name = os.path.basename(tokens[0]).lower()
    if not re.fullmatch(r"python[0-9.]*", name):
        return None
    if "-c" in tokens:
        idx = tokens.index("-c")
        if idx + 1 < len(tokens):
            return tokens[idx + 1]
    return None


class CatastrophicGuard:
    """灾难性行为判定与硬阻断（FR-SAFE 系列）.

    Args:
        audit_dir: 阻断审计目录（data/audit）；None = 不落盘（测试/轻量场景）。
                   非 None 时每次阻断追加 data/audit/safety_blocks.jsonl（FR-SAFE-02 透明）。
    """

    def __init__(self, audit_dir: Path | str | None = None) -> None:
        self._audit_dir = Path(audit_dir) if audit_dir else None

    def guard(self, tool_name: str, args: dict, workdir: str | None = None) -> BlockDecision | None:
        """对工具调用做灾难性判定.

        Args:
            tool_name: 工具名.
            args: 工具参数（如 execute_command 的 command 字段）.
            workdir: 命令实际执行目录（相对目标必须按它解析，不能按进程 cwd）.

        Returns:
            BlockDecision(blocked=True) 命中灾难性模式；
            None 未命中（放行）。
        """
        command = ""
        if tool_name == "execute_command":
            command = str(args.get("command", "") or "")
        elif tool_name in {"delete_file", "write_file", "edit_file", "append_file"}:
            path = str(args.get("path", "") or "")
            command = f"{tool_name} {path}"
        if not command.strip():
            return None

        effective_cwd = (
            workdir
            or str(args.get("workdir") or args.get("cwd") or "").strip()
            or None
        )
        decision = self._scan_command(command, tool_name, depth=0, cwd=effective_cwd)
        if decision is not None and decision.blocked:
            self._audit_block(tool_name, command, decision)
            return decision

        # P2-5（2026-10-25）：破坏性命令放行前必须留下审计；写不进就 fail-closed。
        # 只在配置了 audit_dir 时生效——默认 CatastrophicGuard() 不带审计目录，
        # 纯判定场景（单测、离线扫描）行为不变。
        if (
            self._audit_dir is not None
            and _is_destructive_surface(command)
            and not self._audit_allow(tool_name, command)
        ):
            return BlockDecision(
                blocked=True,
                reason="破坏性操作的审计记录无法写入，已按 fail-closed 阻断（建议书 P2-5）。",
                evidence=f"命令: {command[:200]}; 审计目录: {self._audit_dir}",
            )
        return decision

    def _scan_command(
        self, command: str, tool_name: str, depth: int, cwd: str | None = None
    ) -> BlockDecision | None:
        """双层扫描：A) 正则模式在整条展开命令上（管道/fork 等跨段模式不被切分破坏）；
        B) 分词分析逐子命令（引号语义保留，rm/find/sh/python 载荷递归）."""
        expanded = _expand(_normalize_ansi_c_quotes(command))
        # A) 正则灾难模式（整条展开串——$HOME/~ 展开后判定，拼接目标无处遁形）
        for label, pattern in _CATASTROPHIC_PATTERNS:
            m = pattern.search(expanded)
            if m:
                return self._block(label, command, m.group(0))
        # B) 逐子命令分词分析（P0-1 复核补洞：`cd / && rm -rf *` 的 cwd 必须跟着走，
        #    否则通配目标的危险度永远按进程 cwd 判定，删根命令被放行）
        effective_cwd: str | None = cwd
        # N1（第四轮红队）：引号外换行先归一为 ";"，保证 `cd /etc\nrm -rf .`
        # 的第二段独立进入 _scan_tokens（rm 回到执行位）。正则层 A 仍看原始
        # expanded（[^|;] 与 \s 本就跨换行匹配，不受归一影响）。
        for toks in _split_tokenized(_newline_split_normalize(expanded)):
            d = self._scan_tokens(toks, " ".join(toks)[:200], depth, cwd=effective_cwd)
            if d is not None and d.blocked:
                return d
            effective_cwd = _cwd_after_cd(toks, effective_cwd)
        return None

    def _scan_tokens(
        self, toks: list[str], sub: str, depth: int, cwd: str | None = None
    ) -> BlockDecision | None:
        raw_tokens = _split_grouping(list(toks))
        toks = _execution_tokens(toks)
        if not toks:
            return None

        # N3（第四轮）：env -S 载荷无法重新分词 → 删除范围不可静态判定，fail-closed。
        if toks[0] == _ENV_PAYLOAD_UNPARSABLE:
            return self._block(
                "env -S 载荷无法分词，删除范围不可静态判定",
                sub,
                f"命令: {' '.join(raw_tokens)[:120]}",
            )
        # N2（2026-10-25 第四轮红队）：_execution_tokens 把 eval 余部（含 env -S
        # 载荷）拼回 "eval <整串>"——这里整串递归重扫（重新分词后 rm 回到执行位），
        # 透传 cwd；命中即 block。
        if toks[0].startswith("eval ") and depth < 8:
            payload = toks[0][len("eval "):]
            d = self._scan_command(payload, "execute_command", depth + 1, cwd=cwd)
            if d is not None and d.blocked:
                return BlockDecision(
                    blocked=True,
                    reason=d.reason,
                    evidence=f"eval 载荷: {payload[:120]} ← {d.evidence}",
                )

        # 1a) 裸设备写入（dd of=、重定向、cp）：`/dev/./disk0` 这类变体
        #     绕过 `//*dev//*` 正则；按 realpath 归一后判定（2026-10-25 红队补洞）。
        for token in list(raw_tokens) + list(toks):
            device = _normalized_device_target(token)
            if device:
                return self._block(
                    "向块设备写入（dd/重定向设备节点）",
                    sub,
                    f"设备目标: {device}",
                )

        # 1) rm 分词判定（标志聚合 + 展开后目标集合；正则漏网的复合形态在此闭合）
        # P0-1 复核：`git rm` / `xargs rm` / `busybox rm` / `find -exec rm` 里 rm 不在首位，
        # 因此按"被执行的 rm 词"定位，而不是只看 toks[0]。
        #
        # 但"出现 rm 这个字"≠"执行 rm"：`echo rm -rf /etc`、日志文本、文档字符串里
        # rm 只是普通参数（2026-10-25 全量回归：旧逻辑把 echo 参数当命令，误拦）。
        # 只有 rm 处于执行位（首位或 xargs/busybox/git/find -exec 等执行上下文）才判定。
        _rm_exec_predecessors = frozenset(
            {"xargs", "busybox", "git", "find", "sudo", "env", "command", "nohup",
             "timeout", "nice", "stdbuf", "watch", "exec", "builtin"}
        )

        def _rm_is_executed(index: int) -> bool:
            if index == 0:
                return True
            prev = os.path.basename(toks[index - 1]).lower()
            return prev in _rm_exec_predecessors or prev.startswith("-exec")

        rm_idx = next(
            (
                i
                for i, t in enumerate(toks)
                if os.path.basename(t).lower() == "rm" and _rm_is_executed(i)
            ),
            None,
        )
        # 变量 argv0（`$x -fr /etc`，x=rm）：静态不可判，带递归+强制标志就 fail-closed
        if toks[0].startswith("$") and _recursive_flag(["x", *toks[1:]]) and any(
            t.startswith("-") and "f" in t[1:] for t in toks[1:]
        ):
            return self._block("变量 argv0 + 递归强制删除：目标不可静态判定", sub, f"命令: {' '.join(toks)[:120]}")
        if any(os.path.basename(t).lower() == "xargs" for t in raw_tokens) and rm_idx is not None and _rm_recursive_force(
            toks[rm_idx:]
        ):
            return self._block(
                "xargs 批量删除：目标来自标准输入，围栏无法静态判定范围",
                sub,
                f"命令: {' '.join(raw_tokens)[:120]}",
            )
        if rm_idx is not None and _rm_recursive_force(toks[rm_idx:]):
            for target in _rm_targets(toks[rm_idx:]):
                if "$" in target or "`" in target:
                    # P0-1（2026-10-25）：变量/命令替换未展开时目标不可静态判定，fail-closed
                    # （红队补洞：反引号 `echo /etc` 与 $() 等价，旧逻辑只查 $）
                    return self._block(
                        "rm 目标含未展开变量/命令替换，无法静态判定删除范围",
                        sub,
                        f"rm 目标: {target}",
                    )
                if _is_dangerous_rm_target(target, cwd) or _glob_dangerous_target(target, cwd):
                    return self._block("rm -rf 指向根/主目录/系统关键目录", sub, f"rm 目标: {target}")

        # 1b) chmod/chown 改系统根权限/属主：与递归删除同级不可逆（P0-1，2026-10-25）
        if toks[0] in {"chmod", "chown", "chgrp"}:
            # 第一个非标志操作数是 mode/owner，其余才是目标
            operands = [t for t in toks[1:] if not t.startswith("-")]
            for target in operands[1:]:
                # 第四轮红队 M3：非递归 `chmod 000 /etc/passwd` 同样能锁死主机，
                # 系统关键文件不做"必须先 -R"的豁免。
                if _is_critical_system_file(target, cwd):
                    return self._block(
                        "改系统关键文件权限/属主（不可逆）",
                        sub,
                        f"{toks[0]} 目标: {target}",
                    )
                if _recursive_flag(toks) and (
                    _is_dangerous_rm_target(target, cwd) or _glob_dangerous_target(target, cwd)
                ):
                    return self._block(
                        "递归改根/主目录/系统目录的权限或属主",
                        sub,
                        f"{toks[0]} 目标: {target}",
                    )

        # 1c) git clean 在受保护 cwd：一次性清空未跟踪文件，-x 连 ignored 一起删
        #     （P0-1，2026-10-25；docs 里把它列为"项目级不可逆"）
        if toks[0] == "git" and "clean" in toks:
            has_force = any(t.startswith("-") and "f" in t[1:] for t in toks if t != "--") or any(
                t.startswith("--force") for t in toks
            )
            if has_force and _is_dangerous_rm_target(".", cwd):
                return self._block("git clean 在受保护目录内强制清理", sub, "cwd 受保护")
            # 第四轮红队 M10：`git clean -fdx /` 会把仓库根的清理语义搬到 /。
            # 显式路径操作数指向灾难级目标时同样拦（含 glob 形态）。
            if has_force:
                for operand in toks[1:]:
                    if operand.startswith("-") or operand in {"clean", "git"}:
                        continue
                    if _is_dangerous_rm_target(operand, cwd) or _glob_dangerous_target(operand, cwd):
                        return self._block("git clean 指定了灾难级路径", sub, f"操作数: {operand}")

        # 2) find 删除载荷（审计发现 #3 补洞 + EVO-20260923-c58a0bb1 修正 2:
        #    -delete / -exec rm 不再无条件拦——改按 find **起点**的目标语义
        #    判定。工作区/临时区等安全起点放行（正常清理不再误拦），
        #    灾难级起点（根/主目录本体/系统目录子树）仍硬拦。）
        if toks[0] == "find":
            has_delete_payload = "-delete" in toks or any(
                t == "-exec" and i + 1 < len(toks) and toks[i + 1] in ("rm", "shred", "srm")
                for i, t in enumerate(toks)
            )
            if has_delete_payload:
                for start in _find_start_points(toks):
                    if _is_dangerous_rm_target(start, cwd) or _glob_dangerous_target(start, cwd):
                        return self._block(
                            "find 删除载荷指向灾难级起点",
                            sub,
                            f"find 起点: {start}",
                        )
            # N7（2026-10-25 第四轮红队）：-exec/-execdir 之后的命令段（到
            # ";" 或 "+" 为止）整体递归重扫——`find . -exec sh -c 'rm -rf
            # /etc' \;` 里真正执行的是 sh 载荷，而 find 起点 "." 本身安全。
            # seg 是 token 列表（引号语义已由外层 shlex 归并），直接交
            # _scan_tokens 保留载荷单 token 形态。
            if depth < 4:
                for i, t in enumerate(toks):
                    if t not in ("-exec", "-execdir"):
                        continue
                    seg: list[str] = []
                    for u in toks[i + 1:]:
                        if u in (";", "+"):
                            break
                        seg.append(u)
                    if not seg:
                        continue
                    d = self._scan_tokens(seg, " ".join(seg)[:200], depth + 1, cwd=cwd)
                    if d is not None and d.blocked:
                        return BlockDecision(
                            blocked=True,
                            reason=d.reason,
                            evidence=f"find -exec 载荷: {' '.join(seg)[:120]} ← {d.evidence}",
                        )

        # N10（2026-10-25 第四轮红队）：tar --remove-files / rsync --delete
        # 的不可逆删除语义——前者打包后删源，后者把目标同步成镜像（删超额）。
        # 与 rm 同尺度判定：源/目标指向根、家目录、系统目录、cwd 祖先（仓根）
        # 即拦；工作区/临时区内的正常打包同步不受影响。
        if toks[0] == "tar" and any(
            t == "--remove-files" or t.startswith("--remove-files=") for t in toks
        ):
            for target in _tar_remove_files_targets(toks):
                if _is_dangerous_rm_target(target, cwd) or _glob_dangerous_target(target, cwd):
                    return self._block(
                        "tar --remove-files 指向灾难级源目录",
                        sub,
                        f"tar 源: {target}",
                    )
        if toks[0] == "rsync" and any(t.startswith("--delete") for t in toks):
            # 目标 = 末尾操作数（rsync 语法目标总在最后；从尾向头跳过选项词）
            dest = next((t for t in reversed(toks[1:]) if not t.startswith("-")), None)
            if dest is not None and (
                _is_dangerous_rm_target(dest, cwd) or _glob_dangerous_target(dest, cwd)
            ):
                return self._block(
                    "rsync --delete 指向灾难级目标",
                    sub,
                    f"rsync 目标: {dest}",
                )

        # 3) shell 载荷递归（sh -c "..." 内仍是命令；S3-5：深度 4，嵌套 ≥3 层仍命中）
        if depth < 4:
            payload = _shell_payload(toks)
            if payload:
                d = self._scan_command(payload, "execute_command", depth + 1, cwd=cwd)
                if d is not None and d.blocked:
                    return BlockDecision(
                        blocked=True,
                        reason=d.reason,
                        evidence=f"shell 载荷: {payload[:120]} ← {d.evidence}",
                    )

        # 3b) 其它解释器 -e/-c 载荷（ruby/node/perl/awk）：破坏动词 + 灾难目标
        other_payload = _interpreter_payload(toks)
        if other_payload:
            hit = _payload_deletes_dangerous(other_payload, cwd)
            if hit:
                return self._block(
                    "解释器载荷内含指向灾难目录的破坏调用",
                    sub,
                    f"载荷目标: {hit[:80]}",
                )

        # 4) python -c 载荷检查（递归级无条件拦；单文件级字面目标判定）
        py_payload = _python_payload(toks)
        if py_payload:
            # 递归级：只认"真调用 + 字面目标是灾难目录"。
            # 字符串里出现删除命令只是数据（例如生成文档/测试时引用），
            # 按文本命中就拦会误杀诚实工作流，也会逼调用方改用更难审的写法。
            stripped = _PY_STRING_LITERAL.sub("''", py_payload)
            if _PY_RMTREE_CALL_SITE.search(stripped):
                return self._block(
                    "python -c 载荷递归删除调用（递归级一律拦，目标可能动态拼接）",
                    sub,
                    "调用点: " + stripped.strip()[:80],
                )
            for lm in _PY_SINGLE_FILE_CALL.finditer(py_payload):
                target = lm.group(2)
                if _is_dangerous_rm_target(_expand(target), cwd):
                    return self._block(
                        "python -c 载荷单文件删除指向灾难目录",
                        sub,
                        f"字面目标: {target[:80]}",
                    )
            if _PY_SHELL_CALL.search(py_payload):
                m = _PY_RECURSIVE_DANGER.search(py_payload)
                if m:
                    return self._block("python -c 载荷含递归级不可逆破坏调用", sub, f"载荷命中: {m.group(0)[:80]}")
                # N9（2026-10-25 第四轮红队）：os.system/os.popen/subprocess.* 的
                # 字符串实参整串递归重扫——`chmod -R 000 /etc`、`find /etc
                # -delete` 等非 rm 动词复用全量规则（旧逻辑内层只查 rm）。
                if depth < 4:
                    for sm in _PY_SHELL_CALL_LITERAL.finditer(py_payload):
                        arg = sm.group("arg")
                        d = self._scan_command(arg, "execute_command", depth + 1, cwd=cwd)
                        if d is not None and d.blocked:
                            return BlockDecision(
                                blocked=True,
                                reason=d.reason,
                                evidence=f"python 载荷 shell 调用实参: {arg[:80]} ← {d.evidence}",
                            )
                # 引号/逗号归一后 token 扫描（shell 调用里的列表形态命令）
                inner_toks = re.sub(r"['\",()\[\];]", " ", py_payload).split()
                for i, t in enumerate(inner_toks):
                    if t == "rm" and _rm_recursive_force(inner_toks[i:]):
                        for target in _rm_targets(inner_toks[i:]):
                            if _is_dangerous_rm_target(target, cwd):
                                return self._block(
                                    "python -c 载荷内嵌删除命令指向灾难目标",
                                    sub,
                                    f"载荷 rm 目标: {target}",
                                )

        return None

    @staticmethod
    def _block(label: str, command: str, hit: str) -> BlockDecision:
        return BlockDecision(
            blocked=True,
            reason=f"检测到灾难性行为: {label}。该行为可能造成不可逆破坏，已硬阻断（FR-SAFE-01）。",
            evidence=f"命令: {command[:200]}; 命中: {hit[:80]}",
        )

    def _audit_block(self, tool_name: str, command: str, decision: BlockDecision) -> None:
        """阻断审计落盘（hash chain）；写失败不影响阻断本身（阻断已是安全侧）."""
        self._append_audit(
            "safety_blocks.jsonl",
            {
                "kind": "block",
                "tool_name": tool_name,
                "command": command[:200],
                "reason": decision.reason,
                "evidence": decision.evidence,
            },
        )

    def _audit_allow(self, tool_name: str, command: str) -> bool:
        """破坏性但放行的命令留痕；fail-closed 的判定依据就是这个返回值."""
        return self._append_audit(
            "safety_allows.jsonl",
            {
                "kind": "allow_destructive",
                "tool_name": tool_name,
                "command": command[:200],
            },
        )

    def _append_audit(self, filename: str, rec: dict) -> bool:
        if self._audit_dir is None:
            return True
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            path = self._audit_dir / filename
            prev = _last_chain_hash(path)
            body = {**rec, "ts": system_local_now().isoformat(), "prev_hash": prev}
            body["entry_hash"] = _audit_entry_hash(prev, body)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(body, ensure_ascii=False) + "\n")
            return True
        except OSError:
            logger.error("审计落盘失败（fail-closed 场景将阻断破坏性操作）", exc_info=True)
            return False


# ── EVO-20260810-2549e9b6: EXEC_MODE 只读命令判定 ──
_READONLY_PREFIXES = (
    "ls",
    "cat",
    "pwd",
    "echo",
    "head",
    "tail",
    "grep",
    "find",
    "which",
    "git status",
    "git log",
    "git diff",
    "ps",
    "df",
    "du",
    "env",
    "date",
    "whoami",
    "python3 -c",
    "python -c",
    "printenv",
)
_WRITE_MARKERS = (
    ">",
    ">>",
    "tee",
    "rm ",
    "mv ",
    "cp ",
    "mkdir",
    "touch",
    "chmod",
    "chown",
    "curl -o",
    "wget -O",
    "pip install",
    "pip3 install",
    "npm install",
    "git add",
    "git commit",
    "git push",
    "git reset",
    "git checkout",
    "source ",
    "export ",
    "unset ",
    "kill",
    "sudo ",
    "brew install",
    "cargo install",
    # P0-1(2026-08-15，审计发现 #4): 只读前缀命令的写载荷标记——
    # find -delete/-exec 删除；python -c 载荷中的文件破坏/写打开/子进程调用
    "-delete",
    "-exec",
    "rmtree",
    "unlink(",
    ".remove(",
    "rmdir",
    "removedirs",
    ".write(",
    "writelines",
    "subprocess",
)


def _readonly_inspection_command(command: str) -> bool | None:
    """Conservative, shell-aware admission for ordinary source inspection.

    The legacy substring guard rejected harmless searches for words such as
    "rm " or "chmod" and had no support for rg / git show / git grep /
    git ls-files.  Recognize only explicit inspection commands here; do not
    try to authorize arbitrary shell syntax or subprocess-capable options.
    None delegates unrelated commands to the existing legacy rule.
    """
    if not command or any(x in command for x in ("\n", "\r", "\x00", "\x60", "$")):
        return False if command.lstrip().startswith(("rg ", "grep ", "git ")) else None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False if command.lstrip().startswith(("rg ", "grep ", "git ")) else None
    if not tokens or tokens[0] not in {"rg", "grep", "git"}:
        return None

    # Only an explicit pipe into head/tail is allowed.  Reject chained
    # commands, redirections, conditional shells, process substitutions, etc.
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            if not segments[-1]:
                return False
            segments.append([])
        elif token and all(ch in ";&|<>" for ch in token):
            return False
        else:
            segments[-1].append(token)
    if not segments[-1]:
        return False
    first = segments[0]
    if first[0] == "rg":
        # ripgrep --pre executes an arbitrary external preprocessor.
        if any(
            flag in {"--pre", "--pre-glob"}
            or flag.startswith(("--pre=", "--pre-glob="))
            for flag in first[1:]
        ):
            return False
    elif first[0] == "git":
        idx = 1
        if len(first) > idx and first[idx] == "--no-pager":
            idx += 1
        if len(first) <= idx or first[idx] not in {"show", "grep", "ls-files"}:
            return None
        subcmd = first[idx]
        arguments = first[idx + 1:]
        if any(
            opt in {"--ext-diff", "--textconv", "--open-files-in-pager"}
            or opt.startswith(("--ext-diff=", "--textconv=", "--open-files-in-pager="))
            for opt in arguments
        ):
            return False
        # git grep's -O launches the specified pager/program.
        if subcmd == "grep" and any(arg == "-O" or arg.startswith("-O") for arg in arguments):
            return False
        # git show supports writing to an output file and external diff tools.
        if subcmd == "show" and any(
            arg == "--output" or arg.startswith(("-o", "--output="))
            for arg in arguments
        ):
            return False
    # grep itself searches content; a quoted match pattern containing command
    # names is not an instruction to execute those commands.

    return all(
        tail[0] in {"head", "tail"} for tail in segments[1:]
    )


def is_readonly_command(command: str) -> bool:
    """判定命令是否只读（EXEC_MODE=readonly 时放行只读，拦截写类）.

    P0-1 收紧：find/python -c 等"只读前缀"命令携带写载荷（-delete/-exec/
    rmtree/unlink/write(/subprocess）不再误判只读——宁误拦勿漏放（锁死模式下
    误拦的代价是 AI 换命令，漏放的代价是数据丢失）。
    """
    cmd = command.strip().lstrip()
    if not cmd:
        return False
    inspection = _readonly_inspection_command(cmd)
    if inspection is not None:
        return inspection
    if cmd.startswith(_READONLY_PREFIXES):
        # 只读命令 + 无写标记 → 放行
        return not any(m in command for m in _WRITE_MARKERS)
    return False


@dataclass(frozen=True)
class LinkProbeResult:
    """link_shaped_paths 三态探测结果（R9-IMM-04 / R9-DFX-05，D7）.

    探测函数保持 fail-open：如实返回探测结果、不抛异常；
    fail-closed 决策（如 edit_file 拒写）由调用方按 status 处置。
    """

    status: Literal["no_links", "probe_failed", "links_found"]
    links: tuple[str, ...] = ()  # links_found 时的路径链（根→叶）；其余态为空


def link_shaped_paths(path: str | Path) -> LinkProbeResult:
    """路径链中的符号链接组件探测（自身或任一父目录，T5b 对齐 Harness Unlink 模式）.

    路径可不存在（写场景的待建文件）：从最深现有祖先向下检查每层 is_symlink。

    Returns: LinkProbeResult 三态——
      - no_links: 探测完成，路径链无符号链接
      - probe_failed: 探测失败（ELOOP/权限等 OSError）——探测失败≠无链接，
        这正是最需防护的场景（fail-open：如实返回，不抛异常）
      - links_found: 链含符号链接（links 为根→叶顺序路径链）
    """
    out: list[str] = []
    try:
        p = Path(path).expanduser()
        # 从最深现有祖先开始（不存在部分先暂存，之后逐层拼回）
        cur = p
        missing: list[Path] = []
        while not cur.exists() and cur != cur.parent:
            missing.append(cur)
            cur = cur.parent
        chain: list[Path] = []
        if cur.exists():
            parts = cur.parts
            probe = Path(parts[0])
            chain.append(probe)
            for part in parts[1:]:
                probe = probe / part
                chain.append(probe)
        for m in reversed(missing):
            chain.append(m)
        for c in chain:
            if c.is_symlink():
                out.append(str(c))
    except OSError:
        # 路径解析失败 fail-open：如实返回"探测失败"态（不阻断正常路径；
        # 调用方按语义处置——写面应拒、读面放行）
        return LinkProbeResult(status="probe_failed")
    if out:
        return LinkProbeResult(status="links_found", links=tuple(out))
    return LinkProbeResult(status="no_links")
