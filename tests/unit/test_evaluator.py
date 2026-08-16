"""单元测试: AI 自我评估聚合器与触发检测（T62-T63 / EVAL-01/02/03/04/07）."""

from __future__ import annotations

import json

from llm_loop.introspection.evaluator import (
    EvalTriggerDetector,
    SelfEvaluator,
)


def _write_jsonl(path, records: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class _Status:
    """status mock: 提供 tool_history 与 llm_rounds."""

    def __init__(self, tool_history=None, llm_rounds=0) -> None:
        self._tool_history = tool_history or []
        self._llm_rounds = llm_rounds

    def snapshot(self):
        return {
            "tool_history": self._tool_history,
            "context_usage": {"llm_rounds": self._llm_rounds},
        }


def _seed_action_trace(tmp_path, n_success=40, n_fail=10):
    """写入 action_trace.jsonl（success 动作 + error 动作）."""
    records = []
    for i in range(n_success):
        records.append(
            {
                "ts": f"t{i}",
                "phase": "action.tool_loop",
                "action_type": "tool_call",
                "detail": f"read_file f{i}",
            }
        )
    for i in range(n_fail):
        records.append(
            {
                "ts": f"e{i}",
                "phase": "action.llm_decide",
                "action_type": "llm_error",
                "detail": "timeout",
            }
        )
    _write_jsonl(tmp_path / "action_trace.jsonl", records)
    return n_success + n_fail


def test_evaluate_five_metrics(tmp_path):
    """五维指标聚合（来源可溯，EVAL-02）."""
    _seed_action_trace(tmp_path, n_success=40, n_fail=10)
    _write_jsonl(
        tmp_path / "declaration_check.jsonl",
        [{"ts": f"c{i}", "consistent": True} for i in range(20)]
        + [{"ts": "bad", "consistent": False}],
    )
    _write_jsonl(
        tmp_path / "exception_log.jsonl",
        [{"ts": f"x{i}", "error_type": "ValueError"} for i in range(3)],
    )
    status = _Status(
        tool_history=[{"name": "read_file", "status": "success"} for _ in range(18)]
        + [{"name": "read_file", "status": "failure"} for _ in range(2)],
        llm_rounds=10,
    )
    evaluator = SelfEvaluator(status_provider=status, audit_dir=tmp_path, min_samples=5, span=50)
    report = evaluator.evaluate(session_id="s1", trigger="manual")
    metrics = {m.name: m for m in report.metrics}
    # 成功率 = 40/(40+10) = 0.8
    assert metrics["success_rate"].value == 0.8
    assert metrics["success_rate"].source == "action_trace"
    # 工具效率 = 18/20 = 0.9
    assert metrics["tool_efficiency"].value == 0.9
    # 诚实性 = 20/21
    assert round(metrics["honesty_rate"].value, 4) == round(20 / 21, 4)
    # 异常率 = 3/10 = 0.3
    assert metrics["exception_rate"].value == 0.3
    # 停滞率: 10 条 llm_error（9 条同指纹重复）→ 9/50 = 0.18
    assert metrics["stagnation_rate"].value == 0.18
    # eval_id + 落盘
    assert report.eval_id.startswith("SE-")
    assert report.trigger == "manual"
    log = (tmp_path / "self_eval_log.jsonl").read_text(encoding="utf-8")
    assert report.eval_id in log


def test_evaluate_sample_insufficient(tmp_path):
    """样本不足 → value=None + 如实标注（EVAL-02，spec 10.2.3-1）.

    EVO-20260816-dc3876f9: tool_efficiency 仅无样本才 N/A（空工具历史标注"无工具调用样本"），
    其余指标维持样本不足语义。
    """
    evaluator = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path, min_samples=5)
    report = evaluator.evaluate()
    metrics = {m.name: m for m in report.metrics}
    for name, m in metrics.items():
        assert m.value is None
        if name == "tool_efficiency":
            assert m.note == "无工具调用样本"
        else:
            assert "样本不足" in m.note


def test_evaluate_stagnation_detected(tmp_path):
    """停滞率: 重复动作（同参数指纹）占比."""
    _write_jsonl(
        tmp_path / "action_trace.jsonl",
        [
            {
                "ts": f"t{i}",
                "phase": "action.tool_loop",
                "action_type": "tool_call",
                "detail": "read_file SAME",
            }
            for i in range(10)
        ],
    )
    evaluator = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path, min_samples=5)
    report = evaluator.evaluate()
    metrics = {m.name: m for m in report.metrics}
    # 10 条动作，9 条重复 → 0.9
    assert metrics["stagnation_rate"].value == 0.9
    assert metrics["success_rate"].value == 1.0


