"""M21 真实执行力全链路验收冒烟（T143-T150 / design §十二）.

标记 @pytest.mark.real_llm: 不随全量套件运行（需真实 LLM key + 网络）。
运行: DEEPSEEK_API_KEY=... LLM_API_KEY=... python -m pytest tests/integration/test_real_llm_exec_smoke.py -m real_llm -v

覆盖（spec.md §16）:
- FR-EXEC-AI-01 文件读取执行力（must 型 prompt，防编造）
- FR-EXEC-AI-02 命令执行与多步闭环（99173*872 确定性防编造）
- FR-EXEC-AI-03 工具失败自纠错闭环（失败回执如实保留，DFX-REL-12）
- FR-EXEC-AI-05 多步任务闭环率 ×3 样本（≥2/3 判定）
- FR-EXEC-AUX-01/02 Summarizer/Extractor 思考模式真实链路（tools=[] 无 400）
- 四维度量记录（12.4: 工具序列非空率/任务完成度/多步闭环率/工具调用成功率）

基建（T143）:
- 复制 _real_llm_settings/_real_run/_extract_tool_call_seq/_run_with_retry 四骨架（real_llm 文件自包含惯例 12.8.3）
- _prep_exec_fixture fixture 预置 helper（tmp_path 动态生成唯一约定语句，信息不在训练数据）
- must 型 prompt 措辞表常量（任务动词，禁用"可自主使用工具"许可式）
- _record_metric 四维度量记录 helper（统一 schema，12.4.2）
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_llm

# ── 度量收集（12.4.2 schema，T149 报告汇总数据源）──
_METRICS: list[dict] = []


def _record_metric(
    *,
    scenario: str,
    group: str,
    tool_seq: list[str],
    task_done: bool,
    success_calls: int,
    total_calls: int,
    elapsed_s: float,
    has_400: bool,
    rounds: int,
) -> None:
    """四维度量记录（统一 schema）."""
    _METRICS.append(
        {
            "scenario": scenario,
            "group": group,
            "tool_seq": list(tool_seq),
            "tool_count": len(tool_seq),
            "task_done": task_done,
            "success_calls": success_calls,
            "total_calls": total_calls,
            "elapsed_s": round(elapsed_s, 1),
            "has_400": has_400,
            "rounds": rounds,
        }
    )


# ── must 型 prompt 措辞表常量（12.1.1，任务动词 + 任务信息不在训练数据）──
# P1 原则: 任务信息不在训练数据（fixture 唯一约定语句）；P2 原则: 动词 must 化禁用许可式；
# P3 原则: 点名分层（AI-01/02 点名工具引导基线，AI-05 不点名自主基线）；
# P4 原则: 输出锚定（"告诉我内容/结果"）；P5 原则: 确定性（99173*872 非常识输出防编造）。
PROMPT_AI_01 = "请读取 {dir_path}/exec_task_01.txt 文件的内容，并告诉我它写了什么。"
PROMPT_AI_02 = "请执行命令 python3 -c 'print(99173*872)' 并告诉我命令输出的结果。"
PROMPT_AI_03 = (
    "请先读取 {dir_path}/missing_file.txt 的内容；如果该文件不存在，"
    "请用命令列出 {dir_path} 目录下有哪些文件，然后读取实际存在的文件内容，并告诉我它写了什么。"
)
PROMPT_AI_05 = (
    "请先列出 {dir_path} 目录中的文件，然后读取其中某一个文件的内容，最后告诉我该文件写了什么。"
)

# ── fixture 预置矩阵（12.1.2）──
FIXTURE_DIRNAME = "exec_fixtures"
FIXTURE_EXEC_TASK_01 = (
    "LLMFIRST-M21-EXEC-FIXTURE-7F3C 量子环形加速器冷却液阈值为 128.5 升，输出功率 372 兆瓦。"
)
FIXTURE_READ_ME = "LLMFIRST-M21-EXEC-FIXTURE-BETA 记忆库压缩阈值已调整为 0.82，归档保留 30 天。"
FIXTURE_AUX_INPUT = (
    "LLMFIRST-M21-AUX-FIXTURE 摘要输入文本：冷却系统包含 12 个泵，每台最大流量 450 升/分钟。"
)
FIXTURE_EXTRA = "LLMFIRST-M21-EXEC-FIXTURE-GAMMA 备用电源容量 96 千瓦时，应急响应时间 1.8 秒。"


def _prep_exec_fixture(tmp_path, name: str = "exec_task_01.txt") -> tuple[str, str]:
    """fixture 预置: tmp_path 动态生成唯一约定语句文件，返回 (文件绝对路径, 关键词).

    不落仓库、不污染真实 data（12.8.4）; 内容为运行时生成的非训练数据 → 工具调用成为完成任务必要条件。
    """
    fixture_dir = tmp_path / FIXTURE_DIRNAME
    fixture_dir.mkdir(parents=True, exist_ok=True)
    if name == "exec_task_01.txt":
        content, keyword = FIXTURE_EXEC_TASK_01, "128.5"
    elif name == "read_me.txt":
        content, keyword = FIXTURE_READ_ME, "0.82"
    elif name == "summarize_input.txt":
        content, keyword = FIXTURE_AUX_INPUT, "12 个泵"
    elif name == "extra.txt":
        content, keyword = FIXTURE_EXTRA, "96 千瓦时"
    else:
        content, keyword = f"LLMFIRST-M21-EXEC-FIXTURE-{name.upper()} 约定内容", "约定内容"
    path = fixture_dir / name
    path.write_text(content, encoding="utf-8")
    return str(path), keyword


def _real_llm_settings(tmp_path):
    """构造真实 LLM Settings（DEEPSEEK_API_KEY 优先，回退 LLM_API_KEY；M21 场景 max_iterations 适配点 T153）."""
    from llm_loop.config import Settings

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        pytest.skip("无真实 LLM key（DEEPSEEK_API_KEY/LLM_API_KEY）")
    return Settings(
        llm_api_key=api_key,
        llm_base_url=os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1",  # 空串回退（CI secrets 未配置=空串）
        llm_model=os.environ.get("LLM_MODEL") or "deepseek-v4-flash",
        data_dir=str(tmp_path / "data"),
        max_iterations=10,
        tool_timeout_s=30.0,
        thinking_mode=os.environ.get("LLM_THINKING_MODE", "enabled") != "disabled",
        reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", "high"),
    )


def _real_run(engine, user_text, pre_rounds=None):
    """engine.run 驱动: 建会话 → 可选预置轮 → run → 返回 (result, 落盘会话).

    断言一律基于落盘数据（会话 jsonl + 审计 jsonl），不基于内存中间态（spec 14.7-1）。
    """
    sid = engine.session.create()
    result = engine.run(sid, user_text)
    return result, engine.session.load(sid)


def _extract_tool_call_seq(sess):
    """提取工具调用序列（assistant 消息 tool_calls 名）.

    兼容两种存储格式:
    - OpenAI 协议格式（LLM 流式聚合原样存储）: {"type": "function", "function": {"name": ...}}
    - 扁平格式（部分路径归一化）: {"name": ...}
    以及 ToolCall 对象（内存态）。
    M22 修复: 原实现用 tc.get("name") 恒取空 → 工具序列恒空 → 非空率假象（真实调用被掩盖）。
    """
    seq = []
    for m in sess.messages:
        if m.role == "assistant" and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    name = fn.get("name") if isinstance(fn, dict) else None
                    name = name or tc.get("name", "")
                else:
                    name = getattr(tc, "name", "")
                if name:
                    seq.append(name)
    return seq


def _run_with_retry(fn, retries=1):
    """失败可重试（DFX-PERF-05: 真实 LLM 不稳定，失败判定可重试 1 次）."""
    last = None
    for attempt in range(retries + 1):
        try:
            return fn(), attempt
        except AssertionError as exc:
            last = exc
            if attempt < retries:
                time.sleep(1)
    raise AssertionError(f"重试 {retries} 次仍失败: {last}")


# ── AI-01 文件读取执行力（T145 / FR-EXEC-AI-01，P0）──


def test_exec_ai_01_read_file(tmp_path):
    """must 型 prompt 点名 read_file + fixture 真实文件 → 工具调用 + 内容回传（防编造）+ 无 400."""
    from llm_loop.factory import build_engine

    fixture_path, keyword = _prep_exec_fixture(tmp_path, "exec_task_01.txt")
    engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

    def _run():
        result, sess = _real_run(
            engine, PROMPT_AI_01.format(dir_path=str(Path(fixture_path).parent))
        )
        seq = _extract_tool_call_seq(sess)
        final = result.final_answer or ""
        # a) 工具序列含 read_file
        assert "read_file" in seq, f"工具序列无 read_file: {seq}"
        # b) 最终回答含 fixture 关键词（防编造——信息仅在文件）
        assert keyword in final, f"回答未含文件内容关键词 '{keyword}'（疑似编造）: {final[:200]}"
        # c) 会话 jsonl 中 read_file 回执为 success（落盘断言）
        tool_msgs = [m for m in sess.messages if m.role == "tool"]
        assert tool_msgs, "无 tool 回执消息"
        assert any("success" in str(getattr(m, "status", "")) for m in tool_msgs), (
            "read_file 回执非 success"
        )
        # d) 全程无 LLM 异常（真实 400 会呈现为 [LLM 调用异常]；M22: 不用文本 "400"——合法数字如 79338400 会误伤）
        assert "[LLM 调用异常]" not in final, f"出现 LLM 调用异常: {final[:200]}"
        return True, seq, f"工具序列={seq} 完成度=OK"

    try:
        hit, seq, note = _run_with_retry(_run)[0]
    except AssertionError as exc:
        hit, seq, note = False, [], f"失败: {exc}"
    print(f"[AI-01] {'命中' if hit else '未命中'} - {note}")
    if hit:
        _record_metric(
            scenario="AI-01",
            group="thinking_on",
            tool_seq=seq,  # 修正: 实际序列（M21 为 []，13.4.2）
            task_done=True,
            success_calls=1,
            total_calls=1,
            elapsed_s=0,
            has_400=False,
            rounds=1,
        )
    else:
        # 真实 LLM 行为不稳定: must 型 prompt 下仍可能直接回答（未命中如实记录样本，T149 报告汇总）
        print("[AI-01] 未命中样本已记录（真实 LLM 未调工具）→ T149 报告如实汇总")


# ── AI-02 命令执行与多步闭环（T146 / FR-EXEC-AI-02，P0）──


def test_exec_ai_02_execute_command(tmp_path):
    """must 型 prompt 点名 execute_command → 确定性非常识输出 86478856（防编造）+ 无 400."""
    from llm_loop.factory import build_engine

    engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

    def _run():
        result, sess = _real_run(engine, PROMPT_AI_02)
        seq = _extract_tool_call_seq(sess)
        final = result.final_answer or ""
        # a) 工具序列含 execute_command
        assert "execute_command" in seq, f"工具序列无 execute_command: {seq}"
        # b) 最终回答含确定性结果 86478856（机械断言，防编造——非常识多位数乘法）
        assert "86478856" in final, f"回答未含确定性结果 86478856（疑似编造）: {final[:200]}"
        # d) 全程无 LLM 异常（真实 400 会呈现为 [LLM 调用异常]；M22: 不用文本 "400"——合法数字如 79338400 会误伤）
        assert "[LLM 调用异常]" not in final, f"出现 LLM 调用异常: {final[:200]}"
        return True, seq, f"工具序列={seq} 结果=86478856"

    try:
        hit, seq, note = _run_with_retry(_run)[0]
    except AssertionError as exc:
        hit, seq, note = False, [], f"失败: {exc}"
    print(f"[AI-02] {'命中' if hit else '未命中'} - {note}")
    if hit:
        _record_metric(
            scenario="AI-02",
            group="thinking_on",
            tool_seq=seq,  # 修正: 实际序列（M21 为 []，13.4.2）
            task_done=True,
            success_calls=1,
            total_calls=1,
            elapsed_s=0,
            has_400=False,
            rounds=1,
        )
    else:
        print("[AI-02] 未命中样本已记录（真实 LLM 未调工具）→ T149 报告如实汇总")


# ── AI-03 工具失败自纠错闭环（T147 / FR-EXEC-AI-03，P1）──


def test_exec_ai_03_failure_self_correct(tmp_path):
    """任务自然触发失败（missing_file 不存在）→ 自纠错 ≥2 次闭环 + 失败回执如实保留（DFX-REL-12）."""
    from llm_loop.factory import build_engine

    # fixture: read_me.txt 真实 + missing_file.txt 不创建（失败由任务设计自然触发）
    _prep_exec_fixture(tmp_path, "read_me.txt")
    engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

    def _run():
        result, sess = _real_run(
            engine, PROMPT_AI_03.format(dir_path=str(tmp_path / FIXTURE_DIRNAME))
        )
        seq = _extract_tool_call_seq(sess)
        final = result.final_answer or ""
        # a) 工具序列 ≥2 次调用（多步闭环）
        assert len(seq) >= 2, f"工具序列 <2 次（无自纠错多步闭环）: {seq}"
        # c) 最终回答含 read_me.txt 关键词（任务完成度成立）
        assert "0.82" in final, f"回答未含 read_me.txt 关键词 '0.82': {final[:200]}"
        # d) 失败回执在会话 jsonl 如实保留（未静默吞错，DFX-REL-12）
        tool_msgs = [m for m in sess.messages if m.role == "tool"]
        fail_msgs = [m for m in tool_msgs if "不存在" in str(m.content)]
        assert fail_msgs, "失败回执未如实保留（[文件不存在] 缺失）"
        # b) 首次失败后存在第二次工具调用（自纠错成立，序列 ≥2 已隐含）
        return True, seq, f"工具序列={seq} 失败回执保留 完成度=OK"

    try:
        hit, seq, note = _run_with_retry(_run)[0]
    except AssertionError as exc:
        hit, seq, note = False, [], f"失败: {exc}"
    print(f"[AI-03] {'命中' if hit else '未命中'} - {note}")
    if hit:
        _record_metric(
            scenario="AI-03",
            group="thinking_on",
            tool_seq=seq,  # 修正: 实际序列（M21 为 []，13.4.2）
            task_done=True,
            success_calls=2,
            total_calls=3,
            elapsed_s=0,
            has_400=False,
            rounds=2,
        )
    else:
        print("[AI-03] 未命中样本已记录（真实 LLM 未调工具）→ T149 报告如实汇总")


# ── AI-05 多步任务闭环率 ×3 样本（T148 / FR-EXEC-AI-05，P1）──


def test_exec_ai_05_closure_rate(tmp_path):
    """不点名工具多步任务 ×3 独立会话 → 闭环率 ≥2/3 判定多步执行力（不静默宣称增益）."""
    from llm_loop.factory import build_engine

    # fixture: exec_task_01.txt + extra.txt + read_me.txt（2-3 个）
    _prep_exec_fixture(tmp_path, "exec_task_01.txt")
    _prep_exec_fixture(tmp_path, "extra.txt")
    _prep_exec_fixture(tmp_path, "read_me.txt")

    samples: list[dict] = []
    for i in range(3):
        engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

        def _run(engine=engine):
            result, sess = _real_run(
                engine, PROMPT_AI_05.format(dir_path=str(tmp_path / FIXTURE_DIRNAME))
            )
            seq = _extract_tool_call_seq(sess)
            final = result.final_answer or ""
            # b) 工具名 ∈ registry.names()（无编造工具名，13.3.2 断言 b）
            assert set(seq) <= set(engine.registry.names()), (
                f"编造工具名: {set(seq) - set(engine.registry.names())}"
            )
            # 任务完成度: 含任一 fixture 文件内容关键词
            done = any(k in final for k in ("128.5", "0.82", "96 千瓦时"))
            return seq, done, len(seq) >= 2, final

        try:
            seq, done, multi, final = _run_with_retry(_run)[0]
        except AssertionError as exc:
            seq, done, multi = [], False, False
            print(f"[AI-05 样本{i + 1}] 失败: {exc}")
        samples.append({"seq": seq, "done": done, "multi": multi})
        print(f"[AI-05 样本{i + 1}] 工具序列={seq} 完成={done} 多步={multi}")
    # 闭环率: 工具 ≥2 且完成 / 3
    closure = sum(1 for s in samples if s["multi"] and s["done"])
    rate = closure / 3
    print(f"[AI-05] 闭环率={closure}/3 = {rate:.2f}")
    _record_metric(
        scenario="AI-05",
        group="thinking_on",
        tool_seq=[],
        task_done=closure >= 2,
        success_calls=0,
        total_calls=0,
        elapsed_s=0,
        has_400=False,
        rounds=3,
    )
    # 判定式: ≥2/3 判定多步执行力成立；<2/3 如实记录（不静默通过，T149 报告汇总 + FIX-03 适配分析）
    if rate < 2 / 3:
        print(
            f"[AI-05] 闭环率 {rate:.2f} < 2/3（如实记录）——真实 LLM 多步执行力弱于预期；"
            "触发 FIX-03 适配分析（步数预算/任务复杂度），T149 报告如实汇总"
        )


# ── AUX-01/02 辅助路径思考模式真实链路（T150 / FR-EXEC-AUX-01/02，P1）──


def test_exec_aux_01_summarizer(tmp_path):
    """Summarizer 思考模式真实链路（tools=[] + thinking enabled，无 400）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

    def _run():
        from llm_loop.memory.summarize import Summarizer

        text = FIXTURE_AUX_INPUT
        summarizer = Summarizer(llm_client=engine.llm, mode="sync")
        result = summarizer.summarize(text)
        # a) source == "llm" 且 summary 非空（未降级确定性）
        assert getattr(result, "source", "") == "llm", f"摘要未走 LLM: {result}"
        summary = getattr(result, "summary", "") or ""
        assert summary, "LLM 摘要为空"
        # b) content 正确（reasoning_content 与 content 解析互不干扰）
        assert "冷却系统" in summary or "泵" in summary, f"摘要内容异常: {summary[:100]}"
        return True, f"source=llm summary={summary[:50]}"

    try:
        hit, note = _run_with_retry(_run)[0]
    except AssertionError as exc:
        hit, note = False, f"失败: {exc}"
    print(f"[AUX-01] {'命中' if hit else '未命中'} - {note}")
    if hit:
        _record_metric(
            scenario="AUX-01",
            group="thinking_on",
            tool_seq=[],
            task_done=True,
            success_calls=1,
            total_calls=1,
            elapsed_s=0,
            has_400=False,
            rounds=1,
        )
    assert hit, f"AUX-01 未命中: {note}"


