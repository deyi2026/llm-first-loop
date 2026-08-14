"""蒸馏数据集导出工具（export_distill）核心模块（薄壳、纯读只读，spec.md P0-1~P0-4）.

定位: 把 `data/sessions/*.json` 会话轨迹导出为带思考链的 ReAct JSONL 蒸馏数据集。

原则（spec §五）:
- 纯读只读: 对源 session 文件仅 open('r') + json.load，不做写/删/迁移/备份。
- 不做训练: 只产数据不训练，无数据增强/切分/训练调用（"不是训练框架"）。
- 不做 fork 扩充（D3/P1）: 仅读取校验 parent_id/branch_id，不触发任何行为。
- 不做事件源重构（D1/P2）与 pre-step 过滤钩子（D4）: 以内置过滤规则替代。
- 不新增 env 配置项: 参数面仅 CLI，阈值/策略落为模块级常量。
- fail-open: 单文件损坏/解析失败如实标注跳过，不中断整体导出。

模块组成:
- 纯函数: `load_session_file` / `split_segments` / `segment_has_non_success` /
  `check_closed_loop` / `normalize_tool_call` / `build_react_sample`
- 编排: `run_export`
- 数据类: `FilteredSegment` / `ExportReport`
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_INPUT_DIR = "data/sessions/"
_DEFAULT_OUTPUT_DIR = "data/export_distill/"
_STATUS_VALUES = {"success", "failure", "timeout", "error"}


def load_session_file(path: Path) -> dict:
    """读会话 JSON 文件并校验结构（仅读；JSON 解析/结构错误向调用方抛出以 fail-open）.

    Args:
        path: 会话 JSON 文件路径.

    Returns:
        解析后的会话 dict.

    Raises:
        json.JSONDecodeError: JSON 解析失败.
        ValueError: 结构不合法（缺 session_id / messages 非数组）.
        OSError: IO 异常.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("顶层非 JSON 对象")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("缺少非空 session_id")
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("messages 非数组")
    return data


def split_segments(messages: list[dict]) -> list[list[dict]]:
    """以 user 消息为段起点切分任务段（system 消息归属当前段，不进样本）.

    段首非 user 的前导消息并入首个段（由 `check_closed_loop` 判"缺开头"，防御）。

    Args:
        messages: 会话消息序列.

    Returns:
        段列表；空/异常输入返回空列表.
    """
    segments: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "user":
            if current:
                segments.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        segments.append(current)
    return segments


def segment_has_non_success(seg: list[dict]) -> str | None:
    """返回段内首个非 success 的 tool 消息 status（failure/timeout/error）；全 success → None.

    status 取值白名单 `_STATUS_VALUES`；未知取值按非 success 如实标注（防御）。
    不修改段。

    Args:
        seg: 任务段（list[dict]）.

    Returns:
        主因 status 或 None.
    """
    for msg in seg:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        status = msg.get("status")
        if status is None:
            continue
        if status not in _STATUS_VALUES:
            return status
        if status != "success":
            return status
    return None


def check_closed_loop(seg: list[dict]) -> list[str]:
    """闭环完整性校验（对齐 M40 `validate_tool_call_pairing` 配对语义）.

    返回缺口描述列表（空 = 闭环完整）:
    - 缺开头: 段首非 user
    - 缺回执: assistant(tool_calls) 后连续 tool 回执数 < 声明数（对齐 history.py:506 语义）
    - 缺结尾: 忽略 system 后段尾非"无 tool_calls 的 assistant"回复
    - 校验异常: 遍历/结构异常（fail-open 不抛）

    Args:
        seg: 任务段（list[dict]）.

    Returns:
        缺口描述列表；空列表 = 闭环完整.
    """
    try:
        gaps: list[str] = []
        if not seg:
            return ["校验异常: 空段"]
        if seg[0].get("role") != "user":
            gaps.append("缺开头")
        n = len(seg)
        for i, msg in enumerate(seg):
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            calls = msg.get("tool_calls")
            if not calls:
                continue
            declared = len(calls)
            matched = 0
            j = i + 1
            while j < n and seg[j].get("role") == "tool":
                if seg[j].get("tool_call_id"):
                    matched += 1
                j += 1
            if matched < declared:
                gaps.append(f"缺回执: 声明{declared}实际{matched}")
        tail = None
        for m in reversed(seg):
            if isinstance(m, dict) and m.get("role") != "system":
                tail = m
                break
        if tail is None or tail.get("role") != "assistant" or tail.get("tool_calls"):
            gaps.append("缺结尾")
        return gaps
    except Exception as exc:  # noqa: BLE001 — fail-open 如实标注，不抛
        return [f"校验异常: {type(exc).__name__}: {exc}"]


