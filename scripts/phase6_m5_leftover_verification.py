"""Phase6 M5 遗留验证（#3 停止按钮真 DOM + #4 残余窗口确定性量化）.

口径（单次测量 + 方法文档，非统计结论；设计 §5.6/交付报告 §6）：

#3  webui 真 DOM 停止按钮：隔离端口 dev 实例（127.0.0.1:8899，不碰生产 8000）
     + 慢 FakeLLM（缺省无 chat_stream → 同步通道，8s 窗口）+ 真 webui dist。
     Playwright 真点击「■ 停止生成」→ POST /api/v1/chat/cancel → runner.cancel
     → 引擎窗口轮询 Stop 命中（Phase6 M1 T2 路径）→ 即时终态。
     度量 t(click→引擎终态) 与 t(click→UI 停止按钮消失)，断言终答取消语义。

#4a 引擎侧续答残余（FakeLLM，无 guard 页面）：窗口内插话打断后
     t(打断消费) → t(下一轮 provider 调用开始)——web 通道残余窗口的引擎侧下界。
#4b guard 侧残余（真实 DeepSeekWebModelClient + 桩页面 transport，6s 固定
     exchange，W3 同款构造）：
     - 无 cancel 触发（引擎未调钩子/页面无早退）：第二次 chat 在 guard 上等满
       残余（≈5s）——设计 §4.4「续答受残余窗口约束」的直接量化。
     - cancel 触发（M2 早退路径）：第一次调用早退释放 guard，第二次 chat 即刻
       进入 exchange（残余≈早退时延）。
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# 关键：src 置于 sys.path[0]——否则 venv/PYTHONPATH 可能解析到 .releases/ 下的
# 部署代码（实测曾误载 .releases/f6be73f92/src 并触发生产 canary 配置拒绝）。
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

REPORT = REPO / "reports" / "phase6" / "m5"
PORT = 8899
WINDOW_S = 8.0
GEN_S = 6.0  # #4b 桩页面单次 exchange 固定生成时长
INJECT_AT_S = 2.0

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class _P3Block:
    """#3 慢窗口响应项：置位就绪事件 → 阻塞 WINDOW_S → 返回完整终答。"""

    ready = threading.Event()

    def __call__(self, _calls):
        from llm_loop.llm.client import LLMResponse

        _P3Block.ready.set()
        time.sleep(WINDOW_S)
        return LLMResponse(content="P3-FULL-ANSWER", tool_calls=[], provider="fake")


def _setup_sandbox() -> Path:
    sandbox = Path(tempfile.mkdtemp(prefix="p6-m5-sandbox-"))
    (sandbox / "data").mkdir()
    (sandbox / "runtime-isolated").mkdir()
    os.environ["DATA_DIR"] = str(sandbox / "data")
    os.environ["LFL_DATA_DIR"] = str(sandbox / "data")
    os.environ["LFL_LEAK_GUARD_MODE"] = "observe"  # 测试基建同款（guard observe）
    # 部署泄漏隔离（conftest 批次1-4 同款）：宿主生产 runtime 携带 canary/
    # auth/compress/provider-admin 键，在隔离工作区必然 fail-closed/_deny。
    for var in (
        "WEB_AUTH_REQUIRE", "WEB_ORIGIN_ALLOWLIST", "WEB_API_KEY", "WEB_LOGIN_PASSWORD_HASH",
        "COMPRESS_TARGET_RATIO", "APPEND_COMPRESSION", "COMPACT_RATIO",
        "LLM_MODEL", "MODEL_PROVIDERS", "LFL_TASK_BUDGET_WEB_CANARY_CONFIG",
        "UI_V2_DIR", "WEB_MODELS",  # 审查 C6：防换挂载 dist/过滤模型列表
    ):
        os.environ.pop(var, None)
    os.environ["LFL_RUNTIME_ROOT"] = str(sandbox / "runtime-isolated")
    # 审查 C6：显式钉死本测量的核心机制开关，防宿主 env 带 0 静默回退内联窗口形态。
    os.environ["LFL_SYNC_CHAT_INTERJECT_CHECKPOINT"] = "1"
    # 模型对齐：/api/v1/models 的 current 兜底字面量 deepseek-flash（routes.py
    # getattr(engine.llm,"model",None) or "deepseek-flash"；FakeLLM 无 .model），
    # 不在 fake 池注册表（仅 default/fake-model）——前端按 current 默认选择发送，
    # run 在 pool_resolve_failed 即失败（action_trace 实证；审查 C3 措辞修正）。
    os.environ["LLM_MODEL"] = "default/fake-model"
    os.chdir(sandbox)  # R9-IMM-02 同款：相对路径写入锁进沙箱
    return sandbox