def test_evaluate_no_source_unavailable(tmp_path):
    """来源不可用 → 数据不可用如实标注（不生成无依据结论）."""
    evaluator = SelfEvaluator(status_provider=None, audit_dir=tmp_path, min_samples=5)
    report = evaluator.evaluate()
    metrics = {m.name: m for m in report.metrics}
    for m in metrics.values():
        assert m.value is None
    assert report.summary != ""


def test_eval_log_fail_open(tmp_path, monkeypatch):
    """落盘失败 → fail-open（不阻塞评估结果，DFX-REL-06）."""
    from pathlib import Path

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _broken)
    try:
        evaluator = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path)
        report = evaluator.evaluate()
    finally:
        monkeypatch.setattr(Path, "open", real_open)
    assert report.eval_id.startswith("SE-")


def test_two_evaluations_metric_readable(tmp_path):
    """M18 AA5: compare 已移除，对比交 AI——两次 evaluate 指标字段可读（AI 侧自比基础）."""
    evaluator = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path)
    _seed_action_trace(tmp_path, n_success=30, n_fail=20)
    before = evaluator.evaluate(trigger="manual")
    (tmp_path / "action_trace.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "ts": f"t{i}",
                    "phase": "action.tool_loop",
                    "action_type": "tool_call",
                    "detail": f"f{i}",
                }
            )
            for i in range(45)
        )
        + "\n",
        encoding="utf-8",
    )
    after = evaluator.evaluate(trigger="manual")
    # 两次评估 eval_id 不同可溯源，指标字段可读（AI 侧自比 delta 的基础）
    assert before.eval_id != after.eval_id
    bm = {m.name: m for m in before.metrics}
    am = {m.name: m for m in after.metrics}
    assert bm["success_rate"].value == 0.6
    assert am["success_rate"].value == 1.0  # AI 可自行计算 delta=0.4
    assert not hasattr(evaluator, "compare")


# ── EvalTriggerDetector（T63）──
def test_trigger_periodic():
    """定期触发: rounds % interval == 0."""
    d = EvalTriggerDetector(interval_rounds=50)
    t = d.check(rounds=50)
    assert t is not None and t.trigger == "periodic"
    assert d.check(rounds=25) is None


def test_trigger_milestone():
    """里程碑触发: run 完成/会话结束."""
    d = EvalTriggerDetector()
    t = d.check(rounds=3, task_completed=True)
    assert t is not None and t.trigger == "milestone"
    t2 = d.check(rounds=3, session_ended=True)
    assert t2 is not None and t2.trigger == "milestone"


def test_trigger_none_no_condition():
    """无命中条件 → None（仅提示不强制，EVAL-03）."""
    d = EvalTriggerDetector(interval_rounds=50)
    assert d.check(rounds=10) is None


def test_trigger_no_recent_params():
    """M16 审计（FR-AUDIT-AI-04/08）: check() 无 recent_* 入参（异常触发移交 AI）."""
    d = EvalTriggerDetector(interval_rounds=50)
    # periodic/milestone 仍正常
    assert d.check(rounds=50, task_completed=False).trigger == "periodic"
    assert d.check(rounds=5, task_completed=True).trigger == "milestone"


def test_eval_id_unique_across_runs(tmp_path):
    """M16 审计（FR-AUDIT-AI-10）: eval_id 含随机后缀，连续评估唯一."""
    evaluator = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path)
    r1 = evaluator.evaluate()
    r2 = evaluator.evaluate()
    assert r1.eval_id != r2.eval_id
    assert r1.eval_id.count("-") >= 3  # SE-YYYYMMDD-NNN-XXXX 格式
    # 同实例连续两次 → 当日计数递增且后缀不同


def test_eval_id_unique_across_restart(tmp_path):
    """M16 审计（FR-AUDIT-AI-10）: 模拟重启（新实例）→ 当日计数递增不重复."""
    e1 = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path)
    r1 = e1.evaluate()
    e2 = SelfEvaluator(status_provider=_Status(), audit_dir=tmp_path)  # 模拟重启
    r2 = e2.evaluate()
    assert r1.eval_id != r2.eval_id
    # 同日计数递增（SE-YYYYMMDD-NNN-XXXX）
    prefix1 = r1.eval_id.rsplit("-", 1)[0]
    prefix2 = r2.eval_id.rsplit("-", 1)[0]
    assert prefix2 > prefix1  # 计数递增