def normalize_tool_call(call: dict) -> dict:
    """tool_calls 元素无损扁平化: {id, type, name, arguments}（arguments 字符串原样透传）.

    源形状 `{"id", "type", "function": {"name", "arguments"}}`（OpenAI 嵌套）→
    `{"id", "type", "name", "arguments"}`（name/arguments 从 function 提取）。
    function 缺失/未知形状 → 原样返回原始 dict（防御性不破坏）。

    Args:
        call: tool_calls 元素 dict.

    Returns:
        扁平化 dict 或原始 dict（未知形状）.
    """
    if not isinstance(call, dict):
        return call
    fn = call.get("function")
    if not isinstance(fn, dict):
        return call
    return {
        "id": call.get("id"),
        "type": call.get("type"),
        "name": fn.get("name"),
        "arguments": fn.get("arguments"),
    }


def build_react_sample(session: dict, seg: list[dict], segment_index: int) -> dict:
    """构造单条 ReAct 蒸馏样本（spec §8.3 字段契约 / design §2.3.2 模型）.

    前置条件: `seg` 已通过闭环校验（本函数不再校验）。
    thought/action/observation 与源逐字节一致；缺失思考链如实置 null（不伪造）。

    Args:
        session: 会话 dict（含 session_id/created_at/title/status 等顶层字段）.
        seg: 已通过过滤的任务段.
        segment_index: 会话内段序号（从 0 起）.

    Returns:
        ReAct 样本 dict.
    """
    task = ""
    if seg and isinstance(seg[0], dict):
        task = seg[0].get("content") or ""
    steps: list[dict] = []
    final_answer = ""
    n = len(seg)
    i = 0
    while i < n:
        msg = seg[i]
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            i += 1
            continue
        reasoning = msg.get("reasoning_content")
        thought = reasoning if reasoning else None
        calls = msg.get("tool_calls")
        if calls:
            observations: list[dict] = []
            j = i + 1
            while j < n and seg[j].get("role") == "tool":
                tc = seg[j].get("content")
                observations.append(
                    {
                        "content": tc if tc is not None else "",
                        "status": seg[j].get("status"),
                    }
                )
                j += 1
            steps.append(
                {
                    "thought": thought,
                    "action": [normalize_tool_call(c) for c in calls],
                    "observation": observations,
                }
            )
            i = j
        else:
            final_answer = msg.get("content") or ""
            i += 1
    metadata = {
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "title": session.get("title"),
        "version": session.get("version"),
        "status": session.get("status"),
        "parent_id": session.get("parent_id"),
        "branch_id": session.get("branch_id"),
    }
    return {
        "session_id": session.get("session_id"),
        "segment_index": segment_index,
        "type": "react",
        "task": task,
        "steps": steps,
        "final_answer": final_answer,
        "metadata": metadata,
    }


@dataclass
class FilteredSegment:
    """被过滤的任务段记录（统计报告辅助数据）."""

    session_id: str
    segment_index: int
    reason: str
    all_reasons: list[str] = field(default_factory=list)
    first_status: str | None = None


