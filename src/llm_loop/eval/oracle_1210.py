"""P2 双轨二分 oracle 核心库（tasks 任务组 6；spec 5.2、design 模块 D/2.2.2-⑧）.

双轨设计（spec 5.2.1-1，R3 修订核心）:
- 轨道二"骨架重放": 等长确定性中文占位符替换全部消息内容——保 role 序列/
  条数/chars 分布/尾部邻接结构，不含会话真实内容（spec 4.3-1）。复现 → 结构维度嫌疑。
- 轨道一"内容保真重放": 完整保留原消息内容，对注入群（5-6 条）keep_mask
  二分构造保留/剥离子集，2^k 递归收敛至单条或判定组合触发（spec 5.2.1-2）。

判定矩阵（design 触维表）: 仅骨架复现 → STRUCTURE_TRIGGER；仅保真复现 →
CONTENT_TRIGGER（附最小消息集）；双轨均复现 → COMPOUND_TRIGGER；均不复现 →
NON_REPRODUCIBLE（不据此关闭 P1，等自然失败自动采样复验，spec 5.2.3-2）。
两轨必跑——禁止仅骨架轨下结论（R3 禁止项，spec 5.2.1-5）。

成本与限流（spec 5.2.1-3）: 每样本预算 ≤20 请求（跨两轨共享计数）、令牌桶
QPS ≤0.5（每 2s 至多 1 请求）、429/配额拒绝自动中止剩余变体并标注
"实验不完整 + 覆盖率"（spec 5.2.3-1）。变体先经本地 mock 预检
（httpx.MockTransport 协议合法性，不模拟 1210 语义——design 决策 4），
预检失败修正变体不消耗生产预算（spec 5.2.1-3）。

tools 原样保留（附录 B 已证伪 tools 漂移，非变量；design 决策 2）。
占位符默认单形态（"注"×n 等长确定性重复；design 决策 2 可选增强的默认关闭项）。

报告落盘: data/audit/oracle_1210/<ts>_<session8>/report.json（机器可读）+
report.md（人读，含两轨原始响应记录——spec 5.4-2 验收条件）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from llm_loop.core.loop.err1210 import is_err1210
from llm_loop.llm.errors import LLMError

logger = logging.getLogger(__name__)

# 快照 schema 版本（与 err1210._SNAPSHOT_SCHEMA 同源；独立常量防 import 私有名）
_SNAPSHOT_SCHEMA_EXPECTED = 1
_VALID_ROLES = {"system", "user", "assistant", "tool"}
_SKELETON_CHAR = "注"  # design 决策 2: 确定性中文占位（默认单形态，等长保 chars 分布）
_DEFAULT_BUDGET = 20
_DEFAULT_QPS = 0.5
# 结果分类（发送过=计入预算: 前四种；未发送不计: 后三种）
_SENT_OUTCOMES = ("err1210", "ok", "other_error", "throttled")


class Verdict(StrEnum):
    """触维判定（design 判定矩阵四枚举，P1 分支选择的唯一依据）."""

    STRUCTURE_TRIGGER = "STRUCTURE_TRIGGER"  # 仅骨架轨复现 → 尾部注入聚合
    CONTENT_TRIGGER = "CONTENT_TRIGGER"  # 仅保真轨复现 → 注入内容修复（附最小消息集）
    COMPOUND_TRIGGER = "COMPOUND_TRIGGER"  # 双轨均复现 → 聚合先行 + 内容修复跟进
    NON_REPRODUCIBLE = "NON_REPRODUCIBLE"  # 均不复现 → 挂起，等自然失败自动采样


@dataclass
class OracleSample:
    """一次 oracle 实验的输入样本（快照原样 + 派生缓存，design 类图）."""

    snapshot: dict
    skeleton_ok: bool | None = None  # mock 预检结果（None=未执行）

    @property
    def session_id(self) -> str:
        return str(self.snapshot.get("session_id", ""))

    @property
    def model(self) -> str:
        return str(self.snapshot.get("model", ""))

    @property
    def messages(self) -> list[dict]:
        return self.snapshot.get("messages") or []

    @property
    def tools(self) -> list[dict]:
        return self.snapshot.get("tools") or []

    @property
    def params(self) -> dict:
        return self.snapshot.get("params") or {}

    @property
    def span_idx(self) -> list[int]:
        """注入群消息下标（升序；无登记时空列表——保真轨无二分对象）."""
        span = self.snapshot.get("injection_span") or []
        return sorted(int(e["msg_idx"]) for e in span if "msg_idx" in e)


@dataclass
class ReplayVariant:
    """一个重放变体（keep_mask 对 span_idx 逐条对应；非 span 消息恒保留）."""

    variant_id: str
    track: str  # "skeleton" | "bisect"
    keep_mask: tuple[bool, ...]
    messages: list[dict]
    label: str = ""  # 人读说明（keep_all/strip_all/bisect 半集描述）
    keep_idx: tuple[int, ...] | None = None  # 二分半集保留的 msg_idx（对照轮为 None）
    tools_override: list[dict] | None = (
        None  # 结构轨变体级 tools 覆盖（drop-tools 用；None=沿用 sample.tools）
    )


@dataclass
class VariantResult:
    """变体执行结果（报告 variants 明细的行结构）."""

    variant_id: str
    track: str
    label: str
    keep_mask: list[bool]
    outcome: str  # err1210 | ok | other_error | throttled | preflight_failed | skipped_budget
    detail: str = ""
    round_no: int = 0
    elapsed_ms: float = 0.0


@dataclass
class OracleReport:
    """oracle 执行报告（report.json 的内存形态，design 类图）."""

    sample_ref: str
    session_id: str = ""
    model: str = ""
    variants: list[dict] = field(default_factory=list)
    verdict: str = ""
    minimal_set: list[int] | None = None
    budget: int = _DEFAULT_BUDGET
    budget_used: int = 0
    qps_actual: float = 0.0
    confidence: str = ""
    incomplete_reason: str = ""  # 空=完整；budget_exhausted | throttled
    coverage: str = ""  # 如 "3/5"（已执行/应执行含被跳过；完整实验为空）
    ts_utc: str = ""
    dry_run: bool = False
    report_dir: str = ""


# ── 6.1 快照加载 ──


def load_snapshot(path: str | Path) -> OracleSample:
    """解析模块 C 快照 JSON（err1210.snapshot_offending_payload 产出格式）.

    校验 schema 版本与必需键（messages/session_id/model）；结构异常抛 ValueError
    （oracle 是离线工具，加载失败应显式暴露而非 fail-open 静默）。
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"快照不存在: {p}")
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"快照 JSON 解析失败: {p}: {exc}") from exc
    if not isinstance(snap, dict):
        raise ValueError(f"快照顶层应为对象: {p}")
    schema = snap.get("schema")
    if schema != _SNAPSHOT_SCHEMA_EXPECTED:
        raise ValueError(
            f"快照 schema 版本不匹配: 期望 {_SNAPSHOT_SCHEMA_EXPECTED} 实际 {schema}（{p}）"
        )
    for key in ("messages", "session_id", "model"):
        if key not in snap:
            raise ValueError(f"快照缺少必需键 {key}: {p}")
    if not isinstance(snap.get("messages"), list) or not snap["messages"]:
        raise ValueError(f"快照 messages 非空列表: {p}")
    return OracleSample(snapshot=snap)


