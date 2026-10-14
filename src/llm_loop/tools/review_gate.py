"""EVO-20261014-7ba73d88: push/publish/全量测试前的 review gate 闸提示。

只提醒不阻断：回执注入一行 RULE-AI-28 闸状态（satisfied / exempted:<类型> / none，
由模型按规则二十八自声明），并写 review_gate_probe 结构化事件——模型声明与机器
事实并排落盘，程序不裁决。机器事实探测 = 本会话事件流中最近一条已落盘的
``VERDICT:`` 回执（审查类子代理结算报告的稳定产物），best-effort、fail-open。
"""

from __future__ import annotations

import json
import re
from typing import Callable, cast

GATE_NOTE_PREFIX = "[RULE-AI-28 闸]"

# git push 子命令（含 --force / --force-with-lease 变体）：触发闸。
_GIT_PUSH_RE = re.compile(r"(?:^|[\s;&|])(?:/usr/bin/)?git(?:-[A-Za-z0-9._-]+)?\s+(?:[-\w=]+\s+)*push\b")
# 全量 pytest：出现 pytest 且无 -k/::/具体测试文件路径收窄。
_NARROWING_RE = re.compile(r"(^|\s)-k\S*|\S*::\S*|\S*\.py\b|(^|\s)tests?/\S*|(^|\s)-m\s+\S+")
# 只读探测的旗标形态（供 execute_command 复用，保持单一定义点）。
_READ_ONLY_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "ls", "show", "info", "list", "version", "help"}
)
_READ_ONLY_STANDALONE_FLAGS = frozenset({"--help", "-h", "--version", "-V", "-?"})
# argv0 自身即只读动词的命令（如 ls）。
_READ_ONLY_SELF_BINS = frozenset({"ls"})
_READ_ONLY_ARG_RE = re.compile(r"^(--?[A-Za-z][A-Za-z0-9=_./:+-]*|[A-Za-z0-9._/~@:%+-]+)$")
# 疑似写文件旗标（如 git diff --output=…）：只读面一律不放行。
_WRITE_FLAG_RE = re.compile(r"^--?(o|out|output|write|w)(=|\b)", re.IGNORECASE)
# shell 复合/重定向/替换操作符：出现在命令文本中即不归类为只读探测（fail-closed）。
_SHELL_OPERATOR_RE = re.compile(r"&&|\|\||[|;&<>`]|>>|\$\(|\$\{")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def is_read_only_probe(command: str) -> bool:
    """Deterministic read-only probe classifier (EVO-20261014-459a8a1e，保守、fail-closed).

    只识别无 shell 操作符、无环境赋值包装、无 sudo/nohup 类前缀的单一简单命令，
    且形态限于三类：
    - ``<bin> --help/-h/--version/-V``（可多旗标并置）；
    - 含 ``--dry-run`` 且其余 token 均为安全旗标/路径样参数；
    - ``<bin> <sub>``，sub ∈ 只读子命令集（status/diff/log/ls/show/info/list/
      version/help），其余 token 均为安全旗标/路径样参数且非写文件旗标。

    该分类只用于 shell 围栏层（E3/E4）放行确定只读探测；灾难性硬阻断等其他
    层不受影响，无法归类的命令一律不放行。
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
    argv0 = tokens[0]
    if argv0 in {"sudo", "su", "nohup", "env", "xargs", "watch", "timeout", "exec", "source", "."}:
        return False
    rest = tokens[1:]
    if not rest:
        return False

    def _safe_args(args: list[str]) -> bool:
        return all(_READ_ONLY_ARG_RE.match(t) and not _WRITE_FLAG_RE.match(t) for t in args)

    # (a) 独立 help/version 旗标。
    if all(t in _READ_ONLY_STANDALONE_FLAGS for t in rest):
        return True
    # (a') argv0 自身即只读动词（ls 类）。
    if argv0 in _READ_ONLY_SELF_BINS and _safe_args(rest):
        return True
    # (b) --dry-run：其余参数须为安全旗标/路径样。
    if "--dry-run" in rest and _safe_args([t for t in rest if t != "--dry-run"]):
        return True
    # (c) 只读子命令。
    if rest[0] in _READ_ONLY_SUBCOMMANDS and _safe_args(rest[1:]):
        return True
    return False


def classify_review_gate_command(command: str) -> str | None:
    """Deterministically classify a shell command as a review-gate trigger.

    Returns ``"git_push"`` / ``"full_test"`` / ``None``。只做形态匹配，不裁决、
    不阻断；闸语义（是否已审查/豁免）由模型声明 + 机器事实并排呈现。
    """
    text = str(command or "").strip()
    if not text:
        return None
    if _GIT_PUSH_RE.search(text):
        return "git_push"
    tokens = text.split()
    if any(tok == "pytest" or tok.endswith("/pytest") or tok == "pytest3" for tok in tokens):
        # `python -m pytest` 是模块调用形态，不是 `-m <marker>` 收窄——先归一掉再判收窄。
        probe_text = re.sub(r"(^|\s)-m\s+(pytest|pytest3)(\s|$)", r"\1\2\3", text)
        if not _NARROWING_RE.search(probe_text):
            return "full_test"
    return None


def review_gate_note(action_kind: str, machine_fact: str, *, action_label: str) -> str:
    """One-line gate reminder injected into the receipt (EVO-20261014-7ba73d88)."""
    return (
        f"{GATE_NOTE_PREFIX} 动作={action_label}（{action_kind}）｜"
        "本动作前是否已有独立审查子代理 PASS 回执？声明 satisfied / exempted:<类型> / none｜"
        f"机器事实: {machine_fact}｜只提醒不阻断，豁免按规则二十八自声明"
    )


def make_review_gate_probe(
    event_store: object | None,
    current_session_id_getter: Callable[[], str],
    audit_recorder: Callable[[str, str, str], None] | None = None,
) -> Callable[[dict], str]:
    """Build the machine-fact probe + review_gate_probe event recorder closure.

    返回的 recorder 接收动作指纹 dict（action_kind/tool/command_preview），探测
    本会话事件流中最近一条 ``VERDICT:`` 回执并写 ``review_gate_probe`` 事件，
    返回机器事实一行文本。探测与写盘均 fail-open：任何异常返回 unknown 并照常提醒。

    ``audit_recorder(action_type, detail_text, session_id)``（可选）把同一事件
    以 ``review_gate_probe`` action_type 同步落 action_trace 审计流，使
    event_stream（统一事件流视图）可检索——程序不裁决，只并排落盘。
    """

    verdict_re = re.compile(r"VERDICT:\s*([A-Z][A-Z_]*)")

    def _fact_from_content(content: str) -> str | None:
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
                        found_line = f"last_verdict={verdict}（本会话已落盘 VERDICT 回执）"
                        break
                if last_verdict:
                    fact = found_line
                else:
                    fact = "none_found（本会话未见已落盘 VERDICT 回执）"
        except Exception:  # noqa: BLE001 - probe is best-effort, never blocks the action
            fact = "unknown（探测异常）"
        # review_gate_probe 事件：模型声明位留给回执，机器事实当轮落盘（程序不裁决）。
        payload = {
            **dict(detail or {}),
            "machine_fact": fact,
            "model_declaration": "(模型在回执/后续消息中自声明)",
        }
        try:
            append = getattr(event_store, "append", None)
            if callable(append) and sid:
                append(sid, "review_gate_probe", payload)
        except Exception:  # noqa: BLE001 - event write is observability, fail-open
            pass
        # 同步落 action_trace 审计流（event_stream 统一视图可检索）。
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