@dataclass
class ExportReport:
    """导出统计报告（闭环对账: passed + filtered == total, samples == passed）."""

    sessions_total: int = 0
    messages_total: int = 0
    segments_total: int = 0
    segments_passed: int = 0
    segments_filtered: int = 0
    samples_written: int = 0
    reason_counts: dict[str, int] = field(default_factory=dict)
    all_reason_counts: dict[str, int] = field(default_factory=dict)
    reasoning_present: int = 0
    reasoning_total: int = 0
    status_distribution: dict[str, int] = field(default_factory=dict)
    skipped_files: list[dict] = field(default_factory=list)
    max_observation_len: int = 0
    elapsed_s: float = 0.0
    readonly_violations: list[str] = field(default_factory=list)
    filtered_segments: list[FilteredSegment] = field(default_factory=list)

    @property
    def reasoning_coverage(self) -> float:
        """reasoning 覆盖率（present/total；无样本 → 0.0）."""
        return self.reasoning_present / self.reasoning_total if self.reasoning_total else 0.0

    def render_text(self) -> str:
        """人类可读统计表格（design §2.3.3 布局）."""
        lines = [
            "┌─ export_distill 统计报告 ────────────────────────────",
            f"处理会话数        sessions_total      = {self.sessions_total}",
            f"消息总数          messages_total      = {self.messages_total}",
            f"任务段总数        segments_total      = {self.segments_total}",
            f"通过段数          segments_passed     = {self.segments_passed}",
            f"过滤段数          segments_filtered   = {self.segments_filtered}",
        ]
        if self.reason_counts:
            main = " / ".join(
                f"{k}={v}" for k, v in sorted(self.reason_counts.items())
            )
            lines.append(f"  └─ 过滤主因 reason_counts    : {main}")
        if self.all_reason_counts:
            allr = " / ".join(
                f"{k}={v}" for k, v in sorted(self.all_reason_counts.items())
            )
            lines.append(f"  └─ 全因明细 all_reason_counts: {allr}")
        lines.append(
            f"产出样本数        samples_written     = {self.samples_written}"
        )
        lines.append(
            f"reasoning 覆盖率  reasoning           = {self.reasoning_present}/{self.reasoning_total} "
            f"({self.reasoning_coverage:.1%})"
        )
        if self.status_distribution:
            sd = " / ".join(
                f"{k}={v}" for k, v in sorted(self.status_distribution.items())
            )
            lines.append(f"非 success 分布   status_distribution = {sd}")
        lines.append(f"跳过文件          skipped_files       = {len(self.skipped_files)}")
        for sf in self.skipped_files:
            lines.append(f"  - {sf.get('file')}: {sf.get('reason')}")
        lines.append(f"最长 observation  max_observation_len = {self.max_observation_len}")
        lines.append(f"耗时              elapsed_s           = {self.elapsed_s:.2f}s")
        ok = self.segments_passed + self.segments_filtered == self.segments_total
        lines.append(
            f"└─ 对账 passed+filtered==total: {'OK' if ok else 'FAIL'} "
            f"({self.segments_passed}+{self.segments_filtered}={self.segments_total})"
        )
        return "\n".join(lines)

    def render_json(self) -> str:
        """结构化 JSON（含全字段 + 文本镜像，对账用）."""
        return json.dumps(
            {
                "sessions_total": self.sessions_total,
                "messages_total": self.messages_total,
                "segments_total": self.segments_total,
                "segments_passed": self.segments_passed,
                "segments_filtered": self.segments_filtered,
                "samples_written": self.samples_written,
                "reason_counts": self.reason_counts,
                "all_reason_counts": self.all_reason_counts,
                "reasoning_present": self.reasoning_present,
                "reasoning_total": self.reasoning_total,
                "reasoning_coverage": self.reasoning_coverage,
                "status_distribution": self.status_distribution,
                "skipped_files": self.skipped_files,
                "max_observation_len": self.max_observation_len,
                "elapsed_s": self.elapsed_s,
                "readonly_violations": self.readonly_violations,
                "reconciliation": {
                    "passed_plus_filtered": self.segments_passed
                    + self.segments_filtered,
                    "ok": self.segments_passed
                    + self.segments_filtered
                    == self.segments_total,
                },
                "text": self.render_text(),
            },
            ensure_ascii=False,
            indent=2,
        )