def build_dev_engine(responses):
    import tests.conftest as c

    fs = c.fake_settings.__wrapped__(Path(os.environ["DATA_DIR"]))
    _build = c.build_test_engine.__wrapped__(fs)
    engine, fake = _build(responses)
    from llm_loop.core.loop.runner import BackgroundRunner

    runner = BackgroundRunner(engine)
    engine.runner = runner
    return engine, fake, runner


def _http(method: str, path: str, body: dict | None = None):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _wait_port(timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"dev 实例端口 {PORT} 未就绪")


_SERVER = None  # 进程内单例：多 part 复用同端口时必须先停旧实例，否则新服务
# 绑定失败、HTTP 打到旧引擎（part4a 首轮 interject 409 的根因）。


def _start_server(engine):
    global _SERVER
    import uvicorn
    from llm_loop.web import build_app

    if _SERVER is not None:
        _SERVER.should_exit = True
        time.sleep(0.3)  # 等端口释放
    app = build_app(engine=engine)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    _wait_port()
    _SERVER = server
    return server


def _wait_run_terminal(runner, sid: str, timeout_s: float = 40.0) -> float | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        h = runner.get_handle(sid)
        # RunHandle.status 仅 running|done|error（审查 C7：去掉冗余 pending）
        if h is None or h.get("status") != "running":
            return time.monotonic()
        time.sleep(0.01)
    return None


def part3_stop_dom(engine, runner) -> dict:
    from playwright.sync_api import sync_playwright

    _start_server(engine)
    result: dict = {"window_s": WINDOW_S, "port": PORT, "ui": "/ui/v2/"}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # 前端模型持久化键预置 fake 池模型：/api/v1/models 的 current
        # （settings.llm_model 默认 deepseek-flash）不在 fake 池注册表，
        # 前端按 current 默认选择会 pool_resolve_failed（action_trace 实证）。
        page.add_init_script(
            "localStorage.setItem('lfl.selected.model', 'default/fake-model')"
        )
        sids: list[str] = []
        page.on(
            "request",
            lambda req: (
                (m := _UUID_RE.search(req.url)) and m.group(0) not in sids and sids.append(m.group(0))
            ),
        )
        page.goto(f"http://127.0.0.1:{PORT}/ui/v2/", wait_until="domcontentloaded")
        ta = page.locator("textarea.v2-composer-input")
        ta.wait_for(timeout=10000)
        ta.fill("请长篇回答这个问题")
        ta.press("Enter")
        # dist 与 src 的停止文案存在代差（dist=「停止」，src=「■ 停止生成」），
        # 验证对象=部署 dist 资产，按「停止」子串匹配（探针实证全页唯一）。
        stop_btn = page.get_by_role("button", name=re.compile("停止"))
        stop_btn.wait_for(timeout=15000)
        t_click = time.monotonic()
        stop_btn.click()
        # 审查 C7：sid 捕获失败须硬失败——空 sid 会让 get_handle(None) 恒 None
        # 而 _wait_run_terminal 近 0ms 假通过。
        assert sids, "未能从请求 URL 捕获 session_id"
        sid = sids[0]
        t_engine_terminal = _wait_run_terminal(runner, sid, timeout_s=30)
        try:
            stop_btn.wait_for(state="detached", timeout=10000)
            t_ui_terminal = time.monotonic()
        except Exception:
            t_ui_terminal = None
        # 终答落盘可能晚于 run 终态数毫秒：带重试后取末条 assistant。
        # 语义口径（Phase4 四态）：取消在途 → 终态 0 字节 0 工具——
        # _CANCELLED_ANSWER 仅随终态事件发 UI，持久化消息内容为空（实测）。
        hist_text = ""
        status = 0
        assistant_tail = None
        for _ in range(6):
            time.sleep(0.5)
            status, hist = _http("GET", f"/api/v1/sessions/{sid}/messages?limit=5")
            hist_text = json.dumps(hist, ensure_ascii=False)
            msgs = hist.get("messages", []) if isinstance(hist, dict) else []
            for m in reversed(msgs):
                if m.get("role") == "assistant":
                    assistant_tail = m
                    break
            if assistant_tail is not None and not assistant_tail.get("content"):
                break
        result.update(
            session_id=sid,
            stop_selector='button:has-text("停止")（按「停止」子串匹配，兼容「■ 停止生成」全形态——审查 C1 实证 dist 含完整文案，非代差）',
            t_click_to_engine_terminal_ms=(
                round((t_engine_terminal - t_click) * 1000, 1)
                if t_engine_terminal
                else None
            ),
            t_click_to_ui_terminal_ms=(
                round((t_ui_terminal - t_click) * 1000, 1) if t_ui_terminal else None
            ),
            four_state_cancelled_inflight=(
                {
                    "assistant_content_empty": bool(
                        assistant_tail is not None and not assistant_tail.get("content")
                    ),
                    "tool_calls_empty": bool(
                        assistant_tail is None
                        or not (assistant_tail.get("tool_calls") or [])
                    ),
                }
            ),
            history_status=status,
        )
        browser.close()
    return result


