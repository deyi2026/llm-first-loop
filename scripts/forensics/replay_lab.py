#!/usr/bin/env python3
"""replay_lab 受控复现框架（tasks 1.5，design A2，spec 5.1.1-2 复现实验）.

在测试沙箱（内存 Session + 内存事件轨）内重建候选通路剧本，以脱敏轨迹样本
注入，按四条件判定复现是否成立：

  落盘出现 role=user 消息 且 metadata.program_origin==False
  且 内容含轨迹特征（思考过程标记 + 工具调用命令组合）
  且 写入不经 feishu/web 通道

三类剧本（相互隔离，均可独立加载执行）：
  e1_abuse               E1 滥用注入形态：内部调用方以外部轨迹文本为 user_text
                         走 E1 落盘构造（复刻 engine.py:421-427 现行生产行为：
                         origin_metadata(USER_INSTRUCTION) + Message + append + 事件）
  interop_legacy_tail    interop 历史版本 tail「转 user」行为：inbox 消息进
                         _interop_tail_messages、build 期转 user——仅视图不落盘
  err1210_defer_residual 升级窗口进程内 defer 残留：defer 帧重放——仅视图不落盘

复用 src/llm_loop/core/session.py 的 Session（只读内存实现，零改动）。

用法（库）：from replay_lab import replay_candidate_path
用法（CLI）：python3 scripts/forensics/replay_lab.py --sample-file F [--candidate e1_abuse]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import Session

# ── 轨迹特征判定（#280/#290 结构模板，脱敏通用化） ────────────────────────

_TRACE_THINK_MARK = re.compile(r"(?m)^\s*思考过程\s*$")
_TOOL_CMD_MARK = re.compile(
    r"(?m)^(python3? -[cs]\b|grep -[a-z]*n?\b|sed (-n )?-e ?'|\bnpm \w+|\bgit \w+)"
)


def content_has_trace_signature(content: str) -> bool:
    """思考过程标记与工具调用命令组合同时命中即轨迹特征。"""
    text = str(content or "")
    return bool(_TRACE_THINK_MARK.search(text)) and bool(_TOOL_CMD_MARK.search(text))


@dataclass
class ReplayVerdict:
    """复现回执：成功/失败 + 四条件逐项 + 落盘消息身份快照。"""

    candidate: str
    reproduced: bool
    conditions: dict[str, bool] = field(default_factory=dict)
    persisted_snapshot: list[dict] = field(default_factory=list)
    basis: str = ""
    repo_head: str = ""

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate,
            "reproduced": self.reproduced,
            "conditions": self.conditions,
            "persisted_snapshot": self.persisted_snapshot,
            "basis": self.basis,
            "repo_head": self.repo_head,
        }


@dataclass
class _Sandbox:
    """内存沙箱：Session（生产 dataclass 只读复用）+ 内存事件轨。"""

    sess: Session = field(default_factory=lambda: Session(session_id="replay-lab-sandbox"))
    events: list[dict] = field(default_factory=list)


def _persist_e1_form(sb: _Sandbox, user_text: str) -> None:
    """E1 落盘构造复刻（engine.py:421-427 现行生产语句的字面行为）。"""
    user_msg = Message(
        role="user",
        content=user_text,
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )
    sb.sess.messages.append(user_msg)
    sb.events.append(
        {
            "type": "message.appended",
            "payload": {
                "index": len(sb.sess.messages) - 1,
                "role": user_msg.role,
                "content": user_msg.content,
                "source": user_msg.source.value,
                "metadata": dict(user_msg.metadata),
            },
        }
    )


def _scenario_e1_abuse(sb: _Sandbox, sample: str) -> str:
    """剧本1：内部调用方以外部轨迹文本为 user_text 调用 E1（无通道凭据）。"""
    _persist_e1_form(sb, sample)
    return "内部调用方以外部轨迹文本为 user_text 调用 engine.run 落盘构造（无 ingress 凭据、不经 feishu/web）"


def _scenario_interop_legacy_tail(sb: _Sandbox, sample: str) -> str:
    """剧本2：interop 历史版本 tail「转 user」——视图注入，不落盘。

    复刻历史行为签名：inbox Message 存入 _interop_tail_messages，
    build 期以 system→user 角色转换进 provider 视图尾部；全程零
    sess.messages.append（对 interop.py 历史 tail 链路的语义复刻）。
    """
    _tail: list[Message] = [
        Message(role="system", content=sample, source=MessageSource.SYSTEM)
    ]
    view_tail = [
        {"role": "user", "content": m.content, "metadata": {"interop_tail": True}}
        for m in _tail
    ]  # 视图转换（历史 build.py:1077-1124 语义）；不触发 _persist_e1_form
    sb.events.append(
        {"type": "interop.view_only", "payload": {"tail_count": len(view_tail)}}
    )
    return "interop 历史 tail 链路：仅 provider 视图转换，零 session 落盘"


def _scenario_err1210_defer_residual(sb: _Sandbox, sample: str) -> str:
    """剧本3：升级窗口进程内 defer 残留重放——视图层，不落盘。

    复刻 err1210 defer 槽位语义：_interop_tail_messages 持帧 → 现行
    _inject_interop_messages 开头主动清退（interop.py:218-235 语义），
    清退仅记 action 不落消息。
    """
    legacy_tail: list[Message] = [
        Message(role="system", content=sample, source=MessageSource.SYSTEM)
    ]
    retired = len(legacy_tail)
    legacy_tail.clear()
    sb.events.append(
        {"type": "interop.external_input", "payload": {"action": "legacy_defer_retired", "count": retired}}
    )
    return "err1210 defer 残留：重放即被清退（观测事件 only），零 session 落盘"


SCENARIOS: dict[str, object] = {
    "e1_abuse": _scenario_e1_abuse,
    "interop_legacy_tail": _scenario_interop_legacy_tail,
    "err1210_defer_residual": _scenario_err1210_defer_residual,
}


def _current_head(repo_root: str | Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip()[:12] if out.returncode == 0 else "unknown"
    except Exception:  # noqa: BLE001 — 取证辅助，容错
        return "unknown"


def replay_candidate_path(
    candidate: str, sample: str, *, repo_root: str | Path = "."
) -> ReplayVerdict:
    """执行候选通路剧本并出具四条件复现回执（design §2.2 组4 契约）."""
    if candidate not in SCENARIOS:
        raise ValueError(f"未知候选通路: {candidate}（可用: {sorted(SCENARIOS)}）")
    sb = _Sandbox()
    basis = str(SCENARIOS[candidate](sb, sample))  # type: ignore[operator]

    user_msgs = [m for m in sb.sess.messages if m.role == "user"]
    mislabeled = [
        m
        for m in user_msgs
        if (m.metadata or {}).get("program_origin") is False
    ]
    with_signature = [m for m in mislabeled if content_has_trace_signature(m.content)]
    # 条件4：沙箱剧本不经任何外部通道（无 feishu/web 注入路径）
    via_external_channel = False

    conditions = {
        "persisted_role_user": bool(user_msgs),
        "program_origin_false": bool(mislabeled),
        "trace_signature_hit": bool(with_signature),
        "not_via_feishu_web": not via_external_channel,
    }
    snapshot = [
        {
            "index": i,
            "role": m.role,
            "origin_layer": (m.metadata or {}).get("origin_layer"),
            "program_origin": (m.metadata or {}).get("program_origin"),
            "sha1_12": hashlib.sha1(str(m.content).encode("utf-8")).hexdigest()[:12],
            "chars": len(str(m.content)),
        }
        for i, m in enumerate(sb.sess.messages)
    ]
    reproduced = all(conditions.values())
    return ReplayVerdict(
        candidate=candidate,
        reproduced=reproduced,
        conditions=conditions,
        persisted_snapshot=snapshot,
        basis=basis,
        repo_head=_current_head(repo_root),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default="e1_abuse", choices=sorted(SCENARIOS))
    ap.add_argument("--sample-file", required=True, help="脱敏样本文件（取 content 字段或纯文本）")
    ap.add_argument("--out", default=None, help="回执 JSON 落盘路径")
    args = ap.parse_args()
    raw = Path(args.sample_file).read_text(encoding="utf-8")
    try:
        sample = str(json.loads(raw.splitlines()[0])["payload"]["content"])
    except Exception:  # noqa: BLE001 — 纯文本形态
        sample = raw
    verdict = replay_candidate_path(args.candidate, sample)
    text = json.dumps(verdict.to_dict(), ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] reproduced={verdict.reproduced} -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