def run_export(
    input_dir: str | Path,
    output: str | Path,
    report_path: str | Path,
    force: bool = False,
) -> ExportReport:
    """纯读批处理: 遍历 input_dir/*.json → 切分 → 过滤 → 构造 → 写 JSONL + 报告.

    返回统计结果（正常，含跳过文件，不抛异常）。

    Args:
        input_dir: 会话输入目录.
        output: JSONL 输出路径.
        report_path: 统计报告 JSON 输出路径.
        force: 覆盖既有输出（默认拒绝已存在输出，防静默追加）.

    Returns:
        ExportReport 统计结果.

    Raises:
        FileNotFoundError: 输入目录不存在.
        FileExistsError: 输出文件已存在且非 force.
    """
    start = time.monotonic()
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise FileNotFoundError(f"输入目录不存在: {input_path}")
    out_path = Path(output)
    rep_path = Path(report_path)
    if out_path.exists() and not force:
        raise FileExistsError(f"输出文件已存在: {out_path}（使用 --force 覆盖）")

    report = ExportReport()
    json_files = sorted(input_path.glob("*.json"))
    before: dict[str, dict[str, Any]] = {}
    for p in json_files:
        try:
            raw = Path(p).read_bytes()
            before[str(p)] = {
                "mtime": Path(p).stat().st_mtime_ns,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        except OSError:
            pass  # 只读基线采样失败: 该文件不参与 mtime/哈希对比（fail-open，不阻断导出）

    lines: list[str] = []
    for path in json_files:
        try:
            session = load_session_file(path)
        except Exception as exc:  # noqa: BLE001 — fail-open 如实标注跳过
            report.skipped_files.append(
                {"file": str(path), "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        report.sessions_total += 1
        messages = session.get("messages")
        if isinstance(messages, list):
            report.messages_total += len(messages)
        segments = split_segments(messages if isinstance(messages, list) else [])
        for si, seg in enumerate(segments):
            report.segments_total += 1
            # 全量口径统计（所有段，含过滤段）: status 分布 / reasoning 覆盖率 / max observation 长度
            for m in seg:
                if not isinstance(m, dict):
                    continue
                if m.get("role") == "tool":
                    if m.get("status"):
                        report.status_distribution[m["status"]] = (
                            report.status_distribution.get(m["status"], 0) + 1
                        )
                    content = m.get("content") or ""
                    report.max_observation_len = max(report.max_observation_len, len(content))
                elif m.get("role") == "assistant":
                    report.reasoning_total += 1
                    if m.get("reasoning_content"):
                        report.reasoning_present += 1
            main_reason = segment_has_non_success(seg)
            if main_reason:
                statuses: set[str] = set()
                for m in seg:
                    if not isinstance(m, dict) or m.get("role") != "tool":
                        continue
                    s = m.get("status")
                    if s and s != "success":
                        statuses.add(s)
                _record_filtered(report, str(session.get("session_id")), si, main_reason, sorted(statuses))
                continue
            gaps = check_closed_loop(seg)
            if gaps:
                _record_filtered(report, str(session.get("session_id")), si, gaps[0], list(gaps))
                continue
            try:
                sample = build_react_sample(session, seg, si)
            except Exception as exc:  # noqa: BLE001 — fail-open 如实标注
                report.skipped_files.append(
                    {
                        "file": str(path),
                        "reason": f"样本构造失败: {type(exc).__name__}: {exc}",
                    }
                )
                continue
            lines.append(json.dumps(sample, ensure_ascii=False))
            report.segments_passed += 1
            report.samples_written += 1


    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    for p in json_files:
        try:
            if hashlib.sha256(Path(p).read_bytes()).hexdigest() != before.get(
                str(p), {}
            ).get("sha256"):
                report.readonly_violations.append(f"{p} 内容哈希变化")
            if Path(p).stat().st_mtime_ns != before.get(str(p), {}).get("mtime"):
                report.readonly_violations.append(f"{p} mtime 变化")
        except OSError:
            pass  # 导出后复核失败: 该文件跳过只读校验复核（fail-open，不阻断导出）

    report.elapsed_s = round(time.monotonic() - start, 3)
    rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(report.render_json(), encoding="utf-8")
    return report


def _record_filtered(
    report: ExportReport,
    session_id: str,
    segment_index: int,
    main_reason: str,
    all_reasons: list[str],
) -> None:
    """登记过滤段（主因 + 全因明细计数，保证每段主因只计一次）."""
    report.segments_filtered += 1
    report.reason_counts[main_reason] = report.reason_counts.get(main_reason, 0) + 1
    for r in all_reasons:
        report.all_reason_counts[r] = report.all_reason_counts.get(r, 0) + 1
    report.filtered_segments.append(
        FilteredSegment(
            session_id=session_id,
            segment_index=segment_index,
            reason=main_reason,
            all_reasons=all_reasons,
        )
    )
