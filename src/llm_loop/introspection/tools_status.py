"""架构状态/检索类工具实现（M16 审计 FR-AUDIT-AI-14 拆分: corrections.py → tools_status.py）.

- architecture_status: LLM 拉取架构运行状态（通道一）
- search_archive / search_records: 统一检索（压缩档案 / 历史记录·记忆·档案）

R3（tasks §3）: search_records 工具归因闭环——limit 收口、typed 归因捕获链
（InvalidSearchKindError → [参数错误] / 其余 → [内部错误] 脱敏回执）、三态回执
分流与 [检索诊断] 段渲染（诊断透传展示链，全坏 ≠ 真实零命中 ≠ 扫描失败）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.introspection.search import (
    _VALID_KINDS,
    InvalidSearchKindError,
    InvalidSearchQueryError,
)

# R3(P1-2): hint 与 _VALID_KINDS 同源生成（事实源唯一，消除手写清单漂移；
# 下划线名跨模块导入有 test_introspection.py:391 既有先例）
_SEARCH_RECORDS_KIND_HINT = "/".join(sorted(_VALID_KINDS))


def _sanitize_error_summary(exc: BaseException) -> str:
    """[内部错误] 回执摘要：异常消息压缩单行 + home 前缀脱敏 + ≤300 字符.

    脱敏与 store 层 ``_sanitize_trace`` 同口径（Path.home() 前缀 → ~，防
    str(exc) 泄漏 /Users/... 绝对路径）；单行压缩天然无堆栈多行展开。
    """
    line = " ".join(f"{exc}".split())
    home = str(Path.home())
    if home and home != "/":
        line = line.replace(home, "~")
    return line[:300]


def _read_last_diagnostics(search_fn: Any) -> dict | None:
    """读取检索实现最近一次经验库检索诊断四要素（duck-typing，缺失优雅降级 None，D11）.

    兼容注入形态：绑定方法（经 ``__self__`` 到达检索器）、直接暴露
    ``last_diagnostics`` 属性的适配器对象、其它未知实现（None → 无诊断段）。
    工具层不 import 任何具体检索器类型——search_fn 注入抽象不被破坏。
    """
    owner = getattr(search_fn, "__self__", None)
    for obj in (owner, search_fn):
        diag = getattr(obj, "last_diagnostics", None)
        if isinstance(diag, dict):
            return diag
    return None


def _parse_limit(args: dict) -> int | ToolResult:
    """R3(P1-3): limit 收口——非法值返回 [参数错误] 回执，不再以未分类异常逃逸.

    None/空串 → 默认 10（既有缺省语义）；其余经 int()，(TypeError, ValueError)
    → [参数错误] 三段式回执。
    """
    raw = args.get("limit")
    if raw is None or raw == "":
        return 10
    try:
        return int(raw)
    except (TypeError, ValueError):
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[参数错误] 事实: limit '{raw}' 取值不合法。\n"
                "原因: limit 须为整数。\n"
                "建议: 省略 limit（默认 10）或提供 1-50 的整数后重试。"
            ),
            tool_call_id="",
            tool_name="search_records",
        )


def _kind_param_error_receipt(exc: InvalidSearchKindError) -> ToolResult:
    """R3(P1-2/D5): typed 归因——仅 kind 校验异常归 [参数错误]（文案结构同既有契约）."""
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=(
            f"[参数错误] 事实: {exc}\n原因: kind 取值不合法。\n"
            f"建议: 可选 {_SEARCH_RECORDS_KIND_HINT}。"
        ),
        tool_call_id="",
        tool_name="search_records",
    )


def _query_param_error_receipt(exc: InvalidSearchQueryError) -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=(
            f"[参数错误] 事实: {exc}\n原因: 当前 kind 的 query 语法不合法。\n"
            "建议: file_effect 使用空 query、operation:<id> 或服务返回的 before_seq:<n>。"
        ),
        tool_call_id="",
        tool_name="search_records",
    )


def _internal_error_receipt(kind: str, exc: BaseException) -> ToolResult:
    """R3(P1-2/D5): 执行期任意异常归 [内部错误]（脱敏摘要、无堆栈无绝对路径、可行建议）."""
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=(
            f"[内部错误] 事实: {type(exc).__name__}: {_sanitize_error_summary(exc)}\n"
            f"原因: kind={kind} 检索执行期间发生内部异常。\n"
            "建议: 可更换其它合法 kind（如 episode）重试，或联系运维依据日志定位数据问题。"
        ),
        tool_call_id="",
        tool_name="search_records",
    )


def _scan_error_receipt(kind: str, scan_error: str) -> ToolResult:
    """R3(P0-4): 扫描失败态 FAILURE 回执（不伪装成业务零结果）."""
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=(
            f"[内部错误] 事实: 经验库目录扫描失败: {scan_error}\n"
            f"原因: kind={kind} 检索涉及的经验库目录级扫描失败。\n"
            "建议: 检查 experiences 目录权限后重试，或联系运维处理。"
        ),
        tool_call_id="",
        tool_name="search_records",
    )

# EVO-20260826: architecture_status() 无 dimensions 时默认返回精简子集，
# 避免全量快照 >8000 字符被截断且不归档→search_archive 取不回（RULE-AI-11.1 截断类型 c）。
# 默认子集为 AI 定向所需轻量维度；重维度（action_trace/tool_history/message_flow/
# memory_state/architecture_config/process_versions/recovery/model_fallback）按需 dimensions=<维度> 分页查询。
_DEFAULT_DIMS = [
    "current_phase",
    "context_usage",
    "pending_actions",
    "exception_log",
    "rules_version",
    "program_faults",
]

# 完整维度清单（与 status.py ArchitectureStatusProvider.snapshot 的 avail 键保持同步；
# test_status_all_dims_in_sync 守护防漂移）。
_ALL_DIMS = [
    "current_phase",
    "action_trace",
    "tool_history",
    "message_flow",
    "memory_state",
    "context_usage",
    "exception_log",
    "architecture_config",
    "rules_version",
    "workspace_changed",
    "process_versions",
    "model_fallback",
    "pending_actions",
    "recovery",
    "program_faults",
    "causality",
]


def run_status(ctx: Any, status_provider: Any, args: dict) -> ToolResult:
    """architecture_status: 拉取架构状态快照（维度可按需裁剪）.

    EVO-20260826: 无 dimensions 时默认返回精简子集 + 分页提示（避免全量>8000 截断不可检索）。
    """
    if status_provider is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[架构状态不可用] 架构自省未启用（SELF_INSPECTION_ENABLED=0）或状态提供器未装配。",
            tool_call_id="",
            tool_name="architecture_status",
        )
    dims = args.get("dimensions")
    # EVO-20260818 防御归一化: 模型可能把 array 传成字符串（如 "context_usage"）——
    # 原实现按字符迭代导致全部维度 unavailable；字符串按逗号/空白拆分，
    # 非列表（数字/对象等）一律回落全量。
    if isinstance(dims, str):
        dims = [d.strip() for d in re.split(r"[,，\s]+", dims) if d.strip()] or None
    if not isinstance(dims, list):
        dims = None
    default_view = dims is None
    if default_view:
        dims = _DEFAULT_DIMS
    if "causality" in dims:
        snap = status_provider.snapshot(
            session_id=current_session_id(ctx), dimensions=dims
        )
    else:
        # Preserve the established duck-typed status-provider contract for every
        # ordinary dimension; causality is the only session-scoped extension.
        snap = status_provider.snapshot(dimensions=dims)
    if default_view:
        snap["_default_view_hint"] = (
            "[默认精简视图] 显示维度: " + ", ".join(_DEFAULT_DIMS)
            + "。完整维度: " + ", ".join(_ALL_DIMS)
            + "。按 dimensions=<维度> 分页查询（如 architecture_status(dimensions=[\"architecture_config\"])）。"
        )
    _pending = snap.get("pending_actions", {}) if isinstance(snap, dict) else {}
    _raw_requirements = (
        _pending.get("capability_requirements", ())
        if isinstance(_pending, dict)
        else ()
    )
    _capability_requirements = tuple(
        str(name) for name in (_raw_requirements or ()) if str(name).strip()
    )
    text = json.dumps(snap, ensure_ascii=False, indent=2)
    # M19 FIX-03: 8000 字符静默截断如实标注（标注拼接在截断段之后，保证标注可见）
    # EVO-20260826: 默认精简视图后截断罕见（仅当单维度本身极大），保留作安全网。
    if len(text) > 8000:
        from llm_loop.core.run_context import current_evidence_shadow_enabled

        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=text[:8000]
            + "\n[快照截断] 超出 8000 字符部分未显示（可缩小 dimensions 精确查询，如仅查 architecture_config）。",
            tool_call_id="",
            tool_name="architecture_status",
            raw_observation=text if current_evidence_shadow_enabled.get() else None,
            capability_requirements=_capability_requirements,
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=text,
        tool_call_id="",
        tool_name="architecture_status",
        capability_requirements=_capability_requirements,
    )


def current_session_id(ctx: Any) -> str:
    """当前会话（由循环注入；默认空则检索全部）.

    P0-5(2026-08-15): contextvar 优先——并发 run 期间按当前执行上下文定位
    本会话（ctx.session_id 为环境回退，跨会话并发时其值为最后写入者，不可信）。
    """
    try:
        from llm_loop.core.run_context import current_session_id as _sid_var

        sid = _sid_var.get()
        if sid:
            return sid
    except Exception:  # noqa: BLE001 — 上下文不可用回退 ctx 字段（零回归）
        pass
    return getattr(ctx, "session_id", "") or ""


def run_search_archive(ctx: Any, archive: Any, args: dict, session_id_fn: Any, summarizer: Any = None) -> ToolResult:
    """search_archive: 检索被压缩的历史/超长结果（T22）.

    R2: with_summary=true 时对命中条目生成 LLM 语义摘要（AI 按需触发，增加计费）。
    """
    query = str(args.get("query", "")).strip()
    if not query:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content='[参数错误] 事实: 缺少检索关键词。\n原因: query 为必填。\n建议: 提供关键词后重试（如 search_archive(query="文件名")）。',
            tool_call_id="",
            tool_name="search_archive",
        )
    if archive is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[压缩档案不可用] 事实: 压缩档案未装配。\n原因: ARCHIVE_ENABLED=0 或 ArchiveStore 未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="search_archive",
        )
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 50))
    role = args.get("role") or None
    tool_name = args.get("tool_name") or None
    hits = archive.search(session_id_fn(), query, limit=limit, role=role, tool_name=tool_name)
    if not hits:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[search_archive] 未找到匹配 '{query}' 的压缩档案条目（不伪造结果）。",
            tool_call_id="",
            tool_name="search_archive",
        )
    with_summary = bool(args.get("with_summary", False))
    lines: list[str] = []
    for h in hits[:6]:
        ts = h.get("ts", "")
        role_h = h.get("role", "")
        src = h.get("tool_name") or h.get("source", "")
        header = f"[{ts}] {role_h}/{src}"
        if with_summary:
            content_preview = str(h.get("content_preview", ""))
            # ``content_preview`` is an index projection, not the exact archive source.
            # Calling an LLM on that preview and labelling the result a semantic summary
            # would overstate source coverage. Keep the legacy parameter compatible but
            # return only truthful preview/index facts. Full-source synopsis is a separate
            # model-authored derived view bound to an exact source SHA/ref.
            if str(h.get("summary_source", "")) == "identity_filtered":
                filtered_summary = str(h.get("summary", "") or "[身份问答详情已略]")
                lines.append(f"{header}: {filtered_summary}")
            else:
                stored_summary = str(h.get("summary", "") or "")
                summary_source = str(h.get("summary_source", "") or "unknown")
                lines.append(
                    f"{header}: archive_index_summary(source={summary_source}, "
                    "projection_complete=false, full_source_semantic_summary_generated=false): "
                    f"{stored_summary[:300]}\n原文片段(preview_only=true): {content_preview[:400]}"
                )
        else:
            lines.append(
                f"{header}: {str(h.get('summary', ''))[:200]}"
            )
    if not with_summary:
        lines.append("原文片段: " + str(hits[0].get("content_preview", ""))[:400])
    content = "[search_archive] 命中 " + str(len(hits)) + " 条:\n" + "\n".join(lines[:6])
    # M19 FIX-02: 命中 > 展示数时如实标注（AI 请求 limit 却只见 6 条，需告知真实命中数）
    if len(hits) > 6:
        content += (
            f"\n[仅显示前 6 条] 共 {len(hits)} 条命中（limit={limit}）。"
            "可缩小 query 或提高 limit 精确检索。"
        )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="search_archive",
    )



def run_event_stream(search_fn: Any, args: dict) -> ToolResult:
    """event_stream: 统一事件流视图（EVO-20260814）."""
    if search_fn is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[事件流不可用] 事实: event_stream 未装配。\n原因: 检索实现未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="event_stream",
        )
    streams = str(args.get("streams", "all")).strip() or "all"
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit") or 50)
    limit = max(1, min(limit, 200))
    since = str(args.get("since", "")).strip()
    try:
        result = search_fn.event_stream(streams=streams, query=query, limit=limit, since=since)
    except Exception as exc:  # noqa: BLE001 — 事件流读取失败如实回执
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[事件流读取失败] 事实: {exc}\n原因: 审计流读取异常。\n建议: 检查 audit_dir 后重试。",
            tool_call_id="",
            tool_name="event_stream",
        )
    if not result:
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[event_stream] 无匹配事件（streams={streams}, query='{query}'）。不伪造视图。",
            tool_call_id="",
            tool_name="event_stream",
        )
    lines: list[str] = []
    for e in result:
        lines.append(f"[{e.get('ts', '')}] {e.get('stream', '?')}: {str(e.get('summary', ''))[:200]}")
    content = "[event_stream] 统一事件流 " + str(len(result)) + " 条（旧→新）:\n" + "\n".join(lines)
    if len(result) == limit:
        content += f"\n[已达 limit={limit} 上限] 如需更早事件可提高 limit 或加 since 过滤。"
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="event_stream",
    )


def run_search_records(ctx: Any, search_fn: Any, args: dict, session_id_fn: Any) -> ToolResult:
    """search_records: 统一检索运行记录/记忆/压缩档案（T23）."""
    if search_fn is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[统一检索不可用] 事实: search_records 未装配。\n原因: 检索实现未注入。\n建议: 检查配置后重试。",
            tool_call_id="",
            tool_name="search_records",
        )
    kind = str(args.get("kind", "all")).strip()
    query = str(args.get("query", "")).strip()
    # R3(P1-3): limit 收口（原 int() 位于归因 try 之外，非法值无回执形态直接逃逸）
    parsed_limit = _parse_limit(args)
    if isinstance(parsed_limit, ToolResult):
        return parsed_limit
    limit = max(1, min(parsed_limit, 50))
    # R8.5: resolved episodes are index-first history. Reuse the existing query
    # field so hydration does not permanently expand every request's tool schema:
    #   kind=episode, query=""                    -> recent refs
    #   kind=episode, query="keyword"             -> search index
    #   kind=episode, query="episode:<ref>"       -> bounded hydrate
    #   kind=episode, query="truncated:<ref>"     -> bounded exact partial hydrate
    #   either ref + ``#offset=N``                 -> next page
    _episode_ref = ""
    _episode_offset = 0
    if kind == "episode" and query.startswith(("episode:", "truncated:")):
        _match = re.fullmatch(
            r"((?:episode|truncated):[^#]+)(?:#offset=(\d+))?", query
        )
        if _match is not None:
            _episode_ref = _match.group(1)
            _episode_offset = int(_match.group(2) or 0)
    if kind == "episode" and _episode_ref:
        hydrate = getattr(search_fn, "hydrate_episode", None)
        if not callable(hydrate):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[episode hydrate 不可用] resolved episode 检索器未装配。",
                tool_call_id="",
                tool_name="search_records",
            )
        try:
            # An explicit recovery read is different from ordinary compact history
            # hydration: the model has already chosen to inspect the exact source.
            # Return as much exact source as the tool's physical output budget allows;
            # only genuinely larger artifacts paginate with a monotonic next_offset.
            _hydrate_chars = 100_000 if _episode_ref.startswith("truncated:") else 6000
            hydrated_raw = hydrate(
                session_id=session_id_fn(),
                ref=_episode_ref,
                offset=_episode_offset,
                max_chars=_hydrate_chars,
            )
        except (TypeError, ValueError) as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[参数错误] episode hydrate 参数无效: {exc}",
                tool_call_id="",
                tool_name="search_records",
            )
        if hydrated_raw is None:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[search_records] 未找到 episode ref={_episode_ref}（不伪造结果）。",
                tool_call_id="",
                tool_name="search_records",
            )
        if not isinstance(hydrated_raw, dict):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[episode hydrate 异常] 检索器返回了非结构化结果。",
                tool_call_id="",
                tool_name="search_records",
            )
        hydrated: dict[str, Any] = hydrated_raw
        next_offset = hydrated.get("next_offset")
        header = (
            f"[episode hydrate] ref={_episode_ref} offset={hydrated.get('offset', 0)} "
            f"total_chars={hydrated.get('total_chars', 0)} "
            f"complete={'true' if hydrated.get('complete') else 'false'}"
        )
        if next_offset is not None:
            header += (
                f" next_offset={next_offset}"
                f" next_query={_episode_ref}#offset={next_offset}"
            )
        content = header + "\n" + str(hydrated.get("content") or "")
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=content,
            tool_call_id="",
            tool_name="search_records",
        )
    try:
        result = search_fn(kind=kind, query=query, limit=limit, session_id=session_id_fn())
    except InvalidSearchKindError as exc:
        # R3(P1-2/D5): typed 归因——异常类型即来源，仅 kind 校验异常归 [参数错误]
        #（捕获顺序：typed 在前、泛化在后）
        return _kind_param_error_receipt(exc)
    except InvalidSearchQueryError as exc:
        return _query_param_error_receipt(exc)
    except Exception as exc:  # noqa: BLE001 — 执行期异常如实归因 [内部错误]，禁止伪装参数错误
        return _internal_error_receipt(kind, exc)
    # R3(P0-3/P0-4): 三态回执分流 + [检索诊断] 段（诊断透传展示链）
    return _finalize_search_records(search_fn, kind, query, limit, result)


def _single_line(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _render_experience_record(record: dict, fallback_kind: str) -> str:
    """Render either a thin discovery card or an explicitly hydrated experience."""
    ts = str(record.get("ts", ""))
    title = str(record.get("summary", ""))
    ref = str(record.get("experience_ref") or record.get("key") or "")
    status = str(record.get("status", ""))
    applicability = str(record.get("task_applicability") or "not_evaluated")
    source = str(record.get("source") or {})
    lifecycle = [
        f"{name}={record.get(name)}"
        for name in ("superseded_by", "promoted_to_rule", "last_verified_at")
        if record.get(name)
    ]
    lifecycle_suffix = (" | " + " | ".join(lifecycle)) if lifecycle else ""
    if not record.get("hydrated"):
        scenario = _single_line(record.get("scenario"))
        return (
            f"[{ts}] {record.get('kind', fallback_kind)}: {title} | "
            f"experience_ref={ref} | status={status} | "
            f"task_applicability={applicability} | scenario={scenario} | source={source}"
            f"{lifecycle_suffix}"
        )
    fields = [
        f"[{ts}] {record.get('kind', fallback_kind)}: {title}",
        f"experience_ref={ref}",
        f"status={status}",
        f"task_applicability={applicability}",
        f"representation={record.get('representation', 'full_record')}",
        f"projection_complete={str(bool(record.get('projection_complete'))).lower()}",
        f"created_at={record.get('created_at', '')}",
        f"updated_at={record.get('updated_at', '')}",
        f"source={source}",
        *lifecycle,
        f"tags={record.get('tags', [])}",
        f"scenario={record.get('scenario', '')}",
        f"root_cause={record.get('root_cause', '')}",
        f"solution={record.get('solution', '')}",
        f"evidence={record.get('evidence', '')}",
        f"body={record.get('body', '')}",
    ]
    return "\n".join(fields)


def _render_synopsis_record(record: dict, fallback_kind: str) -> str:
    ref = str(record.get("ref") or record.get("id") or "")
    summary = str(record.get("summary") or "")
    head = (
        f"[{record.get('ts', '')}] {record.get('kind', fallback_kind)}: "
        f"synopsis_ref={ref} | source_ref={record.get('source_ref', '')} | "
        f"source_kind={record.get('source_kind', '')} | "
        f"source_sha256={record.get('source_sha256', '')} | "
        f"source_complete={str(bool(record.get('source_complete'))).lower()} | "
        f"source_range={record.get('source_start', 0)}:{record.get('source_end', 0)} | "
        f"source_ref_state={record.get('source_ref_state', 'not_checked')} | "
        f"task_applicability={record.get('task_applicability', 'not_evaluated')} | "
        f"representation={record.get('representation', 'model_authored_synopsis')} | "
        f"projection_complete={str(bool(record.get('projection_complete'))).lower()}"
    )
    exact_read = str(record.get("exact_summary_read") or "")
    suffix = f" | exact_summary_read={exact_read}" if exact_read else ""
    return head + f" | synopsis={_single_line(summary, 300)}" + suffix


def _render_rule_record(record: dict, fallback_kind: str) -> str:
    ref = str(record.get("rule_ref") or record.get("key") or "")
    title = str(record.get("summary") or "")
    representation = str(record.get("representation") or "rule_card")
    complete = str(bool(record.get("projection_complete"))).lower()
    applicability = str(record.get("task_applicability") or "not_evaluated")
    version = str(record.get("source_version_token") or "")[:16]
    head = (
        f"{record.get('kind', fallback_kind)}: {title} | rule_ref={ref} | "
        f"authority={record.get('authority', 'rule_sot')} | representation={representation} | "
        f"projection_complete={complete} | task_applicability={applicability} | "
        f"source_version={version}"
    )
    if record.get("hydrated"):
        return head + f"\nsource={record.get('source', '')}\ncontent={record.get('content', '')}"
    synopsis = str(record.get("synopsis") or "")
    return head + f" | synopsis={synopsis}"


def _finalize_search_records(
    search_fn: Any, kind: str, query: str, limit: int, result: list[dict]
) -> ToolResult:
    """R3(P0-3/P0-4): 三态回执分流 + [检索诊断] 段渲染（降级诊断真正展示给模型）.

    ①扫描失败（scan_error 非空）→ FAILURE（禁止伪装业务零结果）；
    ②部分损坏零命中（skipped>0）→ SUCCESS + 跳过说明 + 诊断段（非"未找到匹配"式伪装）；
    ③真实零命中 → 既有"未找到匹配"文案（唯一允许形态，健康态无诊断段零噪音）；
    ④命中 → 既有展示链 + 尾部 [检索诊断]（仅非零要素出现）。
    诊断经 duck-typing 读取（属性缺失优雅降级为既有回执形态），仅含计数与状态
    标志，不携带被跳过文档文件名/路径/堆栈。
    """
    diag = _read_last_diagnostics(search_fn)
    scan_error = diag.get("scan_error") if diag else None
    skipped = int(diag.get("skipped") or 0) if diag else 0
    degraded = int(diag.get("degraded") or 0) if diag else 0
    if scan_error:
        return _scan_error_receipt(kind, str(scan_error))

    def _diag_section(n: int) -> str:
        parts = [f"命中 {n} 条"]
        if degraded:
            parts.append(f"降级字段记录 {degraded} 条")
        if skipped:
            parts.append(f"跳过不可解析文档 {skipped} 个（库不完整）")
        return "[检索诊断] " + "；".join(parts)

    if not result:
        if skipped > 0:
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=(
                    f"[search_records] 未命中 '{query}'。注意: 本次扫描跳过 {skipped} 个"
                    "不可解析文档，结果可能不完整。\n" + _diag_section(0)
                ),
                tool_call_id="",
                tool_name="search_records",
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=f"[search_records] 未找到匹配 '{query}' 的记录（不伪造结果）。",
            tool_call_id="",
            tool_name="search_records",
        )

    lines: list[str] = []
    raw_lines: list[str] = []
    for r in result[:limit]:
        record_kind = str(r.get("kind", kind))
        if record_kind == "experience":
            rendered = _render_experience_record(r, kind)
            lines.append(rendered)
            raw_lines.append(rendered)
            continue
        if record_kind == "rule":
            rendered = _render_rule_record(r, kind)
            lines.append(rendered)
            raw_lines.append(rendered)
            continue
        if record_kind == "synopsis":
            rendered = _render_synopsis_record(r, kind)
            lines.append(rendered)
            raw_lines.append(rendered)
            continue
        if record_kind == "file_effect":
            rendered = (
                f"[{r.get('ts', '')}] file_effect: operation={r.get('operation_id', '')} "
                f"origin={r.get('origin', '')} path={r.get('path', '')} "
                f"effect_state={r.get('effect_state', 'outcome_unknown')} "
                f"receipt_state={r.get('receipt_state', 'unknown')} "
                f"current_state={r.get('current_state', 'not_checked')} "
                f"causation_proven={r.get('causation_proven', False)} "
                f"auto_reexecuted={r.get('auto_reexecuted', False)} "
                f"artifact_ref={r.get('artifact_ref', '')} "
                f"precondition_checked={r.get('precondition_checked')} "
                "task_applicability=not_evaluated"
            )
            if r.get("next_query"):
                rendered += f" next_query={r.get('next_query')}"
            lines.append(rendered)
            raw_lines.append(rendered)
            continue
        summary = str(r.get("summary", ""))
        prefix = f"[{r.get('ts', '')}] {r.get('kind', kind)}: "
        if r.get("kind") == "method":
            method_ref = str(r.get("key", ""))
            status = str(r.get("status", ""))
            description = str(r.get("description", ""))
            card = f"{summary} ({method_ref}, status={status}) — {description}".strip()
            if r.get("projection_complete"):
                body = str(r.get("body", ""))
                quals = r.get("qualification_entries") or []
                full = card + f"\n--- exact Method ---\n{body}"
                if quals:
                    full += "\n--- qualification ---\n" + json.dumps(quals, ensure_ascii=False)
                lines.append(prefix + full)
                raw_lines.append(prefix + full)
            else:
                lines.append(prefix + card[:500])
                raw_lines.append(prefix + card)
            continue
        lines.append(prefix + summary[:200])
        raw_lines.append(prefix + summary)
    content = "[search_records] 命中 " + str(len(result)) + " 条:\n" + "\n".join(lines[:6])
    # M19 FIX-02: 命中 > 展示数时如实标注（真实命中数 len(result)，非截断后计数）
    if len(result) > 6:
        content += (
            f"\n[仅显示前 6 条] 共 {len(result)} 条命中（limit={limit}）。"
            "可缩小 query 或提高 limit 精确检索。"
        )
    if degraded or skipped:
        content += "\n" + _diag_section(len(result))
    from llm_loop.core.run_context import current_evidence_shadow_enabled

    raw_content = "[search_records] 命中 " + str(len(result)) + " 条:\n" + "\n".join(raw_lines)
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=content,
        tool_call_id="",
        tool_name="search_records",
        raw_observation=raw_content if current_evidence_shadow_enabled.get() else None,
    )


def current_params(ctx: Any) -> dict:
    """当前生效参数（动态优先）."""
    if ctx.runtime is not None:
        return ctx.runtime.current()
    return dict(ctx.strategy)