# ── 6.2 变体构造 ──


def _skeletonize(messages: list[dict]) -> list[dict]:
    """轨道二骨架替换: content 等长确定性占位（保 role/条数/chars 分布/邻接结构）.

    仅替换字符串 content；tool_calls/role 等结构字段原样（结构即变量本体，
    design 决策 2）。非字符串 content（异常形态）原样保留并依赖预检暴露。
    """
    out: list[dict] = []
    for m in messages:
        m2 = dict(m)
        content = m2.get("content")
        if isinstance(content, str):
            m2["content"] = _SKELETON_CHAR * len(content)
        out.append(m2)
    return out


def _apply_mask(sample: OracleSample, keep_mask: tuple[bool, ...]) -> list[dict]:
    """按 keep_mask 构造保真轨消息副本: keep=False 的 span 条目从序列删除.

    copy-on-write（浅拷贝消息 dict，不动快照原文）；非 span 消息恒保留。
    mask 与 span_idx 逐条对应（长度不齐抛 ValueError——编程错误应显式失败）。
    """
    span = sample.span_idx
    if len(keep_mask) != len(span):
        raise ValueError(f"keep_mask 长度 {len(keep_mask)} != 注入群 {len(span)}")
    drop = {idx for idx, keep in zip(span, keep_mask, strict=True) if not keep}
    return [dict(m) for i, m in enumerate(sample.messages) if i not in drop]


