"""灾难性安全硬边界 CatastrophicGuard（design.md §2.1.3.5 机制四 / FR-SAFE）.

唯一允许程序硬阻断的边界（FR-SAFE-01）: 只拦截不可逆删除/系统破坏，
其余一切如实反馈放行（FR-SAFE-03）。边界刻意保持极小（FR-SAFE-03）。

如实标注（P0-1, 2026-08-15，审计发现 #3 修复）：本机制是**已知灾难模式的
硬阻断 + 全量阻断审计**，不是完备沙箱——它拦截常见的不可逆破坏形态
（rm -rf 根/主目录、mkfs、dd 写块设备、fork bomb、curl 管道执行、写系统
关键区、find 批量删除、shell/python 载荷中的上述行为），不能证明任意命令
无副作用。需要更强隔离时请叠加 EXEC_MODE 分级与系统级沙箱（纵深防御）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockDecision:
    """一次灾难性阻断判定结果."""

    blocked: bool
    reason: str = ""
    evidence: str = ""  # 判定依据（FR-SAFE-02 阻断信息透明）


# 不可逆删除 / 系统破坏的最小灾难性模式集合（design.md §2.1.3.5）
_CATASTROPHIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # rm -rf 指向根 / 用户主目录 / 系统关键目录
    (
        "rm -rf 指向根目录或系统关键目录",
        re.compile(
            r"rm\s+(-[a-z]*r[a-z]*f[a-z]*|-f[a-z]*r[a-z]*|-[a-z]*rf)\s+(\/\s*$|~\/?\s*$|/(etc|boot|usr|bin|sbin|lib|var|home)(\s|/|$))",
            re.IGNORECASE,
        ),
    ),
    # 格式化 / 建文件系统
    ("mkfs/format 格式化磁盘", re.compile(r"(mkfs\.|mkfs\s|format\s+[a-z]:|newfs)", re.IGNORECASE)),
    # dd 写块设备
    ("dd 写入块设备", re.compile(r"dd\b[^|;]*\bof=/dev/(sd|hd|vd|nvme|disk)", re.IGNORECASE)),
    # fork bomb
    ("fork bomb", re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", re.IGNORECASE)),
    # curl/wget 管道直连执行
    ("curl/wget 下载直连执行", re.compile(r"(curl|wget)[^|;]*\|\s*(ba)?sh\b", re.IGNORECASE)),
    # 写系统关键区
    (
        "写入系统关键区",
        re.compile(
            r"(>\s*|>>\s*|tee\s+)/etc/(passwd|shadow|sudoers|fstab|hosts|crontab)|(>\s*|>>\s*)//boot",
            re.IGNORECASE,
        ),
    ),
]

# rm -rf 的灾难性目标（变量展开 + ~ 展开后判定，审计发现 #3：$HOME/${HOME}/~ 绕过修复）
_SYSTEM_DIRS = ("/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/var", "/home")

# python -c 载荷中的不可逆破坏调用（审计发现 #3：python -c 载荷绕过修复）
_PY_DANGER = re.compile(
    r"(shutil\.rmtree|os\.(remove|unlink|rmdir|removedirs)|pathlib[^(]*\([^)]*\)\.(unlink|rmdir)"
    r"|rm\s+-[a-z]*r[a-z]*f|mkfs\b|dd\b.*of=/dev/)",
    re.IGNORECASE,
)

# 复合命令切分边界（审计发现 #3：;/&&/||/| 拼接绕过修复——见 _split_tokenized）


def _expand(command: str) -> str:
    """$VAR/${VAR} + ~ 展开（判定在展开后的真实目标上进行）.

    注意 os.path.expanduser 只展开字符串开头的 ~——命令中 ~ 出现在空白/运算符后
    （rm -rf ~/data），需按词边界补展开（词中 hello~world 不动，防误改）。
    """
    expanded = os.path.expandvars(command)
    home = os.path.expanduser("~")
    if "~" in expanded and home != "~":
        expanded = re.sub(r"(^|(?<=[\s;|&'\"=]))~(?=[/\s'\"]|$)", lambda m: m.group(1) + home, expanded)
    return expanded


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


def _is_dangerous_rm_target(target: str) -> bool:
    """根 / 主目录（含子路径）/ 系统关键目录（含子路径）.

    工作区相对路径（./build 等）与 /tmp 不在此列——边界极小纪律，
    会话内正常清理由 AI 自主裁决，程序只拦不可逆系统级破坏。
    """
    t = target.rstrip("/")
    if t in ("", "/"):
        return True
    home = os.path.expanduser("~")
    if t == home or t.startswith(home + os.sep):
        return True
    return any(t == d or t.startswith(d + "/") for d in _SYSTEM_DIRS)


def _shell_payload(tokens: list[str]) -> str | None:
    """sh/bash -c 的载荷字符串."""
    if tokens and tokens[0] in ("sh", "bash", "zsh") and "-c" in tokens:
        idx = tokens.index("-c")
        if idx + 1 < len(tokens):
            return tokens[idx + 1]
    return None


def _python_payload(tokens: list[str]) -> str | None:
    """python/python3 -c 的载荷字符串."""
    if tokens and tokens[0] in ("python", "python3") and "-c" in tokens:
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

    def guard(self, tool_name: str, args: dict) -> BlockDecision | None:
        """对工具调用做灾难性判定.

        Args:
            tool_name: 工具名.
            args: 工具参数（如 execute_command 的 command 字段）.

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

        decision = self._scan_command(command, tool_name, depth=0)
        if decision is not None and decision.blocked:
            self._audit_block(tool_name, command, decision)
        return decision

    def _scan_command(self, command: str, tool_name: str, depth: int) -> BlockDecision | None:
        """双层扫描：A) 正则模式在整条展开命令上（管道/fork 等跨段模式不被切分破坏）；
        B) 分词分析逐子命令（引号语义保留，rm/find/sh/python 载荷递归）."""
        expanded = _expand(command)
        # A) 正则灾难模式（整条展开串——$HOME/~ 展开后判定，拼接目标无处遁形）
        for label, pattern in _CATASTROPHIC_PATTERNS:
            m = pattern.search(expanded)
            if m:
                return self._block(label, command, m.group(0))
        # B) 逐子命令分词分析
        for toks in _split_tokenized(expanded):
            d = self._scan_tokens(toks, " ".join(toks)[:200], depth)
            if d is not None and d.blocked:
                return d
        return None

    def _scan_tokens(self, toks: list[str], sub: str, depth: int) -> BlockDecision | None:
        if not toks:
            return None

        # 1) rm 分词判定（标志聚合 + 展开后目标集合；正则漏网的复合形态在此闭合）
        if toks[0] == "rm" and _rm_recursive_force(toks):
            for target in _rm_targets(toks):
                if _is_dangerous_rm_target(target):
                    return self._block("rm -rf 指向根/主目录/系统关键目录", sub, f"rm 目标: {target}")

        # 2) find 删除载荷（审计发现 #3：find -delete/-exec rm 绕过修复）
        if toks[0] == "find":
            if "-delete" in toks:
                return self._block("find -delete 批量删除", sub, "find ... -delete")
            if "-exec" in toks:
                idx = toks.index("-exec")
                payload = toks[idx + 1 :]
                if payload and payload[0] in ("rm", "shred", "srm"):
                    return self._block("find -exec 调用删除命令", sub, f"find -exec {payload[0]} ...")

        # 3) shell 载荷递归（sh -c "..." 内仍是命令，深度限 2 防无限递归）
        if depth < 2:
            payload = _shell_payload(toks)
            if payload:
                d = self._scan_command(payload, "execute_command", depth + 1)
                if d is not None and d.blocked:
                    return BlockDecision(
                        blocked=True,
                        reason=d.reason,
                        evidence=f"shell 载荷: {payload[:120]} ← {d.evidence}",
                    )

        # 4) python -c 载荷检查（rmtree/remove/unlink/内嵌 rm -rf 等）
        py_payload = _python_payload(toks)
        if py_payload:
            m = _PY_DANGER.search(py_payload)
            if m:
                return self._block("python -c 载荷含不可逆破坏调用", sub, f"载荷命中: {m.group(0)[:80]}")
            # 引号/逗号归一后 token 扫描（subprocess.run(['rm','-rf','/']) 等列表形态）
            inner_toks = re.sub(r"['\",()\[\];]", " ", py_payload).split()
            for i, t in enumerate(inner_toks):
                if t == "rm" and _rm_recursive_force(inner_toks[i:]):
                    for target in _rm_targets(inner_toks[i:]):
                        if _is_dangerous_rm_target(target):
                            return self._block(
                                "python -c 载荷内嵌 rm -rf 灾难目标",
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
        """阻断审计落盘（data/audit/safety_blocks.jsonl）；写失败不影响阻断（fail-open）."""
        if self._audit_dir is None:
            return
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": datetime.now(UTC).isoformat(),
                "tool_name": tool_name,
                "command": command[:200],
                "reason": decision.reason,
                "evidence": decision.evidence,
            }
            with (self._audit_dir / "safety_blocks.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("阻断审计落盘失败（不影响阻断本身）", exc_info=True)


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


def is_readonly_command(command: str) -> bool:
    """判定命令是否只读（EXEC_MODE=readonly 时放行只读，拦截写类）.

    P0-1 收紧：find/python -c 等"只读前缀"命令携带写载荷（-delete/-exec/
    rmtree/unlink/write(/subprocess）不再误判只读——宁误拦勿漏放（锁死模式下
    误拦的代价是 AI 换命令，漏放的代价是数据丢失）。
    """
    cmd = command.strip().lstrip()
    if not cmd:
        return False
    if cmd.startswith(_READONLY_PREFIXES):
        # 只读命令 + 无写标记 → 放行
        return not any(m in command for m in _WRITE_MARKERS)
    return False


def link_shaped_paths(path: str | Path) -> list[str]:
    """路径链中的符号链接组件（自身或任一父目录，T5b 对齐 Harness Unlink 模式）.

    路径可不存在（写场景的待建文件）：从最深现有祖先向下检查每层 is_symlink。
    解析失败如实返回空（fail-open，不阻断正常路径）。

    Returns: 含符号链接的路径字符串列表（根 → 叶顺序）；空 = 无链接。
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
        pass  # 路径解析失败 fail-open：如实返回已收集结果（不阻断正常路径）
    return out