def part4a_engine_residual() -> dict:
    """窗口内插话打断 → 下一轮 provider 调用开始（引擎侧续答残余下界）."""
    next_call_starts: list[float] = []
    ready = threading.Event()

    def _blocking(_calls):
        from llm_loop.llm.client import LLMResponse

        ready.set()
        time.sleep(WINDOW_S)
        return LLMResponse(content="P4A-FULL", tool_calls=[], provider="fake")

    def _final(_calls):
        from llm_loop.llm.client import LLMResponse

        next_call_starts.append(time.time())  # epoch——与 hq received_at 同基
        # （首轮混用 monotonic 得到荒谬负值 -1.7e12ms 的教训）
        return LLMResponse(content="final-after-p4a", tool_calls=[], provider="fake")

    engine, fake, runner = build_dev_engine([_blocking, _final])
    _start_server(engine)
    sid = engine.session.create()
    # run 经 runner 启动（S 测试同款；/queue 仅入队不驱动 run——QueueServerFallback
    # 巡检才补发，202≠已启动，首轮实证窗口未开）。
    _h, q = runner.start(sid, "请长篇回答")
    assert ready.wait(timeout=10), "窗口未开始"
    time.sleep(INJECT_AT_S)
    gen = (runner.get_handle(sid) or {}).get("run_generation")
    s2, r2 = _http(
        "POST", "/api/v1/chat/queue", {"session_id": sid, "message": "P4A-插话"}
    )
    assert s2 == 202, (s2, r2)
    qid = r2["queue_id"]
    s3, r3 = _http(
        "POST",
        "/api/v1/chat/queue/interject",
        {"session_id": sid, "queue_id": qid, "run_generation": gen},
    )
    assert s3 == 202, (s3, r3)
    assert _wait_run_terminal(runner, sid), "run 未结束"
    status, hq = _http("GET", f"/api/v1/chat/queue?session_id={sid}")
    item = next(
        (it for it in (hq.get("items", []) if isinstance(hq, dict) else []) if it.get("queue_id") == qid),
        None,
    )
    assert item is not None, f"未找到队列项: {hq}"
    assert next_call_starts, "下一轮调用未开始"
    residual_s = next_call_starts[0] - item["received_at"]
    return {
        "window_s": WINDOW_S,
        "inject_at_s": INJECT_AT_S,
        "consumed_via": item.get("consumed_via"),
        "t_effect_ms": round((item["received_at"] - item["created_at"]) * 1000, 1),
        "engine_residual_ms": round(residual_s * 1000, 1),
        "note": (
            "FakeLLM 无 guard 页面：打断后 daemon worker 后台自然结束，下一轮立即开始；"
            "web 通道总残余 = 本引擎侧下界 + guard 等待（见 guard_side）"
        ),
    }