def build_variants(sample: OracleSample, *, track: str) -> list[ReplayVariant]:
    """构造指定轨道的初始变体集（tasks 6.2；二分后续轮由 run_oracle 递归驱动）.

    - skeleton: 单变体——全消息骨架替换（mask 恒 True，语义=零剥离）。
    - bisect: 初始两对照——keep_all（原样重放，基线复现确认）+ strip_all
      （全剥离，P0 降级形态对照，附录 C 已证此形态成功）。
    """
    n = len(sample.span_idx)
    if track == "skeleton":
        return [
            ReplayVariant(
                variant_id="skel-000",
                track="skeleton",
                keep_mask=tuple(True for _ in range(n)),
                messages=_skeletonize(sample.messages),
                label="skeleton_full",
            )
        ]
    if track == "bisect":
        return [
            ReplayVariant(
                variant_id="bis-r0-keep-all",
                track="bisect",
                keep_mask=tuple(True for _ in range(n)),
                messages=_apply_mask(sample, tuple(True for _ in range(n))),
                label="keep_all",
            ),
            ReplayVariant(
                variant_id="bis-r0-strip-all",
                track="bisect",
                keep_mask=tuple(False for _ in range(n)),
                messages=_apply_mask(sample, tuple(False for _ in range(n))),
                label="strip_all",
            ),
        ]
    if track == "struct":
        return _struct_variants(sample)
    raise ValueError(f"未知轨道: {track}（skeleton | bisect | struct）")


def _bisect_variants(sample: OracleSample, active: list[int], round_no: int) -> list[ReplayVariant]:
    """二分轮变体: active（仍复现的最小保留集）对半拆，各构造一个保留半集变体.

    每轮 ≤2 变体（与对照轮合计满足 spec 5.2.1-2 "每轮 ≤4"）；|active|<=1 时
    无需再拆（收敛判定在 run_oracle 循环处理，此处防御返回空）。
    keep_idx 直接携带半集 msg_idx（避免 label 文本解析的脆弱性）。
    """
    if len(active) <= 1:
        return []
    mid = (len(active) + 1) // 2
    halves = [active[:mid], active[mid:]]
    span = sample.span_idx
    out: list[ReplayVariant] = []
    for i, half in enumerate(halves):
        half_set = set(half)
        keep = tuple(idx in half_set for idx in span)
        out.append(
            ReplayVariant(
                variant_id=f"bis-r{round_no}-h{i}",
                track="bisect",
                keep_mask=keep,
                messages=_apply_mask(sample, keep),
                label=f"bisect_half{i}_keep={half}",
                keep_idx=tuple(half),
            )
        )
    return out


