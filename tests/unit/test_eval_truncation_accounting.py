"""截断样本（轮数耗尽）与真失败的统计口径分离（2026-10-23）。

背景：域内 v2 真实跑批实测 22 样本中 5 个 verdict=False，其中 **4 个是
truncated=True**（达到最大轮数被中断）。原口径把截断样本计进分母 →
系统性低估通过率，把「执行预算不足」误报为「被测能力失败」。

本文件锁定：
  1. 截断样本不计入通过率分母，且在结果中单列
  2. 截断样本若本身判定为 True，也不计入「通过」（预算外的运气不算通过）
  3. 判定器接口新增 truncated 关键字不破坏既有调用（向后兼容）
  4. is_truncated_answer 能从历史 checkpoint 的答复文本识别截断
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_eval  # noqa: E402

from llm_loop.eval.verdicts import is_truncated_answer, run_verdict  # noqa: E402


def _scenario(sid="sc", verdict="tool_used", n=4, samples=4):
    return {
        "name": "unit",
        "version": "1",
        "scenarios": [
            {
                "id": sid,
                "name": sid,
                "prompt": "p",
                "samples": n,
                "verdict": verdict,
                "params": {"tool": "execute_command"},
            }
        ],
    }


def _stub_runner(per_sample_truncated):
    """返回 run_one_sample 的替身：按调用次序给出预设 truncated 标志。"""
    seq = list(per_sample_truncated)

    def _run(prompt, workdir, key, setup=None, max_iterations=10, knowledge_binding=None):
        trunc = seq.pop(0) if seq else False
        return {
            "trace": [{"name": "execute_command", "args": {"command": "ls"}}],
            "answer": "done",
            "model_used": "m",
            "rounds": 10 if trunc else 3,
            "truncated": trunc,
            "tokens_in": 100,
            "tokens_out": 10,
        }

    return _run


def test_truncated_samples_excluded_from_denominator(monkeypatch, tmp_path):
    """4 样本：2 通过、1 真失败、1 截断 → 通过率应为 2/3 而非 2/4。"""
    scen = _scenario()
    # 顺序：pass, fail, pass, trunc
    trunc_flags = [False, False, False, True]
    idx = {"i": 0}
    # E1' P1 修复配套（2026-10-25）：evaluate 非 dry 路径无条件逐样本传 knowledge_binding
    # kwarg。构造真实 empty binding（全落 tmp_path，不碰生产目录），替身记录收到的
    # kwarg 以锁定透传契约（只为断言改测试，不改产品代码）。
    binding = run_eval.prepare_knowledge_binding(tmp_path / "kb-scratch", "empty")
    assert binding["mode"] == "empty"
    received_kb: list = []

    def _run(prompt, workdir, key, setup=None, max_iterations=10, knowledge_binding=None):
        received_kb.append(knowledge_binding)
        t = trunc_flags[idx["i"]]
        idx["i"] += 1
        # 第 2 个样本判失败：trace 无工具调用
        trace = (
            [{"name": "execute_command", "args": {"command": "ls"}}]
            if idx["i"] != 2
            else []
        )
        return {
            "trace": trace,
            "answer": "done",
            "model_used": "m",
            "rounds": 10 if t else 3,
            "truncated": t,
            "tokens_in": 100,
            "tokens_out": 10,
        }

    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")
    out = run_eval.evaluate(
        scen, dry=False, samples_override=4, workdir=tmp_path, checkpoint_path=None, resume=False,
        knowledge_binding=binding,
    )
    r = out["results"][0]
    assert r["truncated"] == 1, f"截断数应为 1，实际 {r['truncated']}"
    assert r["failed"] == 1, f"真失败数应为 1，实际 {r['failed']}"
    # 主口径：分母 = 全部样本（截断计入）→ 3/4
    assert r["passed"] == 3, f"主口径通过数应为 3（含截断但判定True的），实际 {r['passed']}"
    assert abs(r["rate"] - 3 / 4) < 1e-9, f"主口径率应为 3/4，实际 {r['rate']}"
    # 参考口径：排除截断 → 2/(2+1)
    assert r["scored"] == 3, f"计分子集应为 3（4-1截断），实际 {r['scored']}"
    assert abs(r["rate_scored"] - 2 / 3) < 1e-9, f"参考率应为 2/3，实际 {r['rate_scored']}"
    assert abs(r["truncated_rate"] - 0.25) < 1e-9
    # 锁"evaluate 逐样本透传 binding"：非空 binding 应原样传给每个样本
    #（对象同一、mode 与构造一致；替身只记录 kwarg，不消费内容）
    assert len(received_kb) == 4, f"应逐样本收到 binding 4 次，实际 {len(received_kb)}"
    assert all(kb is binding for kb in received_kb), "每个样本应收到同一个 binding 对象"
    assert received_kb[0]["mode"] == "empty", (
        f"透传 binding 的 mode 应与构造一致（empty），实际 {received_kb[0]['mode']}"
    )


def test_truncated_but_verdict_true_not_counted_as_pass(monkeypatch, tmp_path):
    """截断样本即便判定为 True 也不计入通过（预算外的运气不算通过）。"""
    scen = _scenario()
    monkeypatch.setattr(run_eval, "run_one_sample", _stub_runner([True, False]))
    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")
    out = run_eval.evaluate(
        scen, dry=False, samples_override=2, workdir=tmp_path, checkpoint_path=None, resume=False
    )
    r = out["results"][0]
    assert r["truncated"] == 1
    # 样本1：截断 + verdict=True → 主口径计入（截断仍在分母内）
    # 样本2：未截断 + verdict=True → 计入
    assert r["passed"] == 2, "主口径：两个 verdict=True 都算通过（分母含截断）"
    assert r["scored"] == 1, "参考口径分母只含非截断样本"
    assert r["rate"] == 1.0, "主口径 2/2"
    assert r["rate_scored"] == 1.0, "参考口径 1/1"
    # 关键：截断样本**没有**被从主口径分母里删掉（否则会虚高、藏负结果）
    assert r["samples"] == 2


def test_all_truncated_scores_zero_not_crash(monkeypatch, tmp_path):
    """全部截断 → 计分样本 0 → 率 0，不应除零崩溃。"""
    scen = _scenario()
    monkeypatch.setattr(run_eval, "run_one_sample", _stub_runner([True, True]))
    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")
    out = run_eval.evaluate(
        scen, dry=False, samples_override=2, workdir=tmp_path, checkpoint_path=None, resume=False
    )
    r = out["results"][0]
    assert r["scored"] == 0, "全部截断 → 参考口径无计分样本"
    assert r["truncated"] == 2
    # 主口径：截断样本仍在分母内（2/2 = 1.0）；不因"全部截断"而崩溃或虚高
    assert r["rate"] == 1.0, "主口径 = 2/2（截断计入分母，判定为True即算通过）"
    assert r["rate_scored"] == 0.0


def test_run_verdict_accepts_truncated_kwarg_backward_compatible():
    """新增 truncated 关键字不破坏既有调用（不传时行为不变）。"""
    trace = [{"name": "execute_command", "args": {"command": "ls"}}]
    a = run_verdict("tool_used", trace, "done", {"tool": "execute_command"})
    b = run_verdict("tool_used", trace, "done", {"tool": "execute_command"}, truncated=True)
    assert a is True
    assert b is True, "truncated 只做标记，不改变谓词返回值语义"


def test_is_truncated_answer_detects_history_checkpoints():
    """历史 checkpoint（写入时无 truncated 字段）可从答复文本识别截断。"""
    assert is_truncated_answer("[已达轮数上限] 事实: 已达到最大循环轮数。")
    assert is_truncated_answer("（已达轮数硬边界）")
    assert is_truncated_answer("已达到最大循环轮数")
    assert not is_truncated_answer("## 结论\n当前运行健康。")
    assert not is_truncated_answer("")


def test_is_truncated_answer_keeps_v4_intent_and_covers_engine_banners():
    """v4 原意保留：题面要求解释"达到上限如何处理"时，正文出现该短语**不算**截断。

    v5 补：引擎自己发的 run 结束横幅（core/loop/engine.py）与子代理横幅
    也要被识别 —— 否则历史 checkpoint 离线重判会把截断当正常回答。
    """
    assert not is_truncated_answer("已达到最大循环轮数时应先归因、压缩收尾或交由扩额决定。")
    assert not is_truncated_answer("## 结论\n已达到最大循环轮数，按规则收口。")
    assert is_truncated_answer("（已达轮数硬边界，run 已结束；发送\"继续\"可开新 run 接续任务。）")
    assert is_truncated_answer("（子代理已达轮数上限，结果未完整收敛——请父级基于已有工具反馈整合）")


def test_scenario_level_max_iterations_is_passed_through(monkeypatch, tmp_path):
    """场景级 max_iterations 透传到 runner（2026-10-23 新增）。"""
    scen = _scenario()
    scen["scenarios"][0]["max_iterations"] = 24
    seen: list[int] = []

    def _run(prompt, workdir, key, setup=None, max_iterations=10, knowledge_binding=None):
        seen.append(max_iterations)
        return {
            "trace": [{"name": "execute_command", "args": {"command": "ls"}}],
            "answer": "done",
            "model_used": "m",
            "rounds": 3,
            "truncated": False,
            "tokens_in": 1,
            "tokens_out": 1,
        }

    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")
    run_eval.evaluate(
        scen, dry=False, samples_override=1, workdir=tmp_path, checkpoint_path=None, resume=False
    )
    assert seen == [24], f"场景轮数预算应透传为 24，实际 {seen}"


def test_default_max_iterations_follows_product_budget(monkeypatch, tmp_path):
    """缺省轮数预算 = 产品口径（预算对齐契约变更，2026-10-25 取代旧"硬编码 10"契约）.

    三条断言锁定新契约：
      1. LLM_MAX_ITERATIONS 未设置 → 跑批默认 = Settings.max_iterations 字段值
         （与产品配置同源取，不硬编码数值，避免再被环境/字段演进钉死）；
      2. env=10 → 默认 = 10（env 优先，与 Settings.from_env 同口径）；
      3. budget_profile=pinned10 → 基准强制 10，即使 env 设成 500（复现历史跑批）。
    """
    import dataclasses

    from llm_loop.config import Settings

    field_default = next(
        f.default for f in dataclasses.fields(Settings) if f.name == "max_iterations"
    )

    def _capture_runner():
        """记录 max_iterations 实参的假 runner（与同文件其它测试同套路）。"""
        seen: list[int] = []

        def _run(prompt, workdir, key, setup=None, max_iterations=10, knowledge_binding=None):
            seen.append(max_iterations)
            return {
                "trace": [{"name": "execute_command", "args": {"command": "ls"}}],
                "answer": "done",
                "model_used": "m",
                "rounds": 3,
                "truncated": False,
                "tokens_in": 1,
                "tokens_out": 1,
            }

        return seen, _run

    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")

    # 1) env 未设置 → Settings.max_iterations 字段默认（不硬编码 500）
    monkeypatch.delenv("LLM_MAX_ITERATIONS", raising=False)
    seen, _run = _capture_runner()
    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    run_eval.evaluate(
        _scenario(), dry=False, samples_override=1, workdir=tmp_path,
        checkpoint_path=None, resume=False,
    )
    assert seen == [field_default], (
        f"缺省预算应为 Settings.max_iterations 字段默认（{field_default}），实际 {seen}"
    )

    # 2) env=10 → 默认 10（env 优先）
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "10")
    seen, _run = _capture_runner()
    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    run_eval.evaluate(
        _scenario(), dry=False, samples_override=1, workdir=tmp_path,
        checkpoint_path=None, resume=False,
    )
    assert seen == [10], f"env LLM_MAX_ITERATIONS=10 时缺省预算应为 10，实际 {seen}"

    # 3) pinned10：忽略 env（500）强制 10（复现历史跑批行为的 CLI 语义）
    monkeypatch.setenv("LLM_MAX_ITERATIONS", "500")
    scen = _scenario()
    budget = run_eval._resolve_run_budget(
        scen,
        product_default=run_eval._product_default_max_iterations(),
        profile="pinned10",
        ignore_scenario_pins=False,
        force_max_iterations=None,
    )
    seen, _run = _capture_runner()
    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    run_eval.evaluate(
        scen,
        dry=False,
        samples_override=1,
        workdir=tmp_path,
        checkpoint_path=None,
        resume=False,
        budget=budget,
    )
    assert seen == [10], f"pinned10 基准应强制 10（无视 env=500），实际 {seen}"


def test_main_rate_keeps_truncated_in_denominator(monkeypatch, tmp_path):
    """主口径率 = 通过/全部样本：截断计入分母（不因排除截断而虚高）。"""
    scen = _scenario()
    # 4 样本：1 通过、1 截断(判定True)、1 截断(判定False)、1 真失败
    seq = [
        (True, False),  # pass
        (True, True),   # 截断 + 判定True
        (False, True),  # 截断 + 判定False
        (False, False), # 真失败
    ]
    idx = {"i": 0}

    def _run(prompt, workdir, key, setup=None, max_iterations=10, knowledge_binding=None):
        v, t = seq[idx["i"]]
        idx["i"] += 1
        trace = [{"name": "execute_command", "args": {"command": "ls"}}] if v else []
        return {
            "trace": trace,
            "answer": "done",
            "model_used": "m",
            "rounds": 10 if t else 3,
            "truncated": t,
            "tokens_in": 1,
            "tokens_out": 1,
        }

    monkeypatch.setattr(run_eval, "run_one_sample", _run)
    monkeypatch.setattr(run_eval, "_resolve_api_key", lambda: "test-key")
    out = run_eval.evaluate(
        scen, dry=False, samples_override=4, workdir=tmp_path, checkpoint_path=None, resume=False
    )
    r = out["results"][0]
    assert r["samples"] == 4
    assert r["truncated"] == 2
    assert r["passed"] == 2, "通过数含截断但判定True的样本（主口径）"
    assert r["rate"] == 0.5, f"主口径率应为 2/4=0.5，实际 {r['rate']}"
    assert r["scored"] == 2, "计分子集=非截断样本(1通过+1真失败)"
    assert r["rate_scored"] == 0.5, "参考率=1/(1+1)"
    assert r["truncated_rate"] == 0.5
