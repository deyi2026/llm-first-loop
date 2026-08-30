"""SessionDigest — 会话汇总档案（EVO-20260829-06c96021 / SDD-20260830 FR-1~3）.

过程-终局两阶段架构的核心组件：工具 SUCCESS 回执的 L1 摘要块 append-only 聚合，
经尾部槽每轮注入——过程上下文薄（防漂移/缓存稳定），终局轮档案全量在场
（全证据一次推理）。缓存契约：已注入块的字节在后续轮次零改动（前缀不变式，
test_digest_prefix_invariance.py 锁定）。

零 LLM 成本：块内容纯规则（extract_key_info 复用），NFR-1。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_loop.core.injection_labels import neutralize_reference_frame


@dataclass(frozen=True)
class DigestBlock:
    """一个工具调用的 L1 摘要块（不可变——append-only 的字节稳定基础）."""

    block_id: str  # = tool_call_id（天然唯一，幂等去重键）
    tool_name: str
    args_key: str  # 关键参数摘要（≤80c）
    facts: tuple[str, ...]  # extract_key_info 要点（≤5 条）
    conclusion: str  # 结论行（≤120c）


class SessionDigest:
    """会话档案构建器（线程安全；并发 O_APPEND 持久化 FR-6.1 P2 再挂文件锁）.

    append() 幂等：同一 tool_call_id 二次追加返回 None（重复回执不产生块）。
    render() 输出稳定：按块首次出现序拼接，已有块字节零改动。
    """

    ARGS_KEY_MAX = 80
    FACTS_MAX = 5
    FACT_MAX_CHARS = 80
    CONCLUSION_MAX = 120

    def __init__(self, session_id: str, persist_dir: Path | None = None):
        self.session_id = session_id
        self._blocks: list[DigestBlock] = []
        self._seen: set[str] = set()
        self._lock = threading.Lock()
        self._persist_path = (
            persist_dir / f"{session_id}.jsonl" if persist_dir else None
        )
        if self._persist_path and self._persist_path.exists():
            self._load_persisted()

    # ── 构建 ──
    def append(
        self, tool_call_id: str, tool_name: str, content: str, arguments: dict | None = None
    ) -> DigestBlock | None:
        """工具 SUCCESS 回执 → L1 块（失败/空/重复返回 None，FR-1.5）."""
        if not tool_call_id or not content or not content.strip():
            return None
        with self._lock:
            if tool_call_id in self._seen:
                return None
            block = DigestBlock(
                block_id=tool_call_id,
                tool_name=tool_name or "?",
                args_key=self._args_key(arguments),
                facts=self._extract_facts(content),
                conclusion=self._conclusion(content),
            )
            self._seen.add(tool_call_id)
            self._blocks.append(block)
            self._persist(block)
            return block

    def update_from_messages(self, messages: list[Any]) -> int:
        """从会话消息批量提取（组装时调用）：role=tool + status SUCCESS → append.

        返回新增块数。消息对象形态兼容 Message（有 .tool_call_id/.tool_name/.content/.status）。
        """
        n = 0
        for m in messages:
            if getattr(m, "role", None) != "tool":
                continue
            if str(getattr(m, "status", "")) != "success":
                # 兼容枚举：ToolResultStatus.SUCCESS.value == "success"
                if getattr(getattr(m, "status", None), "value", None) != "success":
                    continue
            if self.append(
                str(getattr(m, "tool_call_id", "") or ""),
                str(getattr(m, "tool_name", "") or ""),
                str(getattr(m, "content", "") or ""),
                None,
            ):
                n += 1
        return n

    # ── 渲染（缓存契约核心：稳定序 + 已有块零改动）──
    def render(self) -> str:
        """档案槽全量视图。块序=首次出现序；单块渲染确定性（frozen dataclass）."""
        with self._lock:
            blocks = list(self._blocks)
        if not blocks:
            return ""
        parts = ["[会话汇总档案]（append-only，工具成功要点；原文经 search_archive 取回）"]
        for b in blocks:
            lines = [f"▸ {b.tool_name}({b.args_key})" if b.args_key else f"▸ {b.tool_name}"]
            lines.extend(
                f"  · {neutralize_reference_frame(f, ref=f'digest:{b.block_id}')}"
                for f in b.facts
            )
            if b.conclusion:
                lines.append(
                    "  ⇒ "
                    + neutralize_reference_frame(
                        b.conclusion, ref=f"digest:{b.block_id}"
                    )
                )
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def bytes_of(self, block_id: str) -> int:
        """单块渲染字节数（供指标计算 FR-3）."""
        b = next((x for x in self._blocks if x.block_id == block_id), None)
        if b is None:
            return 0
        return len(self._render_block(b))

    @property
    def block_count(self) -> int:
        with self._lock:
            return len(self._blocks)

    # ── 内部 ──
    def _render_block(self, b: DigestBlock) -> str:
        lines = [f"▸ {b.tool_name}({b.args_key})" if b.args_key else f"▸ {b.tool_name}"]
        lines.extend(
            f"  · {neutralize_reference_frame(f, ref=f'digest:{b.block_id}')}"
            for f in b.facts
        )
        if b.conclusion:
            lines.append(
                "  ⇒ "
                + neutralize_reference_frame(
                    b.conclusion, ref=f"digest:{b.block_id}"
                )
            )
        return "\n".join(lines)

    def _args_key(self, arguments: dict | None) -> str:
        if not arguments:
            return ""
        keys: list[str] = []
        for k in ("path", "url", "command", "query", "pattern", "file_path", "name", "goal_id"):
            v = arguments.get(k)
            if v:
                if k == "command":
                    keys.append("command=<recorded>")
                    continue
                s = str(v).replace("\n", " ")[: self.ARGS_KEY_MAX]
                keys.append(f"{k}={s}")
        return " ".join(keys)[: self.ARGS_KEY_MAX]

    def _extract_facts(self, content: str) -> tuple[str, ...]:
        """extract_key_info 规则提取（fail-open：异常回退空）。"""
        try:
            from llm_loop.memory.archive import extract_key_info

            facts, _paths, _s = extract_key_info(content, max_facts=self.FACTS_MAX)
            return tuple(str(f).strip()[: self.FACT_MAX_CHARS] for f in facts if str(f).strip())[
                : self.FACTS_MAX
            ]
        except Exception:  # noqa: BLE001 — fail-open
            return ()

    def _conclusion(self, content: str) -> str:
        """结论行：状态标记行优先（[状态: success] 等），回退首行。"""
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("[状态:") or s.startswith("[状态 "):
                return s[: self.CONCLUSION_MAX]
        first = next((l.strip() for l in content.splitlines() if l.strip()), "")
        return first[: self.CONCLUSION_MAX]

    def _persist(self, block: DigestBlock) -> None:
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "block_id": block.block_id,
                            "tool_name": block.tool_name,
                            "args_key": block.args_key,
                            "facts": list(block.facts),
                            "conclusion": block.conclusion,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001 — 持久化 fail-open（内存视图仍可用）
            pass

    def _load_persisted(self) -> None:
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    bid = str(d.get("block_id", ""))
                    if not bid or bid in self._seen:
                        continue
                    self._seen.add(bid)
                    self._blocks.append(
                        DigestBlock(
                            block_id=bid,
                            tool_name=str(d.get("tool_name", "?")),
                            args_key=str(d.get("args_key", "")),
                            facts=tuple(str(x) for x in d.get("facts", [])),
                            conclusion=str(d.get("conclusion", "")),
                        )
                    )
        except Exception:  # noqa: BLE001 — 加载 fail-open
            pass