def _struct_variants(sample: OracleSample) -> list[ReplayVariant]:
    """结构二分变体（组 8 第二批）: 骨架复现已证结构触发，单变量分流结构特征.

    三变体各只改一个结构维度、内容保真（区别于 skeleton 轨的内容洗牌）：
    - merge-tail-user: 尾部连续 user 合并 1 条（测"连续 user 条数"维度）
    - drop-tools: tools 清空（测"tools 数量/形态"维度）
    - truncate-tail: 消息截半保尾部（测"消息规模"维度；切点后移避开孤儿 tool）
    """
    msgs = [dict(m) for m in sample.messages]
    out: list[ReplayVariant] = []
    i = len(msgs) - 1
    while i >= 0 and msgs[i].get("role") == "user":
        i -= 1
    run = msgs[i + 1 :]
    if len(run) >= 2:
        merged = dict(run[0])
        merged["content"] = "\n\n".join(str(m.get("content") or "") for m in run)
        out.append(
            ReplayVariant(
                variant_id="struct-merge-tail-user",
                track="struct",
                keep_mask=(),
                messages=msgs[: i + 1] + [merged],
                label=f"tail_user_{len(run)}to1",
            )
        )
    out.append(
        ReplayVariant(
            variant_id="struct-drop-tools",
            track="struct",
            keep_mask=(),
            messages=[dict(m) for m in msgs],
            label=f"tools_{len(sample.tools)}to0",
            tools_override=[],
        )
    )
    cut = max(1, len(msgs) // 2)
    while cut < len(msgs) and msgs[cut].get("role") == "tool":
        cut += 1
    trunc = (msgs[:1] + msgs[cut:]) if msgs[:1] and msgs[0].get("role") == "system" else msgs[cut:]
    out.append(
        ReplayVariant(
            variant_id="struct-truncate-tail",
            track="struct",
            keep_mask=(),
            messages=trunc,
            label=f"msgs_{len(msgs)}to{len(trunc)}",
        )
    )
    return out


# ── 6.3 本地 mock 预检 ──


def mock_preflight(variant: ReplayVariant) -> tuple[bool, str | None]:
    """httpx.MockTransport 协议合法性预检（design 决策 4）.

    只验: 请求体可 JSON 序列化、messages 非空、role 合法、无孤儿 tool
    （tool 消息的 tool_call_id 无前驱 assistant.tool_calls 声明）。
    不模拟 1210 语义（provider 黑盒行为，mock 无法复现——双轨设计存在的原因）。
    返回 (ok, 失败原因)；预检失败修正变体不消耗生产预算（spec 5.2.1-3）。
    """
    try:
        import httpx

        def _handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.read())  # 可序列化性 + 合法 JSON 双重验证
            msgs = payload.get("messages")
            if not isinstance(msgs, list) or not msgs:
                return httpx.Response(400, json={"preflight": "messages 为空"})
            declared: set[str] = set()
            for j, m in enumerate(msgs):
                if not isinstance(m, dict):
                    return httpx.Response(400, json={"preflight": f"消息 {j} 非对象"})
                role = m.get("role")
                if role not in _VALID_ROLES:
                    return httpx.Response(400, json={"preflight": f"消息 {j} role 非法: {role!r}"})
                if role == "assistant":
                    for tc in m.get("tool_calls") or []:
                        tc_id = (tc or {}).get("id")
                        if tc_id:
                            declared.add(str(tc_id))
                if role == "tool":
                    tc_id = m.get("tool_call_id")
                    if tc_id and str(tc_id) not in declared:
                        return httpx.Response(
                            400,
                            json={
                                "preflight": f"消息 {j} 孤儿 tool（tool_call_id={tc_id} 无前驱声明）"
                            },
                        )
            return httpx.Response(200, json={"preflight": "ok"})

        with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
            resp = client.post(
                "http://preflight.local/v1/chat/completions",
                json={"messages": variant.messages, "tools": []},
            )
            if resp.status_code != 200:
                return False, str(resp.json().get("preflight", "未知预检失败"))
            return True, None
    except Exception as exc:  # noqa: BLE001 — 序列化失败等，预检整体 fail-visible
        return False, f"预检异常: {exc}"


# ── 6.4 执行引擎 ──


