"""ToolCycleService——工具执行循环职责面（R9-P5-02 / B5-W3-01）.

_ToolExecMixin（10 法，tool_exec.py:138-486）+ _ToolEligibilityMixin（1 法，
tool_eligibility.py）逐字平移：宿主面（events/routing mixin + settings/status/
registry/session + 停滞态 per-session 桶）经 ``self._host``；
域内互调与域状态（_skills_cache/_last_tool_eligibility）保持 self；
module 级辅助 _json_dumps_args 等留驻 tool_exec.py（REQ-REF-06 re-export 不变）。
等价证明：生成管线 AST 反替自证 + 提交门禁 PROBE 隔离树 ci_gate 全绿。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (service 模式: self 属性来自 host 注入面，pyright 无法静态解析，沿 mixin 原口径文件级关闭这两条)

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from llm_loop.core.loop.tool_exec import (
    _EMPTY_SEARCH_REMIND_AT,
    _SEARCH_LIKE_TOOLS,
    _SEARCH_TARGET_FIELDS,
    _STAGNATION_BREAK_AT,
    _STAGNATION_REMIND_AT,
    _is_empty_search_result,
    _is_search_like_call,
    _json_dumps_args,
    _search_target_key,
    _stagnation_reminder_mode,
    _tool_args_summary,
)
from llm_loop.core.message import Message, MessageSource, ToolResult
from llm_loop.introspection.status import ToolHistoryItem
from llm_loop.llm.client import LLMResponse, StreamDelta, ToolRoundInfo
from llm_loop.tools.eligibility import project_tool_schemas
from llm_loop.tools.registry import tool_result_to_message

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

class ToolCycleService:
    # EVO-20260814-aab7eb0b P2: 循环实时停滞检测阈值（连续 N 次相同指纹熔断）
    # （阈值常量 _STAGNATION_BREAK_AT 留 tool_exec.py 模块级，随 _json_dumps_args 同源导入）
    _skills_cache: tuple[float, list[tuple[str, str]]] = (0.0, [])

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _execute_tools(
        self,
        resp: LLMResponse,
        sess,
        rounds: int,
        tool_trace: list[dict],
    ) -> Iterator[StreamDelta]:
        """行动：执行工具（tool_calls），move 自 engine.py:492-553（生成器保持外泄次序）."""
        self._host._phase("action.tool_loop")
        # 约束 C1 配对: 先把 LLM 声明追加为 assistant 消息（带 tool_calls），
        # 后续 tool 回执才有前置声明（严格 API 要求，否则 400）
        if resp.tool_calls:
            assistant_decl = Message(
                role="assistant",
                content=resp.content or "",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": _json_dumps_args(tc.arguments),
                        },
                    }
                    for tc in resp.tool_calls
                ],
                reasoning_content=resp.reasoning_content,  # M20 THK-04: 工具轮回传思考链
            )
            sess.messages.append(assistant_decl)
            # D1: assistant 声明消息事件（fail-open）
            self._host._append_message_event(sess, assistant_decl)
        for tc in resp.tool_calls:
            if not tc.id:
                # 约束 C1: 缺 id 声明不可执行，如实注入反馈（AI-first 三件套）
                msg = Message(
                    role="system",
                    content=(
                        f"[工具调用异常] 事实: 声明缺少 tool_call_id，无法绑定执行（工具 '{tc.name}'）。\n"
                        f"原因: 程序不伪造执行无绑定标识的声明（协议约束）。\n"
                        f"建议: 请重新声明工具调用（确保原生 tool_calls 含 id 字段）。"
                    ),
                    source=MessageSource.SYSTEM,
                )
                sess.messages.append(msg)
                # D1: 系统注入消息事件（fail-open）
                self._host._append_message_event(sess, msg)
                self._host._record_action("action.tool_loop", "missing_tool_call_id", tc.name)
        # EVO-20260810-750e985a: 工具并发控制（只读并行/修改串行/按声明顺序回写）
        valid_calls = [tc for tc in resp.tool_calls if tc.id]
        if valid_calls:
            # HARNESS-01(2026-08-14): 中断时孤儿 tool_calls 合成回执——assistant 声明
            # （带 tool_calls）先入历史、yield 流式进展后才 execute_many；若客户端在 yield
            # 阶段断流（GeneratorExit），历史留下"有声明无回执"孤儿 → 严格 FC 协议下下次
            # 请求直接 400。兜底：中断时对未执行声明写合成"已取消"回执并立即保存会话
            # （声明数 = 结果数 + 取消数 对账不变量成立，任何保存时机历史自洽）。
            try:
                # P2-1: 工具轮次进展外泄（fail-open，yield 异常不阻断主循环）
                for tc in valid_calls:
                    # H-UI: 工具调用开始（实时状态条）
                    self._host._notify_action(
                        "tool_call",
                        tool_name=tc.name,
                        args_summary=_tool_args_summary(tc.arguments),
                    )
                    try:
                        yield StreamDelta(
                            text="",
                            tool_round=ToolRoundInfo(
                                tool_name=tc.name,
                                round_index=rounds,
                                args_summary=_tool_args_summary(tc.arguments),
                                tool_call_id=tc.id,
                            ),
                        )
                    except GeneratorExit:
                        # 客户端断流：全部声明未执行 → 合成取消回执 + 落盘（防孤儿）
                        self._synthesize_cancelled(sess, valid_calls, executed_ids=set())
                        try:
                            self._host.session.save(sess)
                        except Exception:  # noqa: BLE001 — 保存失败 fail-open
                            logger.warning("中断路径会话保存失败（fail-open）", exc_info=True)
                        raise  # 正常生成器关闭语义（重新抛 GeneratorExit）
                    except Exception:  # noqa: BLE001 — fail-open
                        logger.warning("tool_round yield 失败（fail-open）", exc_info=True)
                runner = getattr(self._host, "runner", None)
                if runner is not None and runner.enabled and runner.is_cancelled(sess.session_id):
                    self._synthesize_cancelled(sess, valid_calls, executed_ids=set())
                    return
                results = self._host.registry.execute_many(valid_calls)
                # 对账不变量: 声明数 == 结果数（缺失 → 合成取消，防孤儿声明落盘）
                if len(results) != len(valid_calls):
                    executed_ids = {r.tool_call_id for r in results if r.tool_call_id}
                    missing = [tc for tc in valid_calls if tc.id not in executed_ids]
                    if missing:
                        self._synthesize_cancelled(sess, missing, executed_ids=set())
                        logger.warning(
                            "工具对账不变量缺失: 声明 %d 结果 %d（%d 条合成取消）",
                            len(valid_calls),
                            len(results),
                            len(missing),
                        )
                for tc, result in zip(valid_calls, results, strict=False):
                    tool_trace.append(
                        {
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                            "status": result.status.value,  # GPT 审计批次4: 证据有效性门
                        }
                    )
                    self._record_tool_history(result)
                    # H-UI: 工具结果（实时状态条）
                    self._host._notify_action(
                        "tool_result", tool_name=tc.name, status=result.status.value
                    )
                    tool_msg = tool_result_to_message(
                        result, failure_guidance_enabled=self._host.registry.failure_guidance_enabled
                    )
                    sess.messages.append(tool_msg)
                    # D1: tool 回执消息事件（fail-open）
                    self._host._append_message_event(sess, tool_msg)
                    # EVO-20260814-aab7eb0b P2: 运行中停滞指纹追踪（evaluator.py:271 同构指纹）
                    # EVO-20260823-9bb27899: 传 result 供搜索类工具空结果计数
                    self._track_stagnation(tc, sess, tool_trace, result=result)
                # EVO-20260816-62977206: 工具执行后经验提示注入（末尾追加，无命中不注入）
                self._inject_experience_tips(sess, [tc.name for tc in valid_calls])
            # 注：唯一中断点 = tool_round yield（内层 except GeneratorExit 已合成+落盘+重抛）；
            # execute_many 后无 yield（同步阻塞），不重复外层兜底（防重复合成）
            except GeneratorExit:
                raise

    def _synthesize_cancelled(self, sess, calls, *, executed_ids: set[str]) -> None:
        """HARNESS-01: 对未执行声明写合成取消回执（防孤儿 tool_calls → 下轮 400）.

        消息如实标注"声明后中断未执行"，status 不设（非五态结果，不伪造成功/失败）；
        随会话落盘，任何保存时机下声明数 = 结果数 + 取消数 对账成立。
        """
        for tc in calls:
            if tc.id in executed_ids:
                continue
            cancel_msg = Message(
                role="tool",
                content=(
                    f"[执行中断] 工具 '{tc.name}' 声明后循环中断（客户端断流/引擎终止），"
                    f"该调用未执行、无副作用。"
                ),
                tool_call_id=tc.id,
                tool_name=tc.name,
                source=MessageSource.SYSTEM,
            )
            sess.messages.append(cancel_msg)
            self._host._append_message_event(sess, cancel_msg)
            self._host._record_action("action.tool_loop", "cancelled", tc.name)

    def _inject_experience_tips(self, sess, tool_names: list[str]) -> None:
        """Record that experience/skill references are available on demand.

        R8.15/E08 retires the generic post-tool catalog from automatic working
        context. Tool-name similarity, front-K/task-switch state and unseen refs
        are relevance signals, not proof that a reference is required now.

        Explicit ``search_records(kind=experience)`` and failure-specific tool
        recovery remain available.  Keep this compatibility method because older
        callers may still invoke it, but it must never query the experience store,
        append a Message, or mutate session history.
        """
        if not getattr(self._host.settings, "tool_experience_inject", True):
            return
        names = list(dict.fromkeys(str(name) for name in tool_names if str(name)))
        if not names:
            return
        try:
            action = getattr(self._host, "_record_action", None)
            if callable(action):
                action(
                    "experience.catalog",
                    "on_demand_only",
                    f"tools={','.join(names[:8])};prompt_chars=0",
                )
        except Exception:  # noqa: BLE001 — observability is non-authoritative
            logger.debug("experience catalog observability failed", exc_info=True)

    def _match_skills(self, tool_names: list[str]) -> list[tuple[str, str]]:
        """按工具名/场景关键词匹配 skills/ 下 SKILL.md（返回 (name, description)）.

        frontmatter name/description 与工具名+关键词做子串匹配；
        目录不存在/损坏 fail-open 返回空；扫描结果缓存（目录 mtime 变化才重扫）。
        """
        import re
        from pathlib import Path

        try:
            base = Path(getattr(self._host.settings, "skills_dir", "./skills"))
            if not base.is_dir():
                return []
            try:
                dir_mtime = max(
                    (p.stat().st_mtime for p in base.iterdir() if p.is_dir()), default=0.0
                )
            except OSError:
                dir_mtime = 0.0
            if self._skills_cache[0] == dir_mtime:
                cached = self._skills_cache[1]
            else:
                cached = []
                for p in sorted(base.glob("*/SKILL.md")):
                    try:
                        text = p.read_text(encoding="utf-8", errors="replace")[:2000]
                        fm = re.search(r"^---\s*\n(.*?)\n---", text, re.S | re.M)
                        meta: dict[str, str] = {}
                        if fm:
                            for line in fm.group(1).splitlines():
                                m = re.match(r"(\w+):\s*(.*)", line)
                                if m:
                                    meta[m.group(1).strip()] = m.group(2).strip().strip("\"'")
                        if meta.get("name") and meta.get("description"):
                            cached.append((meta["name"], meta["description"][:200]))
                    except (OSError, UnicodeDecodeError):
                        continue  # 损坏 skill fail-open 跳过
                self._skills_cache = (dir_mtime, cached)
            # 匹配: 工具名分词（-/_/空格分隔）命中 skill name/description 才触发。
            # 不用通用关键词池——避免"zzz_unrelated_tool"因描述含 cache/debug 等泛词而误命中。
            # SKILL.md 编写规范: description 中列出可触发的工具名（如 web_fetch/architecture_status）。
            tokens: set[str] = set()
            for n in tool_names:
                tokens.update(t for t in re.split(r"[^a-z0-9]+", n.lower()) if t)
            hits: list[tuple[str, str]] = []
            for sname, sdesc in cached:
                hay = f"{sname} {sdesc}".lower()
                if any(t in hay for t in tokens):
                    hits.append((sname, sdesc))
            return hits
        except Exception:  # noqa: BLE001 — skill 扫描 fail-open
            logger.warning("skill 扫描失败（fail-open）", exc_info=True)
            return []

    def _stagnation_fingerprint(self, tc) -> str:
        """单次工具调用指纹（evaluator.py:271 同构: 名称 + 规范化参数 JSON）.

        EVO-20260823-9bb27899: 搜索类工具取"目标指纹"——仅保留判定"找什么"的核心字段
        （_SEARCH_TARGET_FIELDS），忽略 limit/root/offset 等细节参数；
        使"换深度/换目录/换工具搜同一目标"也能连续累计停滞计数。
        """
        if tc.name in _SEARCH_LIKE_TOOLS:
            fields = _SEARCH_TARGET_FIELDS.get(tc.name, ())
            target = {k: v for k, v in (tc.arguments or {}).items() if k in fields}
            return f"{tc.name}|{_json_dumps_args(target)}"
        return f"{tc.name}|{_json_dumps_args(tc.arguments)}"

    def _stagnation_state_of_host(self) -> dict:
        """宿主停滞态读写入口（B5-W4-03 per-session 桶化；fail-open 保裸实例契约）.

        正常实例经 RunStateManager 桶（host._run_state().stagnation_state，跨会话
        不共享）；tests __new__ 绕过 __init__ 的裸服务无 mgr，回退宿主旧字段并兜
        底创建（W4-02e 立约：裸服务 fail-open，D-B5-10 同源教训前置规避）。
        """
        mgr = getattr(self._host, "_run_state_mgr", None)
        if mgr is not None:
            return mgr.bucket().stagnation_state
        state = getattr(self._host, "_stagnation_state", None)
        if state is None:
            state = self._host._stagnation_state = {
                "fp": None, "count": 0, "reminded": False,
                "empty_count": 0, "empty_reminded": False,
            }
        return state

    def _track_stagnation(self, tc, sess, tool_trace: list[dict], result=None) -> None:
        """每次工具执行后更新停滞计数（目标级指纹 + 搜索空结果），达阈值注入提醒。

        熔断决策在 engine 主循环（能 break 的位置）读取 _stagnation_should_break() 完成。
        """
        fp = self._stagnation_fingerprint(tc)
        state = self._stagnation_state_of_host()
        # ① 同目标指纹连续计数（原逻辑，指纹已升级为目标级）
        if state["fp"] == fp:
            state["count"] += 1
        else:
            state["fp"] = fp
            state["count"] = 1
            state["reminded"] = False
        if state["count"] >= _STAGNATION_REMIND_AT and not state["reminded"]:
            state["reminded"] = True
            # R8.24-B B-D3: 提醒注入取消——改道事件观测（on/shadow 记事件，off 静默）；
            # 计数/阈值/熔断机械路径不动。sess.messages 零写入（B-G2）。
            _mode = _stagnation_reminder_mode()
            if _mode != "off":
                self._host._record_action(
                    "stagnation.reminder",
                    "suppressed_shadow" if _mode == "shadow" else "suppressed",
                    f"{tc.name} x{state['count']} (prompt_injection=0)",
                )
        # ② 搜索类调用连续空结果计数（EVO-20260823-9bb27899 + 12be9cac 边界①补全）:
        #    结构化搜索工具 + execute_command 搜索命令（find/grep/rg/locate/which）——空结果=前提失效信号
        if _is_search_like_call(tc) and _is_empty_search_result(result):
            state["empty_count"] = state.get("empty_count", 0) + 1
            # 边界①补全: 搜索空结果登记否定帧（跨会话复用，防同目标反复搜索）
            try:
                from llm_loop.tools.path_registry import register_missing

                register_missing(_search_target_key(tc), source="tool:search")
            except Exception:
                logger.warning("搜索空结果登记失败（fail-open）", exc_info=True)
        else:
            state["empty_count"] = 0
            state["empty_reminded"] = False
        if state.get("empty_count", 0) >= _EMPTY_SEARCH_REMIND_AT and not state.get(
            "empty_reminded", False
        ):
            state["empty_reminded"] = True
            # R8.24-B B-D4: [搜索空结果提醒] 建议层删除——真实空结果回执本身已是事实；
            # 否定帧登记（上方 register_missing）保留（跨会话复用，事实层）。
            # 同 LFL_STAGNATION_REMINDER 开关三态事件观测，sess.messages 零写入。
            _mode = _stagnation_reminder_mode()
            if _mode != "off":
                self._host._record_action(
                    "empty_search.reminder",
                    "suppressed_shadow" if _mode == "shadow" else "suppressed",
                    f"{tc.name} 空结果 x{state['empty_count']} (prompt_injection=0)",
                )

    def _stagnation_should_break(self) -> tuple[bool, str, int]:
        """是否达熔断阈值（engine 主循环每轮工具执行后调用）。."""
        state = self._stagnation_state_of_host()
        if not state or state["count"] < _STAGNATION_BREAK_AT:
            return (False, "", 0)
        name = (state["fp"] or "").split("|", 1)[0]
        return (True, name, state["count"])

    def _schema_to_param(self, t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }

    def _resp_summary(self, resp: LLMResponse) -> str:
        if resp.tool_calls:
            return "tool_calls=" + ",".join(t.name for t in resp.tool_calls)
        return f"content={resp.content[:80] if resp.content else '(空)'}"

    def _record_tool_history(self, result: ToolResult) -> None:
        if self._host.status:
            self._host.status.record_tool_history(
                ToolHistoryItem(
                    name=result.tool_name,
                    arguments={},
                    status=result.status,
                    summary=result.content[:120],
                    duration_ms=result.duration_ms,
                )
            )

    def _project_tool_schemas_for_round(
        self,
        tool_schemas: list[dict],
        *,
        planned_label: str,
        user_text: str,
        session_messages: list[Any],
    ) -> list[dict]:
        """Apply R8.7 projection or preserve legacy behavior in shadow/off modes."""
        mode = getattr(self._host.settings, "tool_eligibility_mode", "enforce")
        if mode == "enforce":
            projection = project_tool_schemas(
                tool_schemas,
                user_text=user_text,
                session_messages=session_messages,
                mode="enforce",
            )
            effective = list(projection.schemas)
        elif mode == "shadow":
            projection = project_tool_schemas(
                tool_schemas,
                user_text=user_text,
                session_messages=session_messages,
                mode="enforce",
            )
            effective = self._host._filter_local_tools(tool_schemas, planned_label)
        else:
            self._last_tool_eligibility = {
                "configured_mode": "off",
                "applied": False,
                "original_count": len(tool_schemas),
                "visible_count": len(tool_schemas),
            }
            return self._host._filter_local_tools(tool_schemas, planned_label)

        info = projection.as_dict()
        info["configured_mode"] = mode
        info["applied"] = mode == "enforce"
        self._last_tool_eligibility = info
        try:
            self._host._record_action(
                "tool.eligibility",
                mode,
                (
                    f"model={planned_label};original={projection.original_count};"
                    f"candidate={len(projection.visible_names)};"
                    f"quarantined={len(projection.quarantined_names)};"
                    f"applied={int(mode == 'enforce')}"
                ),
            )
        except Exception:  # noqa: BLE001 — observability must not block the run
            logger.debug("tool eligibility telemetry failed (fail-open)", exc_info=True)
        return effective