def part4b_guard_residual() -> dict:
    """真实 DeepSeekWebModelClient + 桩页面 transport（W3 同款三层委托）。"""
    from llm_loop.llm.deepseek_web import DeepSeekWebModelClient, _ThreadBoundTransport

    class _SlowPageTransport:
        """桩页面：固定 gen_s 生成；cancellable=True 时可 cancel 早退（M2 语义）。"""

        def __init__(self, gen_s: float, cancellable: bool) -> None:
            self._gen_s = gen_s
            self._cancellable = cancellable
            self._cancelled = threading.Event()
            self.exchange_starts: list[float] = []

        def cancel(self) -> None:
            self._cancelled.set()

        def exchange(self, request, *, timeout_s=None):  # noqa: ANN001
            from llm_loop.llm.deepseek_page import DeepSeekPageCancelledError
            from llm_loop.llm.deepseek_web import MODEL_PROTOCOL

            self.exchange_starts.append(time.monotonic())
            # 对齐真实 M2 transport 语义（设计 §10）：取消只作用在途轮次，
            # exchange 开始时清零取消事件（审查 C4：否则复用本桩断言
            # 「第二次调用成功返回」会踩坑；guard_wait 取 entry 时刻不受影响）。
            self._cancelled.clear()
            if self._cancellable:
                # M2 早退语义：cancel 事件先于生成完毕 → 抛取消；否则等满 gen_s
                # 自然完成（不额外再睡——首轮双重窗口是实测 9994ms 的根因）。
                if self._cancelled.wait(timeout=self._gen_s):
                    raise DeepSeekPageCancelledError("stub page cancelled")
            else:
                time.sleep(self._gen_s)
            # 响应键集须与 _validate_response 的 allowed 精确相等（协议校验实证）。
            return {
                "protocol": MODEL_PROTOCOL,
                "request_id": request["request_id"],
                "content": "stub-reply",
                "tool_calls": [],
                "finish_reason": "stop",
            }

    def make_client(cancellable: bool):
        pt = _SlowPageTransport(GEN_S, cancellable)
        client = DeepSeekWebModelClient(_ThreadBoundTransport(lambda: pt))
        return client, pt

    msgs = [{"role": "user", "content": "hi"}]
    out: dict = {"exchange_gen_s": GEN_S, "interrupt_at_s": INJECT_AT_S}

    # 场景1：无 cancel 触发 → 页面生成完毕，第二次 chat 等满 guard 残余
    c1, pt1 = make_client(cancellable=True)  # transport 支持早退但引擎未触发
    t_chat2_entry: list[float] = []
    t_chat2_done: list[float] = []

    def _chat2():
        t_chat2_entry.append(time.monotonic())
        try:
            c1.chat(msgs, [])
        except Exception:
            pass
        t_chat2_done.append(time.monotonic())

    th1 = threading.Thread(
        target=lambda: (_ := c1.chat(msgs, [])), daemon=True
    )
    th1.start()
    while not pt1.exchange_starts:
        time.sleep(0.01)
    time.sleep(INJECT_AT_S)  # 模拟引擎打断命中（但未调 cancel 钩子）
    th2 = threading.Thread(target=_chat2, daemon=True)
    th2.start()
    th2.join(timeout=GEN_S * 3)
    if len(pt1.exchange_starts) >= 2:
        guard_wait = pt1.exchange_starts[1] - t_chat2_entry[0]
        out["no_cancel"] = {
            "guard_wait_ms": round(guard_wait * 1000, 1),
            "expected_upper_bound_ms": round((GEN_S - INJECT_AT_S) * 1000, 1),
        }
    else:
        out["no_cancel"] = {"guard_wait_ms": None, "note": "第二次 exchange 未开始"}

    # 场景2：cancel 触发（M2 早退）→ guard 即刻释放
    c2, pt2 = make_client(cancellable=True)

    def _first():
        try:
            c2.chat(msgs, [])
        except Exception:
            pass

    th3 = threading.Thread(target=_first, daemon=True)
    th3.start()
    while not pt2.exchange_starts:
        time.sleep(0.01)
    time.sleep(INJECT_AT_S)
    t_cancel = time.monotonic()
    c2.cancel()  # 引擎命中后调用协作钩子（M2 契约）
    th3.join(timeout=5.0)
    t_released = time.monotonic()
    t2_entry: list[float] = []
    t2_done: list[float] = []

    def _second():
        t2_entry.append(time.monotonic())
        try:
            c2.chat(msgs, [])
        except Exception:
            pass
        t2_done.append(time.monotonic())

    th4 = threading.Thread(target=_second, daemon=True)
    th4.start()
    th4.join(timeout=10.0)
    if len(pt2.exchange_starts) >= 2:
        out["with_cancel"] = {
            "early_exit_release_ms": round((t_released - t_cancel) * 1000, 1),
            "guard_wait_ms": round((pt2.exchange_starts[1] - t2_entry[0]) * 1000, 1),
            "note": "第一次经 cancel 早退释放 guard；第二次即刻进入 exchange",
        }
    else:
        out["with_cancel"] = {"early_exit_release_ms": None, "note": "第二次 exchange 未开始"}
    return out


def main() -> int:
    sandbox = _setup_sandbox()
    print(f"[m5] sandbox={sandbox}")
    REPORT.mkdir(parents=True, exist_ok=True)

    print("[m5] #3: webui 真 DOM 停止按钮（dev 实例 :8899）...")
    engine, fake, runner = build_dev_engine([_P3Block()])
    p3 = part3_stop_dom(engine, runner)
    (REPORT / "STOP_DOM_SPOTCHECK.json").write_text(
        json.dumps(p3, ensure_ascii=False, indent=2)
    )
    print("[m5] #3:", json.dumps(p3, ensure_ascii=False))

    print("[m5] #4a: 引擎侧续答残余...")
    p4a = part4a_engine_residual()
    print("[m5] #4a:", json.dumps(p4a, ensure_ascii=False))

    print("[m5] #4b: guard 侧残余（真实 web client + 桩页面）...")
    p4b = part4b_guard_residual()
    print("[m5] #4b:", json.dumps(p4b, ensure_ascii=False))

    (REPORT / "RESIDUAL_WINDOW.json").write_text(
        json.dumps(
            {"engine_side": p4a, "guard_side": p4b}, ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