class _TokenBucket:
    """简化令牌桶（固定速率单并发）: QPS=0.5 → 每 2s 至多 1 请求（design 决策 3）.

    time_fn/sleep_fn 注入便于测试（fake clock 验证节奏，不发真实等待）。
    """

    def __init__(
        self,
        qps: float,
        *,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if qps <= 0:
            raise ValueError(f"qps 必须 >0: {qps}")
        self._interval = 1.0 / qps
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._next_at = time_fn()

    def acquire(self) -> None:
        now = self._time_fn()
        wait = self._next_at - now
        if wait > 0:
            self._sleep_fn(wait)
            now = self._next_at
        self._next_at = max(now, self._next_at) + self._interval


def _outcome_of(exc: Exception | None, resp: Any) -> tuple[str, str]:
    """变体执行结果归类: (err1210 | ok | other_error | throttled, 摘要)."""
    if exc is not None:
        if isinstance(exc, LLMError) and is_err1210(exc):
            return "err1210", str(exc)[:300]
        text = str(exc)
        if "429" in text or "quota" in text.lower() or "配额" in text:
            return "throttled", text[:300]
        return "other_error", text[:300]
    content = getattr(resp, "content", None)
    return "ok", f"finish={getattr(resp, 'finish_reason', '')} content_len={len(content or '')}"


def run_oracle(
    sample: OracleSample,
    *,
    budget: int = _DEFAULT_BUDGET,
    qps: float = _DEFAULT_QPS,
    client_factory: Callable[[], Any] | None = None,
    data_dir: str | Path | None = None,
    dry_run: bool = False,
    time_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    track: str = "both",
    ticket_evidence: dict | None = None,
) -> OracleReport:
    """双轨执行编排: 骨架轨 → 保真轨二分递归 → 判定矩阵 → 报告落盘.

    - 预算跨两轨共享（≤budget 个已发送请求）；超预算自动中止（incomplete_reason）。
    - 429/配额 → 中止剩余变体（spec 5.2.3-1），保留已完成结论并标覆盖率。
    - 二分收敛: 定位单条（minimal_set 长度 1）或组合触发（子集无单点复现，minimal_set=活跃集）。
    - dry_run: 只构造变体 + mock 预检，不发送不消耗预算（CLI --dry-run 验收口径）。
    - client_factory: 生产传 LLMClient 构造工厂；测试注入 mock（chat duck-typing）。
    - track: "both"（默认，两轨必跑——R3 禁止项）| "skeleton" | "bisect"（受限轨
      不产判定，CLI --track 透传；verdict 留空并标 none-track-restricted）。
    - ticket_evidence [tasks 7.1]: spec 5.2.1-5b 例外条款——R5 工单官方确认结构性
      限制时，工单答复即结构触发的直接证据：{"ref": 工单编号, "note": 答复摘要}。
      提供时跳过骨架轨（记 skipped_ticket 变体，零预算消耗），Verdict 由
      "保真轨数据 + 官方证据源"等效两轨构成: 保真轨复现 → COMPOUND_TRIGGER，
      不复现 → STRUCTURE_TRIGGER（工单为结构证据）。
    """
    from datetime import UTC, datetime

    ts_utc = datetime.now(UTC).isoformat()
    t_start = time_fn()
    report = OracleReport(
        sample_ref=str(sample.session_id),
        session_id=sample.session_id,
        model=sample.model,
        budget=budget,
        ts_utc=ts_utc,
        dry_run=dry_run,
    )
    results: list[VariantResult] = []
    bucket = _TokenBucket(qps, time_fn=time_fn, sleep_fn=sleep_fn)
    client = client_factory() if (client_factory and not dry_run) else None
    sent_count = 0
    aborted = ""

    # ── 轨道选择 + 工单例外条款（spec 5.2.1-5b）──
    if track not in ("both", "skeleton", "bisect", "struct"):
        raise ValueError(f"未知轨道: {track}（both | skeleton | bisect | struct）")
    tracks: tuple[str, ...] = ("skeleton", "bisect") if track == "both" else (track,)
    ticket = dict(ticket_evidence or {})
    if ticket and "skeleton" in tracks:
        # 官方证据源等效骨架轨（R5 工单确认结构性限制）→ 跳过骨架轨不消耗预算
        tracks = tuple(t for t in tracks if t != "skeleton")
        results.append(
            VariantResult(
                variant_id="skel-000",
                track="skeleton",
                label="skipped_ticket",
                keep_mask=[True] * len(sample.span_idx),
                outcome="skipped_ticket",
                detail=(
                    f"工单证据（{str(ticket.get('ref') or '?')}）跳过骨架轨——"
                    "官方确认结构性限制即结构触发直接证据（spec 5.2.1-5b）"
                ),
            )
        )

    def _record(res: VariantResult) -> VariantResult:
        results.append(res)
        return res

    def _run_variant(variant: ReplayVariant, round_no: int = 0) -> VariantResult:
        """预检 → 预算闸 → 令牌桶 → 发送（结果统一入 results 明细）."""
        nonlocal sent_count, aborted
        ok, reason = mock_preflight(variant)
        if not ok:
            return _record(
                VariantResult(
                    variant_id=variant.variant_id,
                    track=variant.track,
                    label=variant.label,
                    keep_mask=list(variant.keep_mask),
                    outcome="preflight_failed",
                    detail=reason or "",
                    round_no=round_no,
                )
            )
        if dry_run:
            return _record(
                VariantResult(
                    variant_id=variant.variant_id,
                    track=variant.track,
                    label=variant.label,
                    keep_mask=list(variant.keep_mask),
                    outcome="ok",
                    detail="dry-run: 变体构造+预检通过，未发送",
                    round_no=round_no,
                )
            )
        if sent_count >= budget:
            aborted = "budget_exhausted"
            return _record(
                VariantResult(
                    variant_id=variant.variant_id,
                    track=variant.track,
                    label=variant.label,
                    keep_mask=list(variant.keep_mask),
                    outcome="skipped_budget",
                    detail=f"预算耗尽（{sent_count}/{budget}）",
                    round_no=round_no,
                )
            )
        bucket.acquire()
        exc: Exception | None = None
        resp: Any = None
        t0 = time_fn()
        try:
            assert client is not None  # 类型收窄（client_factory 装配契约；dry_run 已前置返回）
            resp = client.chat(
                variant.messages,
                variant.tools_override if variant.tools_override is not None else sample.tools,
                timeout_s=sample.params.get("timeout_s"),
                model=sample.model or None,
            )
        except Exception as send_exc:  # noqa: BLE001 — 二次异常是实验数据本体，如实记录
            exc = send_exc
        outcome, detail = _outcome_of(exc, resp)
        sent_count += 1
        if outcome == "throttled":
            aborted = "throttled"
        return _record(
            VariantResult(
                variant_id=variant.variant_id,
                track=variant.track,
                label=variant.label,
                keep_mask=list(variant.keep_mask),
                outcome=outcome,
                detail=detail,
                round_no=round_no,
                elapsed_ms=round((time_fn() - t0) * 1000, 1),
            )
        )

    # ── 轨道二: 骨架重放（单请求判定结构维度，成本最低——design 决策 1）──
    if "skeleton" in tracks:
        skel_variant = build_variants(sample, track="skeleton")[0]
        skel_result = _run_variant(skel_variant)
        sample.skeleton_ok = skel_result.outcome != "preflight_failed"

    # ── 结构轨: 单变量结构变体（组 8 第二批——骨架复现已证结构触发的维度定位）──
    if "struct" in tracks and not aborted:
        for v in build_variants(sample, track="struct"):
            _run_variant(v)
            if aborted:
                break

    # ── 轨道一: 内容保真二分（对照轮 + 递归半集轮）──
    keep_all_res: VariantResult | None = None
    if "bisect" in tracks and not aborted:
        for v in build_variants(sample, track="bisect"):
            res = _run_variant(v)
            if v.label == "keep_all":
                keep_all_res = res
            if aborted:
                break

    minimal_set: list[int] | None = None
    span = sample.span_idx
    if (
        not aborted
        and keep_all_res is not None
        and keep_all_res.outcome == "err1210"
        and len(span) > 1
    ):
        # keep_all 复现 → 二分递归；keep_all 不复现则无二分必要（保真轨记不复现）
        active = list(span)
        round_no = 1
        while len(active) > 1 and not aborted:
            halves = _bisect_variants(sample, active, round_no)
            reproduced: list[int] | None = None
            for hv in halves:
                res = _run_variant(hv, round_no=round_no)
                if res.outcome == "err1210" and hv.keep_idx is not None:
                    reproduced = list(hv.keep_idx)
                    break  # 首个复现半支继续二分；两半均不复现 → 组合触发
                if aborted:
                    break
            if aborted:
                break
            if reproduced:
                active = [i for i in active if i in set(reproduced)]
            else:
                # 两半均不复现 → 组合触发（子集无单点复现，spec 5.2.1-2 收敛标准 b）
                minimal_set = list(active)
                break
            round_no += 1
        if minimal_set is None and len(active) == 1:
            minimal_set = list(active)  # 单条定位（spec 5.2.1-2 收敛标准 a）

    # ── 判定与报告汇总 ──
    report.variants = [
        {
            "variant_id": r.variant_id,
            "track": r.track,
            "label": r.label,
            "keep_mask": r.keep_mask,
            "outcome": r.outcome,
            "detail": r.detail,
            "round_no": r.round_no,
            "elapsed_ms": r.elapsed_ms,
        }
        for r in results
    ]
    report.budget_used = sent_count
    report.minimal_set = minimal_set
    report.incomplete_reason = aborted
    skipped = sum(1 for r in results if r.outcome == "skipped_budget")
    report.coverage = f"{len(results) - skipped}/{len(results)}" if aborted else ""
    if dry_run:
        report.confidence = "none-dry-run"
    elif aborted:
        report.confidence = "low-experiment-incomplete"  # 结论降级为"初步"（spec 5.2.3-1c）
    elif ("skeleton" in tracks or ticket) and "bisect" in tracks:
        # 两轨数据齐备（骨架轨=实跑 或 工单证据等效，spec 5.2.1-5b）→ 可判 Verdict
        report.verdict = str(verdict_matrix(report))
        if ticket:
            # 工单官方确认结构性限制 → 结构触发为直接证据: 保真轨复现=复合，
            # 不复现=纯结构（spec 5.2.1-5b；覆盖矩阵的 CONTENT/NON_REPRODUCIBLE 分支）
            report.verdict = str(
                Verdict.COMPOUND_TRIGGER
                if report.verdict == str(Verdict.CONTENT_TRIGGER)
                else Verdict.STRUCTURE_TRIGGER
            )
        report.confidence = (
            "medium-non-reproducible" if report.verdict == Verdict.NON_REPRODUCIBLE else "high"
        )
    else:
        # 单轨运行（或 ticket 下无可执行轨道）→ 不出 Verdict（R3 禁止项: 禁止单轨下结论）
        report.confidence = "none-track-restricted"
    elapsed_s = max(1e-9, time_fn() - t_start)
    report.qps_actual = round(sent_count / elapsed_s, 3) if (sent_count and not dry_run) else 0.0

    # ── 6.6 报告落盘（fail-open：落盘失败不掩盖实验结论）──
    base = Path(data_dir or os.environ.get("LFL_DATA_DIR", "data"))
    ts_compact = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_dir = (
        base / "audit" / "oracle_1210" / f"{ts_compact}_{sample.session_id[:8] or 'nosession'}"
    )
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(
            json.dumps(_report_to_dict(report), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        (report_dir / "report.md").write_text(_report_markdown(report), encoding="utf-8")
        report.report_dir = str(report_dir)
    except Exception:  # noqa: BLE001
        logger.warning("oracle 报告落盘失败（结论仍在返回值中）", exc_info=True)
    return report


def _report_to_dict(report: OracleReport) -> dict:
    return {
        "sample_ref": report.sample_ref,
        "session_id": report.session_id,
        "model": report.model,
        "variants": report.variants,
        "verdict": report.verdict,
        "minimal_set": report.minimal_set,
        "budget": report.budget,
        "budget_used": report.budget_used,
        "qps_actual": report.qps_actual,
        "confidence": report.confidence,
        "incomplete_reason": report.incomplete_reason,
        "coverage": report.coverage,
        "ts_utc": report.ts_utc,
        "dry_run": report.dry_run,
    }


# ── 6.5 判定矩阵 ──


def verdict_matrix(report: OracleReport) -> Verdict:
    """四枚举判定（design 触维表；输入报告需含两轨变体结果）.

    - 骨架轨复现 = 存在 track=skeleton 且 outcome=err1210 的变体。
    - 保真轨复现 = keep_all 对照变体 outcome=err1210（二分半集复现蕴含于其中）。
    两轨必跑（R3 禁止项）：任一轨道无结果 → 抛 ValueError（防单轨下结论）。
    """
    skel = any(
        v.get("track") == "skeleton" and v.get("outcome") == "err1210" for v in report.variants
    )
    bisect = any(
        v.get("track") == "bisect"
        and v.get("label") == "keep_all"
        and v.get("outcome") == "err1210"
        for v in report.variants
    )
    has_skel_track = any(v.get("track") == "skeleton" for v in report.variants)
    has_bisect_track = any(
        v.get("track") == "bisect" and v.get("label") == "keep_all" for v in report.variants
    )
    if not (has_skel_track and has_bisect_track):
        raise ValueError(
            f"判定矩阵要求两轨数据齐备（skeleton={has_skel_track}, "
            f"bisect_keep_all={has_bisect_track}）——R3 禁止项: 禁止仅骨架轨下结论（spec 5.2.1-5）"
        )
    if skel and not bisect:
        return Verdict.STRUCTURE_TRIGGER
    if bisect and not skel:
        return Verdict.CONTENT_TRIGGER
    if skel and bisect:
        return Verdict.COMPOUND_TRIGGER
    return Verdict.NON_REPRODUCIBLE


# ── 6.6 人读报告 ──


def _report_markdown(report: OracleReport) -> str:
    """report.md 人读格式（spec 5.4-2: 含两轨原始响应记录 + 置信度声明）."""
    lines = [
        "# err1210 双轨 oracle 实验报告",
        "",
        f"- 样本会话: `{report.session_id}`　模型: `{report.model}`",
        f"- 时点(UTC): {report.ts_utc}　dry_run: {report.dry_run}",
        f"- 预算: {report.budget_used}/{report.budget}　实测 QPS: {report.qps_actual}",
        f"- 完整性: {'完整' if not report.incomplete_reason else f'不完整（{report.incomplete_reason}，覆盖率 {report.coverage}）'}",
        f"- **Verdict: {report.verdict or '（未判定）'}**　置信度: {report.confidence}",
    ]
    if report.minimal_set is not None:
        lines.append(f"- 最小消息集（msg_idx）: {report.minimal_set}")
    lines += [
        "",
        "## 变体明细（两轨原始响应记录）",
        "",
        "| 变体 | 轨道 | 轮次 | 结果 | 详情 |",
        "|---|---|---|---|---|",
    ]
    for v in report.variants:
        lines.append(
            f"| {v.get('variant_id')} | {v.get('track')} | {v.get('round_no')} "
            f"| {v.get('outcome')} | {str(v.get('detail', ''))[:160]} |"
        )
    lines += [
        "",
        "## 判定矩阵（design 触维表）",
        "",
        "| 骨架轨复现 | 保真轨复现 | 结论 |",
        "|---|---|---|",
        f"| {_track_repro(report, 'skeleton')} | {_track_repro(report, 'bisect')} | {report.verdict or '—'} |",
        "",
        "> NON_REPRODUCIBLE 不据此关闭 P1（spec 5.2.3-2）——等待自然失败自动采样复验。",
    ]
    return "\n".join(lines) + "\n"


def _track_repro(report: OracleReport, track: str) -> str:
    if track == "skeleton":
        hit = any(
            v.get("track") == "skeleton" and v.get("outcome") == "err1210" for v in report.variants
        )
    else:
        hit = any(
            v.get("track") == "bisect"
            and v.get("label") == "keep_all"
            and v.get("outcome") == "err1210"
            for v in report.variants
        )
    return "是" if hit else "否"


if __name__ == "__main__":  # pragma: no cover
    pass