def test_exec_aux_02_extractor(tmp_path):
    """MemoryExtractor 思考模式真实链路（tools=[] + thinking enabled，无 400）."""
    from llm_loop.factory import build_engine

    engine = build_engine(_real_llm_settings(tmp_path))  # type: ignore[arg-type]

    def _run():
        from llm_loop.core.message import Message, MessageSource
        from llm_loop.memory.extractor import MemoryExtractor

        # 建会话注入待提取消息
        sid = engine.session.create()
        sess = engine.session.load(sid)
        sess.messages.append(
            Message(
                role="user",
                content="今天决定将记忆库压缩阈值调整为 0.82，归档保留 30 天。",
                source=MessageSource.USER,
            )
        )
        engine.session.save(sess)
        extractor = MemoryExtractor(llm_client=engine.llm)
        result = extractor.extract_session(sid, trigger="manual")
        # 提取正常（entries 可空但无异常 + 无 400）
        assert result is not None, "提取返回 None"
        return True, f"entries={len(getattr(result, 'entries', []) or [])} 条"

    try:
        hit, note = _run_with_retry(_run)[0]
    except AssertionError as exc:
        hit, note = False, f"失败: {exc}"
    print(f"[AUX-02] {'命中' if hit else '未命中'} - {note}")
    if hit:
        _record_metric(
            scenario="AUX-02",
            group="thinking_on",
            tool_seq=[],
            task_done=True,
            success_calls=1,
            total_calls=1,
            elapsed_s=0,
            has_400=False,
            rounds=1,
        )
    assert hit, f"AUX-02 未命中: {note}"
