"""消息构建 mixin（EVO-20260817-e63f712f，engine.py 防膨胀拆分）.

2026-08-18 自 engine.py 迁出（engine.py 1200 行触发防膨胀守卫 test_complexity_reduction，
按建议拆 _BuildMixin）。职责: 提交 LLM 的消息序列构建（system prompt + 记忆注入 +
协调通道 inbox + 窗口锚定 + 预算分级压缩 + 缓存门禁 + 投影一致性门闸）。

纯重构: 方法体原样迁移（零行为变更），原路径可导入语义保持（REQ-REF-06 对齐）。
依赖（engine 其他 mixin）: _planned_model_label / _provider_inject_notices /
_record_action / _runtime_extract_interval / _runtime_history_budget /
_inject_interop_messages / _cache_monitor / _last_snapshot_count / _last_compact_ratio。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条)


from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from llm_loop.core.cache_health import GATE_NOTE_CONTENT  # 门禁干预知情标记

# EVO-20260818: projection_ver/check 提升到模块级（消除函数内 import 遮蔽导致的 F823）——
# 与 engine.py 顶部 re-export 同模式；stable_digest 既有模块级使用
from llm_loop.core.history import (
    projection_check,  # noqa: F401 (history 工具, 函数内使用)
    projection_ver,  # noqa: F401 (history 工具, 函数内使用)
    stable_digest,  # 投影门闸
)

# build_session_snapshot_text 定义于 engine（loop 包内）——顶层 import 会触发
# engine→build→loop/__init__ 循环（engine import build 在前），故用函数内延迟 import
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt import build_system_prompt

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class _BuildMixin:
    def _build_llm_messages(
        self, sess, memory_msgs: list[Message], max_chars: int | None = None,
        model: str | None = None,  # P1-7: per-call 模型覆盖（判定本地 provider 跳过推送式注入）
    ) -> list[dict]:
        """构造提交 LLM 的消息序列（system prompt + 记忆注入 + 历史 + 压缩另存）.

        M54: max_chars 可覆盖默认预算（模型窗口感知压缩）；None = 运行时预算（零回归）。
        P1-10: 窗口锚定——按 provider 固定历史起点（只追加不挤旧, 超预算优先降级中段),
        前缀稳定命中引擎/服务端缓存; 锚点写入 sess.history_anchors 随会话持久化。
        """
        planned_label = self._planned_model_label(model, sess)
        planned_label = self._planned_model_label(model, sess)
        provider_id = planned_label.partition("/")[0] or "default"
        anchors = sess.history_anchors or {}
        sess_anchor = int(anchors.get(provider_id, 0) or 0)
        system_prompt = build_system_prompt()
        # 记忆消息作为前置注入
        base = [m for m in memory_msgs] + list(sess.messages)
        prefix_len = len(memory_msgs)
        # RULE-AI-14 协调通道: 程序级自动注入 DSH→LFL 待处理消息（每轮 run 必感知，
        # 非仅提示词引导；实现见 core/loop/interop.py _InteropMixin，fail-open）
        # 注入位置: memory 之后、历史之前（2026-08-16 优化: system_prompt+memory 前缀
        # 有/无消息轮字节级一致，服务端缓存命中不受 inbox 影响）
        base, prefix_len = self._inject_interop_messages(base, prefix_len, sess.session_id)
        # EVO-20260817-72fcd94a L3 发送前门禁·预检（程序常态锚点管理）: 稳定段指纹
        # （system+注入）与该 session 基线不符 → 强制缓存友好压缩，当次 build 即合规化。fail-open。
        try:
            self._cache_gate_stable_fp = stable_digest(
                [(m.role, m.content) for m in base[:prefix_len]] + [system_prompt]
            )
            self._cache_monitor.preflight(sess.session_id, self._cache_gate_stable_fp)
        except Exception:  # noqa: BLE001
            self._cache_gate_stable_fp = ""
        # EVO-20260811-9ccdec97: 会话状态快照节流——每间隔注入状态帧（定位锚点，fail-open）
        # M58 配置面收敛: 间隔走 runtime（动态优先，AI 可调）
        # P1-10: 仅无锚时注入（锚定后快照为推送式注入（已打标被跳过提交）, 且避免锚点换算复杂化）
        if sess_anchor == 0:
            try:
                interval = self._runtime_extract_interval()
                if len(sess.messages) - self._last_snapshot_count >= interval:
                    evo_summary = None
                    if self.evolution_store is not None and hasattr(self.evolution_store, "summary"):
                        try:
                            s = self.evolution_store.summary()
                            evo_summary = s if isinstance(s, dict) else None
                        except Exception:
                            evo_summary = None
                    # EVO-20260818: 函数内延迟 import（engine 已加载，防顶层循环；修复
                    # 基线 NameError——原无任何 import，快照注入从未生效（被 fail-open 吞掉））
                    from llm_loop.core.loop.engine import build_session_snapshot_text

                    snapshot = Message(
                        role="system",
                        content=build_session_snapshot_text(
                            len(sess.messages), self.memory.count(), evo_summary
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={"injected_system": True},  # P1-7: 快照=推送式注入（本地 provider 下不进提交）
                    )
                    base.insert(0, snapshot)
                    prefix_len += 1
                    self._last_snapshot_count = len(sess.messages)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("会话状态快照注入失败（fail-open）", exc_info=True)
        from llm_loop.core.history import build_history_messages

        archive_sink = None
        if self.archive is not None:
            archive_sink = self._archive_sink
        # R1: 存构建中间值，供主循环在 tools_param 构造后计算 breakdown（含 tool_schema_chars）
        effective_budget = max_chars if max_chars is not None else self._runtime_history_budget()
        self._last_build_info = {
            "base": base,
            "system_prompt": system_prompt,
            "memory_msgs": memory_msgs,
            "budget": effective_budget,
        }
        # EVO-20260817: 预算分级管理——①80% 准备态（审计提示，不压缩）:
        # 长任务大几率撞顶，接近预算时让 AI 感知"下轮可能主动整理压缩"（压缩仍保留
        # 关键事实帧+档案零丢失，不打断推理）；②90% 压缩态（compact_ratio, env 可调）:
        # 预算附近提前平滑压缩（裁到 COMPRESS_TARGET_RATIO 留缓冲），优于撞顶被动压缩。
        try:
            _history_total = sum(len(m.content) for m in base)
            _compact_ratio = float(os.environ.get("COMPACT_RATIO", "0.9"))
            if 0 < _compact_ratio < 1.0:
                _prep_at = effective_budget * 0.8
                if _history_total > _prep_at and _history_total <= effective_budget * _compact_ratio:
                    self._record_action(
                        "understand.compact_prep",
                        "approaching_budget",
                        f"history {_history_total} 字符 ≥预算 80%（{int(_prep_at)}），"
                        f"下一轮可能在 {int(effective_budget*_compact_ratio)} 触发主动压缩整理；"
                        "压缩保留关键事实帧+档案零丢失，不影响推理",
                    )
        except Exception:  # noqa: BLE001
            _compact_ratio = 1.0
        self._last_compact_ratio = _compact_ratio
        # P1-10: 锚点相对传入列表 = 会话锚点 + 前置（memory/快照）长度
        anchor_arg = sess_anchor + prefix_len if sess_anchor > 0 else 0
        anchor_box: list[int] = []
        built = build_history_messages(
            base,
            system_prompt,
            max_chars=max_chars if max_chars is not None else self._runtime_history_budget(),
            compact_ratio=self._last_compact_ratio,  # EVO-20260817: 预算分级主动压缩
            session_id=sess.session_id,
            archive_sink=archive_sink,
            # RULE-AI-00: 不再传 summarizer（压缩路径不自动 LLM 摘要，AI 主动触发）
            layer_tool_trim=getattr(self.settings, "tool_trim_enabled", False),  # EVO-20260811-7baa2737: 历史分层降级
            tool_trim_age=getattr(self.settings, "tool_trim_age", 0),  # R3: 0=自适应
            tool_trim_threshold=getattr(self.settings, "tool_trim_threshold", 8000),  # EVO-A: 降级长度阈值（默认 8000）
            reasoning_tail=getattr(self.settings, "reasoning_tail", 2),  # M66 思考链瘦身
            # P1-7: provider（inject_system_notices=false）跳过推送式注入 → system 前缀静态 → 引擎缓存命中
            skip_injected_system=not self._provider_inject_notices(planned_label),
            # P1-10: 窗口锚定
            history_anchor=anchor_arg,
            anchor_out=anchor_box,
            # EVO-20260817-9d3e1f2c: 缓存友好压缩——保留锚点头部（前缀命中）只归档中段;
            # EVO-20260818: HEAD_KEEP_RATIO 默认 0.10→0.15（压缩轮即命中 system+头部 ≥70%）;
            # force 档位 HEAD_KEEP_FORCE_RATIO 默认 0.20（L3 拦截强制保留——须高于常规档位，
            # max() 两侧同值会吞掉强制语义，grill-me 2.10）; 0=关闭回到锚点前移行为；env 可调
            head_keep_chars=max(
                int(effective_budget * float(os.environ.get("HEAD_KEEP_RATIO", "0.15"))),
                int(effective_budget * float(os.environ.get("HEAD_KEEP_FORCE_RATIO", "0.20")))
                if self._cache_monitor.force_head_keep else 0,
            ),
        )
        # P1-10: 锚点推进持久化（换算回会话索引, clamp 防御）
        if anchor_box:
            new_anchor = anchor_box[0] - prefix_len
            new_anchor = max(0, min(len(sess.messages), new_anchor))
            # EVO-20260817-72fcd94a L3 归因: 锚点实际前移（≠旧锚点）→ 记入缓存失效归因窗口
            if new_anchor != sess_anchor:
                self._cache_monitor.note_anchor_moved()
            # 2026-08-16 锚点推进对齐工具轮边界（现场：tool_call_id is not found 根因）：
            # 锚点不得落在声明↔回执组内——若锚点处是 tool 回执（其声明在锚点前），
            # 拉回至该轮声明起点（整组保留，防孤儿回执）。
            while 0 < new_anchor < len(sess.messages) and sess.messages[new_anchor].role == "tool":
                new_anchor -= 1
            if sess.history_anchors is None:
                sess.history_anchors = {}
            sess.history_anchors[provider_id] = new_anchor
        # EVO-20260818（spec §5.3.1-1 c/d，grill-me B1）: interop 外部协调注入——
        # 尾部追加（GATE_NOTE 模式，转 user），system+稳定历史前缀字节不变（注入轮不断前缀）;
        # env INTEROP_INJECT_TAIL=0 回退旧行为（头部插入，见 interop.py）
        tail_msgs = getattr(self, "_interop_tail_messages", None)
        if tail_msgs:
            for _m in tail_msgs:
                _d = _m.to_llm_dict()
                if _d.get("role") == "system":
                    _d["role"] = "user"  # system 静态: 转独立 user 尾部追加
                built.append(_d)
            self._interop_tail_messages = None  # 一次性消费（每轮重扫 pending）
        # EVO-20260817-72fcd94a: 门禁干预知情标记——干预激活首轮在 built 末尾追加固定
        # system 消息（末尾追加缓存友好，不破坏前缀；让 AI 感知上下文结构变化）
        if self._cache_monitor.take_gate_note():
            built = list(built) + [{"role": "system", "content": GATE_NOTE_CONTENT}]
        # EVO-20260817-b6554376: 投影一致性门闸（借鉴 DSH seq 水印，fail-open 不阻断 run）
        # seq（消息数）负责"历史追加"水印；ver（构建参数+动态输入指纹）负责参数水印；
        # ver+seq 匹配而 built_hash 不同 → 非确定性构建/历史被改 → 告警（只读，不阻断）。
        try:
            _fp = lambda msgs: stable_digest([(m.role, m.content) for m in msgs])  # noqa: E731
            _settings_fp = stable_digest({
                "tool_trim_enabled": getattr(self.settings, "tool_trim_enabled", False),
                "tool_trim_age": getattr(self.settings, "tool_trim_age", 0),
                "tool_trim_threshold": getattr(self.settings, "tool_trim_threshold", 8000),
                "reasoning_tail": getattr(self.settings, "reasoning_tail", 2),
                "skip_injected_system": not self._provider_inject_notices(planned_label),
                "extract_interval_msgs": getattr(self.settings, "extract_interval_msgs", 20),
            })
            # EVO-20260818: interop 尾部追加后 base[:prefix_len] 仅 memory 段——
            # interop_fp 改为对注入消息指纹（tail 模式）或 memory+inbox 段（旧模式），
            # 保证 ver 与 built 中的尾部注入内容一致（投影一致性不误报）
            _interop_for_fp = (
                tail_msgs
                if tail_msgs is not None
                else [m for m in base[:prefix_len]]
            )
            _ver = projection_ver(
                model=planned_label, budget=effective_budget, anchor=sess_anchor,
                memory_fp=_fp(memory_msgs),
                interop_fp=stable_digest([(m.role, m.content) for m in _interop_for_fp]),
                system_fp=stable_digest(system_prompt),
                settings_fp=_settings_fp,
            )
            _seq = len(sess.messages)
            # 知情标记剔除: 门闸比较的 built 不含门禁干预注（末尾固定 system 消息）
            _built_for_hash = (
                built[:-1]
                if built and built[-1].get("content") == GATE_NOTE_CONTENT
                else built
            )
            _built_hash = stable_digest(_built_for_hash)
            # EVO-20260817: 压缩轮判定——主动/被动压缩归档（built 消息数 < base）属合法
            # 变化（缓存友好压缩锚点不动 → ver 不变但 built 变短），豁免投影 mismatch 误报
            _compressed_this_build = len(built) < len(base)
            _guards = sess.projection_guard if sess.projection_guard is not None else {}
            _prev = _guards.get(provider_id)
            _state = projection_check(_prev, ver=_ver, seq=_seq, built_hash=_built_hash)
            self._projection_guard_state = _state
            if _state == "mismatch" and not _compressed_this_build:
                _hint = (
                    f"[投影一致性告警] provider={provider_id} seq={_seq} ver 匹配但构建输出与上次不一致"
                    f"——非确定性构建或历史被改（追加式保证被破坏），前缀缓存可能失效（成本放大 ~50 倍）。"
                    "只读告警，是否处理由你决定。"
                )
                self._record_action("run.projection_guard", "mismatch", _hint)
            # 更新缓存行（mismatch 也更新——保留最近构建作新基准，但已告警过）
            import datetime as _dt

            _guards[provider_id] = {
                "ver": _ver, "seq": _seq, "built_hash": _built_hash,
                "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            }
            sess.projection_guard = _guards
        except Exception:  # noqa: BLE001 — 门闸失败 fail-open，不阻断 run
            logging.getLogger(__name__).warning("投影一致性门闸异常（fail-open）", exc_info=True)
        # EVO-20260817-72fcd94a L3 发送前门禁·后检（合规再出闸）: 校验稳定段与该 session
        # 基线一致；不一致 → 审计 + hint（run 末注入 final_answer），fail-open 不阻断发送。
        try:
            self._cache_gate_hint = self._cache_monitor.postcheck(
                sess.session_id, self._cache_gate_stable_fp
            )
            if self._cache_gate_hint:
                self._record_action("run.cache_gate", "drift", self._cache_gate_hint)
        except Exception:  # noqa: BLE001 — 门禁失败 fail-open
            self._cache_gate_hint = None
        # EVO-20260817: 压缩产物合规检验（锚点固化模式）——压缩轮审计产物状态:
        # 稳定段指纹（system+注入）不变 → 门禁 preflight/postcheck 自动合规（不误报）;
        # 关键事实帧+档案目录已由 build 注入（AI 持续推理所需信息整理好）;
        # 配对原子性由 _repair_tool_call_pairing 保证。检验通过才出闸（记录 ok）。
        try:
            _compressed = locals().get("_compressed_this_build", False)
            if _compressed:
                _built_chars = sum(len(m.get("content", "")) for m in built)
                _facts_injected = any(
                    isinstance(m, dict)
                    and (
                        "[压缩关键事实]" in m.get("content", "")
                        or "[压缩推理结论]" in m.get("content", "")
                    )
                    for m in built[-8:]
                )
                self._record_action(
                    "run.compact",
                    "ok" if _facts_injected else "warn",
                    f"history {locals().get('_history_total', '?')}→{_built_chars} 字符"
                    f"{'，关键事实帧已注入（推理信息整理完备）' if _facts_injected else '，关键事实帧缺失（告警）'}，"
                    "稳定段未变→门禁合规，投影门闸豁免（压缩属合法变化）",
                )
        except Exception:  # noqa: BLE001
            pass
        return built

