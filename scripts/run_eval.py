"""T4(2026-08-14) 评测运行器：评测集 → 真实 LLM N 样本 → 判定 → Wilson CI → 报告落盘.

用法:
    # 真实 LLM（需 DEEPSEEK_API_KEY/LLM_API_KEY；样本数为场景定义值）
    .venv/bin/python scripts/run_eval.py

    # 指定样本数与输出目录
    .venv/bin/python scripts/run_eval.py --samples 3 --output docs/metrics/eval_20260814

    # dry 模式：内置 fixture 轨迹验证判定/统计/报告管道（零 LLM 零网络）
    .venv/bin/python scripts/run_eval.py --dry

输出:
    <output>/report.json  结构化对账（每场景 k/n + 率 + Wilson CI + 样本详情）
    <output>/report.md    markdown 渲染（CI 区间/基线引用/如实标注）

纪律（playbook 4.x）: 样本不足如实标注；不宣称统计显著（CI 重叠即不显著）；
负结果与正结果同等呈现；报告含评测集版本与场景口径引用。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 2026-10-23 修复：只插入项目根会让 `import llm_loop` 落到 **PYTHONPATH**。
# 本机 PYTHONPATH 指向 `.releases/<commit>/src`（发布快照），于是评测脚本加载的是
# **release 快照源码**而非工作树 —— 本地新增的判定谓词/修复全部静默失效
# （实测：新场景恒 0/1，因为快照里没有新谓词）。
# 处置：把 `src` 显式插到 sys.path 最前，与 eval/rules/selfcheck.py 及 pytest 入口一致；
# 项目根本身仍在路径中（兼容 `data/` 等以根为基准的相对路径读取）。
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT))

from llm_loop.eval.verdicts import run_verdict, wilson_ci  # noqa: E402


def load_scenarios(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("scenarios"), list) or not data["scenarios"]:
        raise ValueError(f"评测集为空或格式错误: {path}")
    return data


_SCENARIOS_DEFAULT = Path(__file__).resolve().parent.parent / "tests" / "eval_sets" / "scenarios_v1.json"


_DEFAULT_MODEL_REF = "deepseek-v4-flash"


def resolve_model_ref() -> str:
    """本次评测**实际使用**的模型标识（provider/model），全脚本唯一真源。

    2026-10-23 修正（v5.1，独立审查 P1-2）：此前"引擎用什么模型"与
    "场景 ${MODEL} 注入什么模型"是两处独立的 ``os.environ.get`` 读取
    （一处带默认值、一处不带）→ 可能在无人察觉的情况下**静默错配**
    （判据比对的身份不是本轮真在跑的模型）。
    → 统一到这一个函数，引擎、provider 解析、场景注入共用同一结果。
    """
    import os

    return (os.environ.get("LLM_MODEL") or _DEFAULT_MODEL_REF).strip()


def substitute_model_params(scenarios: dict) -> None:
    """把场景 params 里的 ``${MODEL}`` 占位替换成**本次实际使用的模型**（就地修改）。

    2026-10-23 修正（v5）：``identity_verified`` 场景原把 ``expected`` 写死成
    ``deepseek-v4-flash``，而本轮被测模型是 ``minimax/MiniMax-M3.1-Flash``
    → 模型如实核验身份并正确作答，却因"身份与回执不一致"被判不通过（**假阴性**）。
    → 改为占位符 + 运行时按实际模型注入，场景集不再与具体模型绑死。
    """
    import os

    model_ref = resolve_model_ref()
    for sc in scenarios.get("scenarios", []):
        params = sc.get("params")
        if isinstance(params, dict) and params.get("expected") == "${MODEL}":
            params["expected"] = model_ref


def _resolve_api_key() -> str:
    """按 provider 声明的 api_key_env 解析真实 LLM 凭据（2026-10-23）.

    顺序：registry 中 provider 的 api_key_env → DEEPSEEK_API_KEY → LLM_API_KEY。
    解析 provider 时用 LLM_MODEL 的 provider 前缀；无法解析时退化为后两者。
    """
    import os
    import shutil
    import tempfile

    env_names: list[str] = []
    model_ref = resolve_model_ref()
    if model_ref and "/" in model_ref:
        provider_id = model_ref.split("/", 1)[0]
        try:
            from llm_loop.config import Settings
            from llm_loop.llm.providers import load_registry

            tmp = Path(tempfile.mkdtemp(prefix="eval-keyprobe-"))
            tmp_data = tmp / "data"
            tmp_data.mkdir(parents=True, exist_ok=True)
            src_providers = Path(__file__).resolve().parent.parent / "data" / "providers.json"
            if src_providers.exists():
                shutil.copy2(src_providers, tmp_data / "providers.json")
            reg = load_registry(
                Settings(
                    llm_api_key="probe",
                    llm_base_url="https://api.deepseek.com/v1",
                    llm_model=model_ref,
                    data_dir=str(tmp_data),
                )
            )
            spec = reg.providers.get(provider_id)
            if spec is not None and spec.api_key_env:
                env_names.append(spec.api_key_env)
        except Exception:  # noqa: BLE001 — 探测失败不改变后续行为
            pass
    env_names += ["DEEPSEEK_API_KEY", "LLM_API_KEY"]
    for name in env_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _settings(tmp_path, key: str, max_iterations: int = 10):
    """真实 LLM Settings（对齐 test_real_llm_smoke._real_llm_settings 口径）.

    ``max_iterations``（2026-10-23 新增，可按场景覆盖）：此前硬编码 10，
    场景集无法按任务复杂度配置轮数 → 多步链式场景（rule08_chain_complete 等）
    被 10 轮上限截断（实测 23 样本中 10 个截断，截断率 43.5%）。
    截断不是能力失败，是**预算不足**；不同量级的任务需要不同预算。
    """
    import shutil

    from llm_loop.config import Settings

    # M64 防污染隔离: 会话/审计写临时目录，但 providers.json 复制自真实 data/——
    # 否则多 provider 配置（如 deepseek/deepseek-v4-flash 全限定名）在 L0 合成下
    # resolve 失败"未知 provider"（2026-08-17 实测 401/未知 provider 根因）。
    tmp_data = tmp_path / "data"
    src_providers = Path(__file__).resolve().parent.parent / "data" / "providers.json"
    if src_providers.exists():
        tmp_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_providers, tmp_data / "providers.json")

    return Settings(
        llm_api_key=key,
        llm_base_url=__import__("os").environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        # 2026-08-17: strip 防御——shell 环境可能残留带尾随空格的 LLM_MODEL（脏值
        # 被 load_env_file 环境优先跳过覆盖），导致 resolve "模型不存在"（实测根因）。
        llm_model=resolve_model_ref(),
        data_dir=str(tmp_data),
        max_iterations=max_iterations,
        tool_timeout_s=30.0,
        thinking_mode=__import__("os").environ.get("LLM_THINKING_MODE", "enabled") != "disabled",
        reasoning_effort=__import__("os").environ.get("LLM_REASONING_EFFORT", "high"),
    )


def run_one_sample(
    prompt: str,
    workdir: Path,
    key: str,
    setup: dict | None = None,
    max_iterations: int = 10,
) -> dict:
    """单样本真实执行：engine.run → (trace, answer)。

    会话/数据目录全部隔离到临时目录（M64 防污染真实 data/ 的独立实现）。
    setup（场景可选）: 运行前向 engine.status 注入失败信号（对齐 M25-M28 必调整基线配置，
    仅测试基建直调 status 公共方法，产品零改动）。
    """
    import tempfile

    from llm_loop.factory import build_engine

    tmp = Path(tempfile.mkdtemp(prefix="eval-run-", dir=str(workdir)))
    engine = build_engine(_settings(tmp, key, max_iterations=max_iterations))  # type: ignore[arg-type]
    if setup:
        _apply_setup(engine, setup)
    sid = engine.session.create()
    # R8.24-D 修订②：LFL_LEAK_GUARD_MODE 默认 fail-closed —— 无 ingress 凭据的
    # role=user 写入会被 user_ingress_guard 拒绝（engine.run 直接返回
    # "[写入被拒] … leak.channel_denied"，rounds=0，模型根本未被调用）。
    # 评测框架是**测试后门**而非人类入口，故显式签发 test_harness 凭据
    # （issue_test_ingress 为测试专用入口，spec 5.3.3-4a；生产代码禁止使用）。
    # 不改动 guard 的 fail-closed 语义，只补齐本入口的合法凭据。
    ingress = None
    try:
        from llm_loop.core.trace_leak.ingress_token import issue_test_ingress

        ingress = issue_test_ingress()
    except Exception:  # noqa: BLE001 — 凭据不可得时保持原行为，不静默改语义
        ingress = None
    result = engine.run(sid, prompt, ingress=ingress)
    trace = [
        {"name": tc.get("name", ""), "arguments": tc.get("arguments", {})}
        for tc in result.tool_calls
    ]
    return {
        "trace": trace,
        "answer": result.final_answer,
        "model_used": result.model_used,
        "rounds": result.rounds,
        "truncated": result.truncated,
        # 2026-10-23(P2 A/B): 会话 id 与隔离 data 目录回传 —— 供跑批器读事件日志
        # 统计压缩事件/归档 ref（压缩后存续率需要事件侧事实，不能只看 trace）。
        "sid": sid,
        "data_dir": str(tmp / "data"),
        # A2(2026-08-14): token 用量（prompt 开销指标；0=provider 未提供）
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
    }


def _apply_setup(engine, setup: dict) -> None:
    """场景 setup：向 engine.status 注入失败信号（对齐 M28 基线：2 FAILURE + 1 异常）.

    仅测试基建直调 status 公共方法（record_tool_history/record_exception），产品零改动。
    注入失败 fail-open（status 未装配/异常时跳过，样本照常运行）。
    EVO-20260816-4fb09dd0: setup 含 inject_guidance 时同步注入行动引导
    （"发现失败率偏高/异常 → 应调用 adjust_strategy 调整"），对齐程序给事实、AI 决策。
    """
    try:
        from llm_loop.core.message import ToolResultStatus
        from llm_loop.introspection.status import ToolHistoryItem

        status = getattr(engine, "status", None)
        if status is None:
            return
        n_fail = int(setup.get("inject_failures", 0) or 0)
        for i in range(n_fail):
            status.record_tool_history(
                ToolHistoryItem(
                    name="read_file",
                    arguments={"path": f"/no/such/eval_{i}"},
                    status=ToolResultStatus.FAILURE,
                    summary=f"[文件不存在] /no/such/eval_{i} 不存在（评测预置失败信号）",
                )
            )
        if setup.get("inject_exception"):
            status.record_exception(
                "action.tool_loop", FileNotFoundError("/no/such/eval 预置异常信号")
            )
        # B: 行动引导注入（对齐 HARNESS-04 预警模式——程序给事实，AI 决策）
        if setup.get("inject_guidance"):
            try:
                from llm_loop.core.message import Message, MessageSource

                sess = getattr(engine, "session", None)
                if sess is not None:
                    msg = Message(
                        role="system",
                        content=(
                            "[行动引导] 检测到工具失败率偏高（2 条 FAILURE）与异常记录。"
                            "若确认异常，应调用 adjust_strategy 调整相关运行参数（如 max_iterations/"
                            "timeout_s）并说明依据——检查后行动，而非仅汇报。"
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={"injected_system": True},
                    )
                    with contextlib.suppress(Exception):  # noqa: BLE001 — 注入失败 fail-open
                        sess.messages.append(msg)
            except Exception:  # noqa: BLE001 — 引导注入失败 fail-open
                pass
    except Exception:  # noqa: BLE001 — 注入失败 fail-open
        pass


def run_dry_sample(
    prompt: str,
    workdir: Path,
    key: str,
    setup: dict | None = None,
    max_iterations: int = 10,
) -> dict:
    """dry 模式：固定 fixture 轨迹验证管道（零 LLM；trace 含自查+调整，answer 提及工具名）.

    ``max_iterations`` 与 run_one_sample 同签名（dry 不实际跑 LLM，仅保持调用一致）。
    """
    return {
        "trace": [
            {"name": "architecture_status", "arguments": {}},
            {"name": "adjust_strategy", "arguments": {"max_iterations": 8}},
            {"name": "read_file", "arguments": {"path": "data/eval_probe.txt"}},
        ],
        "answer": "我通过 architecture_status 自查发现失败率偏高，已用 adjust_strategy 将 max_iterations 从 5 调整为 8。",
        "model_used": "dry-fixture",
        "rounds": 3,
        "truncated": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _dry_injection_selfcheck() -> None:
    """P2-5(2026-08-15): dry 模式注入可见性自检（管道失效如实失败，防 dry 假绿）.

    背景: run_one_sample 依赖 setup 向 engine.status 注入 FAILURE 历史/异常（供
    adjust_step 等必调整场景），而 run_dry_sample 完全不经过注入——若注入链路或
    architecture_status 快照生产路径失效，依赖注入的场景在 dry 下无法被发现。

    自检流程（与 run_one_sample 完全相同的注入调用 + 真实快照生产路径）:
    1. 构造真实 ArchitectureStatusProvider（architecture_status 所用的状态类）
    2. 执行 inject_failures=2 + inject_exception=True 的注入调用（复用 _apply_setup）
    3. 走 architecture_status 快照生产路径（run_status → status_provider.snapshot）
    4. 断言注入的 FAILURE 计数与异常在快照中可见；不可见抛 RuntimeError
       （dry 结果不可信时必须如实失败，不静默通过）。
    """
    from types import SimpleNamespace

    from llm_loop.core.message import ToolResultStatus
    from llm_loop.introspection.status import ArchitectureStatusProvider
    from llm_loop.introspection.tools_status import run_status

    status = ArchitectureStatusProvider(enabled=True)
    _apply_setup(
        SimpleNamespace(status=status),
        {"inject_failures": 2, "inject_exception": True},
    )

    result = run_status(
        ctx=None,
        status_provider=status,
        args={
            "dimensions": ["tool_history", "exception_log"],
            # Dry selfcheck deliberately validates process-global injected fixtures rather
            # than a human task session; make that authority explicit instead of widening
            # model-facing current_session semantics.
            "scope": "runtime",
        },
    )
    if result.status != ToolResultStatus.SUCCESS:
        raise RuntimeError(
            f"dry 注入自检失败: architecture_status 快照生产失败（status={result.status.value}）"
        )
    try:
        snap = json.loads(result.content)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"dry 注入自检失败: architecture_status 快照解析失败: {exc}") from exc

    tool_history = snap.get("tool_history", [])
    failures = [t for t in tool_history if t.get("status") == ToolResultStatus.FAILURE.value]
    exception_log = snap.get("exception_log", [])
    if len(failures) < 2 or not exception_log:
        raise RuntimeError(
            "dry 注入自检失败: 预置失败信号在 architecture_status 快照中不可见"
            f"（tool_history FAILURE={len(failures)}/2, exception_log={len(exception_log)}/1）"
            "——注入链路或快照生产路径失效，dry 结果不可信（如实失败）。"
        )


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写文本（先写临时文件再 replace）：中断不产生半截报告."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_checkpoint(path: Path | None) -> dict[tuple[str, int], dict]:
    """读回已完成的样本记录（键 = (scenario_id, sample_index) → 样本详情）.

    2026-10-23：长跑批（84 样本真实 LLM）此前**只在 84 样本全跑完后**才写
    report.json，中途被 kill 即全部产出丢失（实测 evals/results/
    eval_v2_m31flash_20261023/ 为空 = 零产出）。本函数配合逐样本 checkpoint
    实现断点续跑。
    末行可能因中断被截断 → JSON 解析失败如实跳过该行（不静默改写已完成语义）。
    """
    done: dict[tuple[str, int], dict] = {}
    if path is None or not path.exists():
        return done
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        sid = rec.get("scenario_id")
        idx = rec.get("sample")
        detail = rec.get("detail")
        if sid is None or idx is None or not isinstance(detail, dict):
            continue
        try:
            done[(str(sid), int(idx))] = detail
        except (TypeError, ValueError):
            continue
    return done


def _append_checkpoint(path: Path, scenario_id: str, sample_index: int, detail: dict) -> None:
    """追加一条样本记录并 flush（逐样本落盘 → 中断只丢当前样本）."""
    rec = {"scenario_id": scenario_id, "sample": sample_index, "detail": detail}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()


def evaluate(
    scenarios: dict,
    *,
    dry: bool,
    samples_override: int | None,
    workdir: Path,
    checkpoint_path: Path | None = None,
    resume: bool = False,
) -> dict:
    key = ""
    if not dry:
        # 2026-10-23: key 来源按 **provider 实际使用的 api_key_env** 解析，
        # 不再只认 DEEPSEEK_API_KEY/LLM_API_KEY —— 否则换 provider（如 minimax）
        # 时 registry 取不到凭据，client_params 抛 "缺少 api_key"。
        # 解析顺序：provider 声明的 api_key_env → DEEPSEEK_API_KEY → LLM_API_KEY。
        key = _resolve_api_key()
        if not key:
            raise RuntimeError(
                "无真实 LLM key（provider 声明的 api_key_env / DEEPSEEK_API_KEY / LLM_API_KEY）；"
                "使用 --dry 验证管道"
            )
    else:
        # P2-5(2026-08-15): dry 路径开头做注入可见性自检——adjust_step 等依赖预置失败
        # 信号的场景必须在 dry 下同样可被发现（注入不可见 → 如实失败，防 dry 假绿）
        _dry_injection_selfcheck()

    runner = run_dry_sample if dry else run_one_sample
    results: list[dict] = []
    # 断点续跑：已完成的 (scenario_id, sample_index) 直接复用，不再调 LLM。
    # 复用样本的 verdict 是**上次真实运行**的判定结果，不重算（重算需再跑 LLM）。
    done = _load_checkpoint(checkpoint_path) if resume else {}
    if done:
        print(f"[resume] 复用已完成样本 {len(done)} 条", flush=True)
    substitute_model_params(scenarios)
    for sc in scenarios["scenarios"]:
        n = samples_override if samples_override is not None else int(sc.get("samples", 6))
        setup = sc.get("setup")
        # 场景级轮数预算（2026-10-23 新增）：缺省 10（与历史行为一致），
        # 场景可写 "max_iterations" 覆盖 → 多步链式场景不再被 10 轮硬上限截断。
        sc_max_iter = int(sc.get("max_iterations", 10))
        per_scenario: list[dict] = []
        for i in range(n):
            ck_key = (str(sc["id"]), i + 1)
            if ck_key in done:
                per_scenario.append(done[ck_key])
                continue
            sample = runner(sc["prompt"], workdir, key, setup, sc_max_iter)
            verdict = run_verdict(sc["verdict"], sample["trace"], sample["answer"], sc.get("params"))
            detail = {
                "sample": i + 1,
                "verdict": bool(verdict),
                "trace": sample["trace"],
                "answer_head": sample["answer"][:200],
                # 2026-10-23：存全量答复（此前只留 200 字摘要 → 判据口径变更后**无法离线重判**，
                # 每次改判据都得重跑 108 条真实 LLM 样本）。
                "answer_full": sample["answer"],
                "model_used": sample["model_used"],
                "rounds": sample["rounds"],
                "truncated": sample["truncated"],
                "tokens_in": sample.get("tokens_in", 0),
                "tokens_out": sample.get("tokens_out", 0),
            }
            per_scenario.append(detail)
            # 逐样本落盘：中断只丢当前样本，不丢已跑完的部分
            if checkpoint_path is not None:
                _append_checkpoint(checkpoint_path, str(sc["id"]), i + 1, detail)
            print(
                f"[sample] {sc['id']} #{i + 1}/{n} verdict={bool(verdict)} "
                f"rounds={sample['rounds']} model={sample['model_used']}",
                flush=True,
            )
        # ── 统计口径（2026-10-23 修正）────────────────────────────────
        # 轮数耗尽（truncated）的样本**不是**被测能力的失败，是执行预算不足。
        # 但**不能因此把它们从分母里删掉** —— 那会把通过率抬高（负结果被藏起来，
        # 违反"负结果同等呈现"）。实测 v2 跑批 22 样本：9 个截断；
        #   删掉截断 → 12/13 = 92.3%（虚高）；保留全样本 → 17/22 = 77.3%（真实）
        # 口径（两个都报，不藏负结果）：
        #   主口径 rate = 通过 / 全部样本          ← 保守，作为对外结论
        #   参考 rate_scored = 通过 / (通过 + 真失败) ← 排除截断后的能力上界
        #   truncated_rate = 截断 / 全部样本        ← 预算不足的直接度量
        n_trunc = sum(1 for s in per_scenario if s.get("truncated"))
        n_pass_all = sum(1 for s in per_scenario if s["verdict"])
        n_pass_scored = sum(1 for s in per_scenario if s["verdict"] and not s.get("truncated"))
        n_fail = sum(1 for s in per_scenario if not s["verdict"] and not s.get("truncated"))
        n_scored = n_pass_scored + n_fail
        k = n_pass_all
        lo, hi = wilson_ci(k, n) if n else (0.0, 0.0)
        lo_s, hi_s = wilson_ci(n_pass_scored, n_scored) if n_scored else (0.0, 0.0)
        # A2: 场景级 token 开销统计（provider 未提供用量时如实 0）
        _toks_in = [s["tokens_in"] for s in per_scenario]
        _toks_out = [s["tokens_out"] for s in per_scenario]
        _toks_total = [a + b for a, b in zip(_toks_in, _toks_out, strict=False)]
        tokens_stats = {
            "total_in": sum(_toks_in),
            "total_out": sum(_toks_out),
            "avg_per_sample": round(sum(_toks_total) / n, 1) if n else 0,
        }
        results.append(
            {
                "id": sc["id"],
                "name": sc["name"],
                "verdict": sc["verdict"],
                "samples": n,
                "passed": k,
                "truncated": n_trunc,
                "failed": n_fail,
                "scored": n_scored,
                "tokens": tokens_stats,
                "rate": (k / n) if n else 0.0,
                "rate_scored": (n_pass_scored / n_scored) if n_scored else 0.0,
                "truncated_rate": (n_trunc / n) if n else 0.0,
                "ci": [round(lo, 3), round(hi, 3)],
                "ci_scored": [round(lo_s, 3), round(hi_s, 3)],
                "samples_detail": per_scenario,
            }
        )
    return {"results": results, "dry": dry}


def render_markdown(scenarios: dict, eval_out: dict) -> str:
    lines = [
        "# 评测报告（T4 评测集运行）",
        "",
        f"> 评测集: {scenarios['name']}（version {scenarios['version']}）",
        f"> 运行模式: {'dry 管道验证（零 LLM）' if eval_out['dry'] else '真实 LLM'}",
        f"> 生成: {datetime.now(UTC).isoformat()}",
        f"> 基线引用: {scenarios.get('baseline_ref', '')}（各验收报告为数据唯一出处）",
        "",
        "| 场景 | 判定 | 通过/全部 | 截断 | 真失败 | 主口径率 | 参考率(排除截断) | Wilson 95% CI(主) | 平均 token/样本 |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for r in eval_out["results"]:
        lines.append(
            f"| {r['name']} | {r['verdict']} | {r['passed']}/{r['samples']} "
            f"| {r.get('truncated', 0)} | {r.get('failed', 0)} "
            f"| {r['rate']:.2f} | {r.get('rate_scored', 0.0):.2f} "
            f"| [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] "
            f"| {r.get('tokens', {}).get('avg_per_sample', 0):.0f} |"
        )
    lines.append("")
    lines.append(
        "> 口径（2026-10-23 修正）：**主口径率 = 通过 / 全部样本**（保守，对外结论用）；"
        "「截断」= 达到最大轮数被中断的样本，单列且**仍计入全样本分母** —— "
        "轮数耗尽是执行预算不足而非能力失败，但把它从分母删掉会让通过率虚高、藏掉负结果。"
        "「参考率」= 通过 / (通过 + 真失败)，是排除截断后的能力上界；两者同报，不藏负结果。"
    )
    lines.append(
        "> 纪律：样本不足如实标注；CI 区间重叠即不宣称统计显著；负结果同等呈现。"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T4 评测集运行器（真实 LLM / dry 管道验证）")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=_SCENARIOS_DEFAULT,
    )
    parser.add_argument("--samples", type=int, default=None, help="覆盖场景样本数（默认用场景定义值）")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出目录（默认 docs/metrics/eval_<ts>/，自动创建）",
    )
    parser.add_argument("--dry", action="store_true", help="dry 模式：fixture 轨迹验证管道（零 LLM）")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="逐样本 checkpoint 路径（默认 <output>/checkpoint.jsonl）：每样本跑完即落盘，"
        "中断后可 --resume 续跑（2026-10-23 长跑批中断零产出修复）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续跑：复用 checkpoint 中已完成的样本，只跑未完成部分",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="只跑这些场景（逗号分隔的 scenario id）——用于针对性补跑",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=(
            "覆盖场景的 max_iterations（针对性补跑用）。"
            "改了预算的跑批是**另一种配置**，报告里必须单列，不得并进主跑批的分母"
        ),
    )
    args = parser.parse_args(argv)

    # M63 对齐: 与 CLI/Web/飞书一致从项目 .env 加载（环境变量优先），
    # 真实模式无需手动 export key；--dry 不受影响（不读 key）
    from llm_loop.config import load_env_file

    load_env_file()

    try:
        scenarios = load_scenarios(args.scenarios)
        if args.only:
            keep = {s.strip() for s in str(args.only).split(",") if s.strip()}
            known = {s.get("id") for s in scenarios["scenarios"]}
            missing = keep - known
            if missing:
                raise SystemExit(f"--only 指定了不存在的场景: {sorted(missing)}")
            scenarios = {
                **scenarios,
                "scenarios": [s for s in scenarios["scenarios"] if s.get("id") in keep],
            }
        if args.max_iterations:
            for s in scenarios["scenarios"]:
                s["max_iterations"] = args.max_iterations
        workdir = Path(__file__).resolve().parent.parent / "data" / "e2e"
        workdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_dir = args.output or (Path(__file__).resolve().parent.parent / "docs" / "metrics" / f"eval_{ts}")
        out_dir.mkdir(parents=True, exist_ok=True)
        ck_path = args.checkpoint or (out_dir / "checkpoint.jsonl")
        ck_path.parent.mkdir(parents=True, exist_ok=True)
        eval_out = evaluate(
            scenarios,
            dry=args.dry,
            samples_override=args.samples,
            workdir=workdir,
            checkpoint_path=ck_path,
            resume=args.resume,
        )
        _atomic_write_text(
            out_dir / "report.json",
            json.dumps(
                {"scenario_version": scenarios["version"], "generated": ts, **eval_out},
                ensure_ascii=False,
                indent=2,
            ),
        )
        _atomic_write_text(out_dir / "report.md", render_markdown(scenarios, eval_out))
        print(f"评测完成（{'dry' if args.dry else 'real'}）: {out_dir}")
        for r in eval_out["results"]:
            print(f"  {r['name']}: {r['passed']}/{r['samples']} = {r['rate']:.2f} CI {r['ci']}")
        return 0
    except RuntimeError as exc:
        print(f"评测中止: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — 异常如实报错退出
        print(f"评测异常: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
