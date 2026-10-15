"""RULE-AI-28 mandatory review obligation and observational evidence hints.

The model must obtain an independent PASS for the current artifact before the
target action. These receipt annotations are observations, not admission proof:
a VERDICT substring is unverified tool text, not an authenticated child result.
Only observation recording is best-effort; its failure never waives review.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import cast

GATE_NOTE_PREFIX = "[RULE-AI-28 闸]"
REVIEW_GATE_OBLIGATION = "代码任务进入全量测试、文稿对外发表或 git push 前，必须取得对应独立审查子代理覆盖当前产物的有效 PASS 回执；未满足时暂缓该动作。"
ARTICLE_REVIEW_OBLIGATION = "涉及文稿发表前，按 RULE-AI-28 取得专门独立审查子代理覆盖当前产物的有效 PASS 回执；未满足时暂缓发表。"


# git push 子命令（含 --force / --force-with-lease 变体）：触发闸。
# 锚定在命令起点或 shell 操作符之后（echo git push / git log --grep push 不触发）；
# git 与 push 之间只允许以 - 开头的旗标。
_GIT_PUSH_RE = re.compile(
    r"(?:^|[;&|]{1,2})\s*(?:\S*/)?git(?:-[A-Za-z0-9._-]+)?\s+"
    r"(?:--?[\w=.-]+(?:\s+(?:\"[^\"]*\"|'[^']*'|[\w./@:~-]+))?\s+)*push\b"
)
# 全量 pytest：pytest 位于命令起点或操作符之后（python -m pytest 归一后判定），
# 且无 -k/::/具体测试文件路径收窄。grep pytest file 之类不触发。
_PYTEST_CMD_RE = re.compile(r"(?:^|[;&|]{1,2})\s*(?:\S+/)?(python3?\s+-m\s+)?pytest3?\b")
# 全量 pytest 的收窄形态（出现即视为子集，不触发闸）。
_NARROWING_RE = re.compile(r"(^|\s)-k\S*|\S*::\S*|\S*\.py\b|(^|\s)tests?/\S*|(^|\s)-m\s+(?!pytest3?\b)\S+")
# 只读探测的旗标形态（供 execute_command 复用，保持单一定义点）。
# argv0 允许集（basename 归一后）：只读豁免只对集合内命令生效——
# rm status / tee diff / ./deploy.sh --dry-run 等 argv0 混淆形态一律不放行
# （独立审查 subagent_859ec7d661bf 端到端证实原实现对写命令穿透）。
_READ_ONLY_ARGV0 = frozenset(
    {"git", "service_control", "ls", "pwd", "pytest", "pytest3", "python", "python3", "pip", "pip3"}
)
# 各 argv0 允许的只读子命令（argv1 白名单，按命令真实语义逐个核定）。
_READ_ONLY_SUBCOMMANDS_BY_ARGV0: dict[str, frozenset[str]] = {
    "git": frozenset({"status", "diff", "log", "show"}),
    "service_control": frozenset({"status"}),
}
# --dry-run 豁免仅限有该旗标"不落盘"确定语义的命令。
_DRY_RUN_ARGV0 = frozenset({"git"})
_READ_ONLY_STANDALONE_FLAGS = frozenset({"--help", "-h", "--version", "-V", "-?"})
# argv0 自身即只读动词的命令。
_READ_ONLY_SELF_BINS = frozenset({"ls", "pwd"})
_READ_ONLY_ARG_RE = re.compile(r"^(--?[A-Za-z][A-Za-z0-9=_./:+-]*|[A-Za-z0-9._/~@:%+-]+)$")
# 疑似写文件旗标（如 git diff --output=…）：只读面一律不放行。
_WRITE_FLAG_RE = re.compile(r"^--?(o|out|output|write|w)(=|\b)", re.IGNORECASE)
# 外部程序执行面旗标（git 配置驱动的 textconv/ext-diff）：只读面不放行。
_EXTERNAL_EXEC_FLAG_RE = re.compile(r"^--?(textconv|ext-diff|exec-path)\b", re.IGNORECASE)
# shell 复合/重定向/替换操作符：出现在命令文本中即不归类为只读探测（fail-closed）。
_SHELL_OPERATOR_RE = re.compile(r"&&|\|\||[|;&<>`]|>>|\$\(|\$\{")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WRAPPER_ARGV0 = frozenset({"sudo", "su", "nohup", "env", "xargs", "watch", "timeout", "exec", "source", ".", "bash", "sh", "zsh", "fish", "dash"})


def is_read_only_probe(command: str) -> bool:
    """Deterministic read-only probe classifier (EVO-20261014-459a8a1e，保守、fail-closed).

    只识别无 shell 操作符、无环境赋值包装、无包装器前缀、且 argv0（basename
    归一）在显式允许集内的单一简单命令，形态限于：
    - ``<bin> --help/-h/--version/-V``（允许集内任意 bin，旗标须全部为独立
      help/version 形态）；
    - ``git ... --dry-run``（--dry-run 豁免仅限有确定"不落盘"语义的命令集）；
    - ``<bin> <sub>``，sub ∈ 该 argv0 逐个核定的只读子命令白名单，其余 token
      均为安全旗标/路径样参数且非写文件/外部程序执行旗标；
    - ``ls/pwd ...``（argv0 自身只读动词）。

    argv0 不在允许集内的一律不放行（rm status / tee diff / ./x.sh --dry-run
    等混淆形态）；无法归类的命令一律不放行。灾难性硬阻断等其他围栏层不受
    本分类影响。
    """
    import shlex

    text = str(command or "").strip()
    if not text or "\n" in text or _SHELL_OPERATOR_RE.search(text):
        return False
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        return False
    # 剥掉纯环境变量赋值前缀（FOO=bar <bin> ...），只考察实际命令。
    while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return False
    # basename 归一（/usr/bin/git → git）；相对路径脚本（./x.sh）的 basename
    # 不在允许集内，天然拒绝。
    argv0 = tokens[0].rsplit("/", 1)[-1]
    if argv0 in _WRAPPER_ARGV0 or argv0 not in _READ_ONLY_ARGV0:
        return False
    rest = tokens[1:]
    if not rest:
        return False

    def _safe_args(args: list[str]) -> bool:
        return all(
            _READ_ONLY_ARG_RE.match(t)
            and not _WRITE_FLAG_RE.match(t)
            and not _EXTERNAL_EXEC_FLAG_RE.match(t)
            for t in args
        )

    # (a) 独立 help/version 旗标。
    if all(t in _READ_ONLY_STANDALONE_FLAGS for t in rest):
        return True
    # (a") 尾随 help 旗标形态：<bin> <sub> --help/-h（白名单 bin 的子命令帮助，
    # 如 service_control publish --help / git push --help——SPEC-20260922 原始场景；
    # 仅限长度恰 2 且尾旗标恰为 help，不扩散到其它参数组合）。
    if (
        len(rest) == 2
        and re.fullmatch(r"[a-z][a-z0-9_-]*", rest[0])
        and rest[1] in {"--help", "-h"}
    ):
        return True
    # (a') argv0 自身即只读动词（ls/pwd 类）。
    if argv0 in _READ_ONLY_SELF_BINS and _safe_args(rest):
        return True
    # (b) --dry-run：仅限确定"不落盘"语义命令集，其余参数须为安全旗标/路径样。
    if argv0 in _DRY_RUN_ARGV0 and "--dry-run" in rest and _safe_args(
        [t for t in rest if t != "--dry-run"]
    ):
        return True
    # (c) 只读子命令：argv1 必须在该 argv0 的逐个核定白名单内。
    subcommands = _READ_ONLY_SUBCOMMANDS_BY_ARGV0.get(argv0, frozenset())
    return rest[0] in subcommands and _safe_args(rest[1:])


def classify_review_gate_command(command: str) -> str | None:
    """Deterministically classify a shell command as a review-gate trigger.

    Returns ``"git_push"`` / ``"full_test"`` / ``None``。仅报告已识别形态；
    不是完整 shell 解析器，也不返回审查资格。父 agent 仍须履行前置审查义务。
    """
    text = str(command or "").strip()
    if not text:
        return None
    if _GIT_PUSH_RE.search(text):
        return "git_push"
    if _PYTEST_CMD_RE.search(text) and not _NARROWING_RE.search(text):
        return "full_test"
    return None


def review_gate_note(action_kind: str, machine_fact: str, *, action_label: str) -> str:
    """Report the obligation and unverified observation without claiming admission."""
    return (
        f"{GATE_NOTE_PREFIX} 动作={action_label}（{action_kind}）｜"
        "审查是强制前置义务，须先取得对应独立审查子代理覆盖当前产物的有效 PASS 回执｜"
        f"观测线索（审查资格未核验）: {machine_fact}｜"
        "本行不是审查通过凭据或免审许可；具体执行状态以本工具回执为准"
    )


def make_review_gate_probe(
    event_store: object | None,
    current_session_id_getter: Callable[[], str],
    audit_recorder: Callable[[str, str, str], None] | None = None,
) -> Callable[[dict], str]:
    """Build the machine-fact probe + review_gate_probe event recorder closure.

    返回的 recorder 接收动作指纹 dict（action_kind/tool/command_preview），探测
    本会话工具文本中最近一条 verdict 线索并写 ``review_gate_probe`` 事件，
    返回观测线索一行文本。观测故障返回 unknown；unknown 不等于通过或免审。

    ``audit_recorder(action_type, detail_text, session_id)``（可选）把同一事件
    以 ``review_gate_probe`` action_type 同步落 action_trace 审计流，使
    event_stream（统一事件流视图）可检索——程序不裁决，只并排落盘。
    """

    verdict_re = re.compile(r"VERDICT:\s*([A-Z][A-Z_]*)")

    def _fact_from_content(content: str) -> str | None:
        try:
            candidate = json.loads(content)
        except (ValueError, TypeError):
            candidate = None
        if isinstance(candidate, dict) and candidate.get("verdict") in {"PASS", "REVISE", "BLOCK"}:
            return str(candidate["verdict"])
        m = verdict_re.search(content)
        return m.group(1) if m else None

    def recorder(detail: dict) -> str:
        sid = ""
        try:
            sid = str(current_session_id_getter() or "")
        except Exception:  # noqa: BLE001 - probe is best-effort
            sid = ""
        fact = "unknown（探测失败）"
        last_verdict = ""
        found_line = ""
        try:
            store = event_store
            read_events = getattr(store, "read", None)
            if (
                store is None
                or not callable(read_events)
                or not bool(getattr(store, "enabled", False))
                or not sid
            ):
                fact = "unknown（无本会话事件流）"
            else:
                events = list(cast("list[object]", read_events(sid) or []))
                for event in reversed(events):
                    payload = getattr(event, "payload", None) or {}
                    if str(payload.get("role") or "") != "tool":
                        continue
                    verdict = _fact_from_content(str(payload.get("content") or ""))
                    if verdict:
                        last_verdict = verdict
                        found_line = (
                            f"unverified_verdict_text={verdict}"
                            "（仅工具文本，未核验真实子会话、审查类型、当前产物与目标）"
                        )
                        break
                fact = (
                    found_line
                    if last_verdict
                    else "none_found（未发现可识别的工具文本线索；不证明不存在审查回执）"
                )
        except Exception:  # noqa: BLE001 - observation unavailable; review remains mandatory
            fact = "unknown（探测异常）"
        # Only an observation: never promote a text match to review qualification.
        payload = {
            **dict(detail or {}),
            "machine_fact": fact,
            "review_qualification_verified": False,
        }
        try:
            append = getattr(event_store, "append", None)
            if callable(append) and sid:
                append(sid, "review_gate_probe", payload)
        except Exception:  # noqa: BLE001 - event write is observability, fail-open
            pass
        # Observation failures affect telemetry only, never the review obligation.
        try:
            if callable(audit_recorder):
                audit_recorder(
                    "review_gate_probe",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    sid,
                )
        except Exception:  # noqa: BLE001 - audit write is observability, fail-open
            pass
        return fact

    return recorder
