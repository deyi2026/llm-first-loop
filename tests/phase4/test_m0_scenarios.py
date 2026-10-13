"""Phase4 M0 基线扩展：S13–S16 生效时延场景（现状对照，零核心代码变更）.

场景定义见 docs/phase4-effect-latency-design.md §6 M0：
- S13 在途打断基线：2.0s 长工具（execute_command `sleep 2.0`）在途，工具启动后
  ~0.3s 注入插话。现状：插话滞留 mailbox 至工具自然完成（~2.0s）后轮转轮首消费
  → t_effect ≈ 1.7s 量级（差值本体=工具剩余时长）。
- S14 不可中断保守：revocable=False 工具在途（测试内注册 phase4_locked_sleep，
  副作用登记 revocable=False），同 0.3s 注入。现状与 S13 同（无打断机制）；
  M2 后此场景必须保持自然边界（保守等待，不进打断通道）。
- S15 竞速如实：`sleep 1.5` 工具 + 工具启动后 ~1.45s 注入（剩余 ~50ms 边界）。
  分支（natural_first / interrupt_first）按事件序判定（工具完成墙钟 vs 插话消费
  received_at），两分支各≥3 次构造；M0 现状无打断判定通道 → 全部 natural_first，
  如实记录。
- S16 空窗插话：无在途工具，第二次 LLM 调用（final 生成窗口，callable 内 sleep
  1.5s）期间注入。现状：终答结算边界消费（continued_before_final）→ t_effect ≈
  生成窗口剩余时长；M1 目标场景（序列间隙直接收割，P50≤50ms）。

口径：t_effect_ms = received_at − created_at（hq 条目时间戳，与
HumanTurnQueue.aggregate_interject_metrics 同源）。每场景 n≥5 样本，
P50/P95 用最近邻序法（与 hq._pct 同法）。
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.web import build_app
from llm_loop.web.human_turn_queue import HumanTurnQueue

REPO = Path(__file__).resolve().parents[2]
# 基线输出目录参数化（默认 reports/phase4/m0；重跑指定 PHASE4_REPORT_DIR 防覆盖
# 原始记录——沿 Phase3 m0 覆盖事故教训）
REPORT_DIR = REPO / os.environ.get("PHASE4_REPORT_DIR", "reports/phase4/m0").lstrip("/")
REPORT_DIR = Path(os.path.abspath(REPORT_DIR))
REPORT_DIR.mkdir(parents=True, exist_ok=True)

INTERJECT_TEXT = "改用方案B，不要等了"
RAN_UNDER = os.environ.get("PHASE4_RAN_UNDER", "M0-baseline")


def _pct(vals: list[float], p: float) -> float | None:
    """最近邻序法百分位（与 HumanTurnQueue._pct 同法）."""
    if not vals:
        return None
    s = sorted(vals)
    k = max(1, math.ceil(p * len(s)))
    return s[k - 1]


class Rec:
    """场景记录器：多样本流水 + 墙钟时刻 + 时延 + 行为事实，finally 落盘."""

    def __init__(self, sid: str, title: str) -> None:
        self.data: dict = {
            "scenario": sid,
            "title": title,
            "ran_under": RAN_UNDER,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "samples": [],
            "obs": {},
        }

    def sample(self, entry: dict) -> None:
        self.data["samples"].append(entry)

    def obs(self, key: str, value) -> None:
        self.data["obs"][key] = value

    def write(self, status: str = "ok", error: str | None = None) -> None:
        self.data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.data["status"] = status
        if error:
            self.data["error"] = str(error)[:2000]
        effs = [s["t_effect_ms"] for s in self.data["samples"] if s.get("t_effect_ms") is not None]
        self.data["n"] = len(self.data["samples"])
        self.data["t_effect_p50_ms"] = _pct(effs, 0.50)
        self.data["t_effect_p95_ms"] = _pct(effs, 0.95)
        path = REPORT_DIR / f"{self.data['scenario']}.json"
        # 基线保全护栏：已存在的基线快照默认不覆写（PHASE4_OVERWRITE_REPORTS=1
        # 强制重测）。基线数据是不可再生事实，回归重跑测的是新行为，混入基线
        # 目录会破坏对照真值。
        import os as _os
        if path.exists() and _os.environ.get("PHASE4_OVERWRITE_REPORTS") != "1":
            return
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _wait_tool_started(engine, tool_name: str, signal_attr: str, timeout: float = 3.0) -> bool:
    tool = engine.registry.get(tool_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if getattr(tool, signal_attr, None):
            return True
        time.sleep(0.005)
    return False


def _wait_tool_done(engine, tool_name: str, signal_attr: str, timeout: float = 10.0) -> float | None:
    """轮询工具活跃信号消失，返回完成墙钟（perf_counter 域）；超时 None."""
    tool = engine.registry.get(tool_name)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not getattr(tool, signal_attr, None):
            return time.perf_counter()
        time.sleep(0.005)
    return None


def _wait_run_done(q, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ev = q.get_nowait()
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
            continue
        if ev.get("type") in ("done", "error"):
            return ev
    return {"type": "timeout"}


def _hq_of(client: TestClient, engine) -> HumanTurnQueue:
    store = getattr(client.app.state, "human_turn_queues", None) or {}
    data_dir = str(Path(getattr(engine.settings, "data_dir", "./data")).expanduser().resolve())
    if data_dir in store:
        return store[data_dir]
    assert store, "no human_turn_queues in app.state"
    return next(iter(store.values()))


def _hq_item(hq: HumanTurnQueue, sid: str, qid: str) -> dict | None:
    for it in hq.snapshot_items():
        if it.get("queue_id") == qid and it.get("session_id") == sid:
            return it
    return None


def _interject(client: TestClient, sid: str, queue_id: str, gen: str):
    return client.post(
        "/api/v1/chat/queue/interject",
        json={"session_id": sid, "queue_id": queue_id, "run_generation": gen},
    )


def _enqueue_and_interject(client, sid, gen, rec_step):
    """POST /queue + POST /queue/interject，返回 (queue_id, created_at, interject_done_perf)."""
    r1 = client.post("/api/v1/chat/queue", json={"session_id": sid, "message": INTERJECT_TEXT})
    assert r1.status_code == 202, f"入队非 202: {r1.status_code}"
    queue_id = r1.json()["queue_id"]
    r2 = _interject(client, sid, queue_id, gen)
    assert r2.status_code == 202, f"插话受理非 202: {r2.status_code} {r2.text[:200]}"
    return queue_id


class _LockedSleepTool:
    """S14 不可中断语义测试工具：revocable=False 副作用登记 + 睡眠.

    不含任何终止通道（无 terminate/proc 管理）——语义上即「打断不可回收」，
    M2 后不进闭集、保持保守等待。_active 供 _wait_tool_started/_wait_tool_done 轮询。
    """

    name = "phase4_locked_sleep"
    description = "Phase4 S14 测试工具：revocable=False 副作用登记 + 睡眠（不可中断语义基线）"
    parameters = {
        "type": "object",
        "properties": {"seconds": {"type": "number", "default": 2.0}},
        "required": [],
    }

    def __init__(self) -> None:
        self._active = False

    def execute(self, seconds: float = 2.0, **_) -> ToolResult:
        from llm_loop.core.loop.side_effects import SideEffectRegistry

        sid = current_session_id.get() or ""
        self._active = True
        try:
            SideEffectRegistry.instance().register(
                sid,
                self.name,
                f"phase4-locked seconds={seconds}",
                "test_locked",
                revocable=False,
                detail="Phase4 S14: 不可中断语义基线（revocable=False）",
            )
            time.sleep(float(seconds))
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content=f"[locked sleep done] seconds={seconds}（自然完成，revocable=False 语义）",
                tool_call_id="",
                tool_name=self.name,
            )
        finally:
            self._active = False


def _one_tool_sample(build_test_engine, *, tool_name: str, cmd: str | None, sleep_s: float,
                     inject_delay_s: float, title: str, tag: str,
                     poll_attr: str = "_active_procs") -> dict:
    """单样本：turn0=长工具 → 注入 → 等 run 终态 → 取 hq 时间戳算 t_effect.

    build_test_engine responses：[带工具调用, final]。返回样本记录 dict。
    """
    tool_args = {"command": cmd} if cmd is not None else {"seconds": sleep_s}
    responses = [
        {
            "content": f"{tag} 先跑长工具",
            "tool_calls": [
                ToolCall(id=f"{tag}-c1", name=tool_name, arguments=tool_args)
            ],
        },
        {"content": "final-after-tool"},
    ]
    engine, fake = build_test_engine(responses)
    if tool_name == "phase4_locked_sleep":
        engine.registry.register(_LockedSleepTool())
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    entry: dict = {"tag": tag, "tool": tool_name, "tool_args": tool_args,
                   "inject_delay_s": inject_delay_s}
    try:
        _h, q = runner.start(sid, "请执行长命令")
        assert _wait_tool_started(engine, tool_name, poll_attr), "脚手架失效：工具未启动"
        entry["tool_started_perf"] = round(time.perf_counter(), 3)
        time.sleep(inject_delay_s)
        entry["inject_perf"] = round(time.perf_counter(), 3)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        queue_id = _enqueue_and_interject(client, sid, gen, None)

        if tag.startswith("S15"):
            done_perf = _wait_tool_done(engine, tool_name, poll_attr)
            entry["tool_done_perf"] = round(done_perf, 3) if done_perf else None

        final = _wait_run_done(q, timeout=40)
        entry["final_event"] = final.get("type")
        hq = _hq_of(client, engine)
        item = _hq_item(hq, sid, queue_id) or {}
        entry["item_status"] = item.get("status")
        c, r = item.get("created_at"), item.get("received_at")
        entry["created_at"], entry["received_at"] = c, r
        if c and r:
            entry["t_effect_ms"] = round((r - c) * 1000, 1)
            entry["t_ack_ms"] = round((item["interject_requested_at"] - c) * 1000, 1)
        # 行为事实：插话文本进入会话历史 + 模型可见
        sess = engine.session.load(sid)
        entry["model_saw_interject"] = any(
            INTERJECT_TEXT in (m.content or "") for m in sess.messages
        )
        entry["llm_call_count"] = len(fake.calls)
        return entry
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# S13 在途打断基线（n=5）
# ────────────────────────────────────────────────────────────────────
def test_s13_interject_during_long_tool(build_test_engine):
    rec = Rec("S13", "在途打断基线：2.0s 长工具 + 0.3s 注入")
    try:
        for i in range(5):
            s = _one_tool_sample(
                build_test_engine,
                tool_name="execute_command", cmd=f"sleep 2.0", sleep_s=2.0,
                inject_delay_s=0.3, title="S13", tag=f"S13-{i+1}",
            )
            rec.sample(s)
        rec.obs("expectation", "现状：t_effect ≈ 2.0 − 0.3 ≈ 1.7s 量级（工具自然完成后轮转消费）")
        rec.obs("all_final_done", all(s.get("final_event") == "done" for s in rec.data["samples"]))
        rec.obs("all_received", all(s.get("item_status") == "interject_received" for s in rec.data["samples"]))
    except Exception as exc:  # noqa: BLE001
        rec.write("error", exc)
        raise
    rec.write()


# ────────────────────────────────────────────────────────────────────
# S14 不可中断保守（n=5，revocable=False 测试工具）
# ────────────────────────────────────────────────────────────────────
def test_s14_interject_non_interruptible(build_test_engine):
    rec = Rec("S14", "不可中断保守：revocable=False 工具 + 0.3s 注入")
    try:
        for i in range(5):
            s = _one_tool_sample(
                build_test_engine,
                tool_name="phase4_locked_sleep", cmd=None, sleep_s=2.0,
                inject_delay_s=0.3, title="S14", tag=f"S14-{i+1}",
                poll_attr="_active",
            )
            rec.sample(s)
        rec.obs("expectation", "现状：与 S13 同（无打断机制）；M2 后必须保持自然边界（保守等待）")
        rec.obs("all_final_done", all(s.get("final_event") == "done" for s in rec.data["samples"]))
        rec.obs("all_received", all(s.get("item_status") == "interject_received" for s in rec.data["samples"]))
    except Exception as exc:  # noqa: BLE001
        rec.write("error", exc)
        raise
    rec.write()


# ────────────────────────────────────────────────────────────────────
# S15 竞速如实（n=6：sleep 1.5 + ~1.45s 注入，剩余 ~50ms 边界）
# ────────────────────────────────────────────────────────────────────
def test_s15_race_natural_vs_interrupt(build_test_engine):
    rec = Rec("S15", "竞速如实：sleep 1.5 + 1.45s 注入（剩余 ~50ms 边界）")
    try:
        for i in range(6):
            s = _one_tool_sample(
                build_test_engine,
                tool_name="execute_command", cmd="sleep 1.5", sleep_s=1.5,
                inject_delay_s=1.45, title="S15", tag=f"S15-{i+1}",
            )
            # 分支判定（M0 近似口径 + 观察噪声边界）：
            # received_perf ≈ inject_perf + t_effect（created_at 在注入打点后数 ms 内落盘）
            # 观察机制不对称：tool_done 来自本测试 5ms 轮询线程（滞后真实退出可达
            # ~20ms），received 来自引擎内 hq 时间戳——两者差 <40ms 属观察噪声带，
            # M0 无打断判定通道（构造上不可能 interrupt_first）。
            # M2 后改用事件序真值（终止登记/WAL 事件），弃近似与噪声带。
            if s.get("tool_done_perf") is not None and s.get("t_effect_ms") is not None:
                s["tool_done_after_inject_ms"] = round(
                    (s["tool_done_perf"] - s["inject_perf"]) * 1000, 1
                )
                s["received_minus_tooldone_ms"] = round(
                    s["t_effect_ms"] - s["tool_done_after_inject_ms"], 1
                )
                if s["received_minus_tooldone_ms"] > 40.0:
                    s["branch"] = "interrupt_first"
                elif s["received_minus_tooldone_ms"] > -40.0:
                    s["branch"] = "natural_first(noise_band)"
                else:
                    s["branch"] = "natural_first"
            else:
                s["branch"] = "undetermined"
            rec.sample(s)
        branches = [s.get("branch") for s in rec.data["samples"]]
        rec.obs("branch_counts", {b: branches.count(b) for b in set(branches)})
        rec.obs("expectation", "M0 现状无打断判定通道 → 应全部 natural_first，如实记录")
    except Exception as exc:  # noqa: BLE001
        rec.write("error", exc)
        raise
    rec.write()


# ────────────────────────────────────────────────────────────────────
# S16 空窗插话（n=5：第二次 LLM 调用生成窗口内注入）
# ────────────────────────────────────────────────────────────────────
def test_s16_interject_llm_generation_window(build_test_engine):
    from llm_loop.llm.client import LLMResponse

    def _slow_final(calls):
        time.sleep(1.5)  # 构造 final 生成窗口
        return LLMResponse(content="final-during-window", tool_calls=[], provider="fake")

    rec = Rec("S16", "空窗插话：第二次 LLM 调用（final 生成窗口 1.5s）期间注入")
    try:
        for i in range(5):
            engine, fake = build_test_engine(
                [
                    {
                        "content": "S16 先跑短工具",
                        "tool_calls": [
                            ToolCall(id=f"s16-{i}-c1", name="execute_command",
                                     arguments={"command": "sleep 0.2"})
                        ],
                    },
                    _slow_final,
                    {"content": "final-after-cbf"},
                ]
            )
            runner = BackgroundRunner(engine)
            engine.runner = runner
            client = TestClient(build_app(engine=engine))
            sid = engine.session.create()
            entry: dict = {"tag": f"S16-{i+1}", "llm_window_s": 1.5}
            try:
                _h, q = runner.start(sid, "请先跑短命令再总结")
                # 等第二次 LLM 调用开始（生成窗口开启）
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and len(fake.calls) < 2:
                    time.sleep(0.005)
                assert len(fake.calls) >= 2, "脚手架失效：第二次 LLM 调用未开始"
                entry["window_open_perf"] = round(time.perf_counter(), 3)
                time.sleep(0.05)  # 窗口开启后 50ms 注入
                entry["inject_perf"] = round(time.perf_counter(), 3)
                gen = (runner.get_handle(sid) or {}).get("run_generation")
                queue_id = _enqueue_and_interject(client, sid, gen, None)

                final = _wait_run_done(q, timeout=30)
                entry["final_event"] = final.get("type")
                hq = _hq_of(client, engine)
                item = _hq_item(hq, sid, queue_id) or {}
                entry["item_status"] = item.get("status")
                c, r = item.get("created_at"), item.get("received_at")
                if c and r:
                    entry["t_effect_ms"] = round((r - c) * 1000, 1)
                    entry["t_ack_ms"] = round((item["interject_requested_at"] - c) * 1000, 1)
                entry["cbf_recorded"] = bool(item.get("cbf_at"))
                sess = engine.session.load(sid)
                entry["model_saw_interject"] = any(
                    INTERJECT_TEXT in (m.content or "") for m in sess.messages
                )
                rec.sample(entry)
            finally:
                runner.cancel(sid)
        rec.obs("expectation", "现状：终答结算边界消费（CBF）→ t_effect ≈ 生成窗口剩余 ≈1.4s 量级")
        rec.obs("all_final_done", all(s.get("final_event") == "done" for s in rec.data["samples"]))
        rec.obs("all_received", all(s.get("item_status") == "interject_received" for s in rec.data["samples"]))
    except Exception as exc:  # noqa: BLE001
        rec.write("error", exc)
        raise
    rec.write()
