// 可观测性 M1c V3：插话时延观测面板契约（只读/fail-open/诚实口径）
// 设计依据 docs/ANALYSIS-20261014-observability-m0-findings.md §5-B2/B4、§6-V3。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InterjectMetricsPanel } from "./components/sidebar/InterjectMetricsPanel";

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

const GLOBAL = {
  ok: true,
  scope: "global",
  session_id: null,
  n: 6,
  sessions_in_window: 2,
  window_terminal_cap: 500,
  p50_t_ack_ms: 3.0,
  p95_t_ack_ms: 4.0,
  p50_t_persist_ms: 47.0,
  p95_t_persist_ms: 60.0,
  p50_t_effect_ms: 50.0,
  p95_t_effect_ms: 60.0,
  p50_t_applied_ms: null,
  p95_t_applied_ms: null,
  buckets: {
    interruptible: { n: 0, p50_t_effect_ms: null, p95_t_effect_ms: null, insufficient_sample: true },
    natural_boundary: { n: 2, p50_t_effect_ms: 3000.0, p95_t_effect_ms: 3000.0, insufficient_sample: true },
    llm_stream: { n: 0, p50_t_effect_ms: null, p95_t_effect_ms: null, insufficient_sample: true },
    llm_stream_interrupt: { n: 6, p50_t_effect_ms: 93.0, p95_t_effect_ms: 120.0, insufficient_sample: false },
    sync_window_poll: { n: 4, p50_t_effect_ms: 50.0, p95_t_effect_ms: 60.0, insufficient_sample: false },
    idle: { n: 0, p50_t_effect_ms: null, p95_t_effect_ms: null, insufficient_sample: true },
  },
};

const SESSION = {
  ok: true,
  session_id: "s1",
  n: 3,
  items: [{}, {}, {}],
  p50_t_ack_ms: 3.0,
  p95_t_ack_ms: 3.0,
  p50_t_persist_ms: 47.0,
  p95_t_persist_ms: 47.0,
  p50_t_effect_ms: 50.0,
  p95_t_effect_ms: 50.0,
  p50_t_applied_ms: null,
  p95_t_applied_ms: null,
  buckets: GLOBAL.buckets,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("interject metrics panel (M1c)", () => {
  it("全局六桶渲染：null=无样本（≠0ms）、样本不足徽标、窗口标注、会话视图复用", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL, init?: RequestInit) => {
        calls.push({ url: String(url), init });
        const u = String(url);
        if (u.includes("/metrics/global")) return ok(GLOBAL);
        if (u.includes("/metrics?")) return ok(SESSION);
        throw new Error(`unexpected url: ${u}`);
      }),
    );
    render(<InterjectMetricsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId("interject-metrics")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("im-global-n")).toHaveTextContent("6"));
    // 六桶全列（B7 口径；全局+会话两表均渲染，用 getAllByText）
    for (const label of ["可打断点", "自然边界", "流式·保守等待", "流式·打断收割", "同步窗口轮询", "空闲收割"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    }
    // null → 无样本（显式文本，不渲染 0ms）
    const row = screen.getByTestId("im-global-bucket-interruptible");
    expect(row).toHaveTextContent("无样本");
    expect(row).not.toHaveTextContent("0 ms");
    // 样本不足徽标：n<5 有，n>=5 无
    expect(screen.getByTestId("im-global-insufficient-natural_boundary")).toBeInTheDocument();
    expect(screen.queryByTestId("im-global-insufficient-sync_window_poll")).toBeNull();
    // t_applied null → 无样本
    expect(screen.getByTestId("im-global-t_applied_ms-p50")).toHaveTextContent("无样本");
    // 滚动窗口边界标注（B5）
    expect(screen.getByTestId("im-window-note")).toHaveTextContent("最近 500 条终态");
    // 会话视图：复用既有端点（带 session_id），展示 n
    expect(screen.getByTestId("im-session-n")).toHaveTextContent("3");
    const sessionCalls = calls.filter((c) => c.url.includes("/metrics?session_id=s1"));
    expect(sessionCalls.length).toBeGreaterThanOrEqual(1);
    // 零写操作（V3）：全部调用为 GET，且只打两个只读端点
    for (const c of calls) {
      expect(c.init?.method ?? "GET").toBe("GET");
      expect(c.url).toMatch(/^\/api\/v1\/chat\/queue\/metrics(\/global)?(\?|$)/);
    }
  });

  it("fail-open：全局失败仅该块不可用，会话视图不受影响", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        const u = String(url);
        if (u.includes("/metrics/global")) return new Response("boom", { status: 502 });
        if (u.includes("/metrics?")) return ok(SESSION);
        throw new Error(`unexpected url: ${u}`);
      }),
    );
    render(<InterjectMetricsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId("im-global-error")).toBeInTheDocument());
    expect(screen.getByTestId("im-global-error")).toHaveTextContent("不可用");
    // 会话块照常渲染
    await waitFor(() => expect(screen.getByTestId("im-session-n")).toHaveTextContent("3"));
  });

  it("无当前会话：会话块显式提示，不发会话端点请求", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        calls.push(String(url));
        return ok(GLOBAL);
      }),
    );
    render(<InterjectMetricsPanel sessionId="" />);
    await waitFor(() => expect(screen.getByTestId("im-session-empty")).toBeInTheDocument());
    expect(calls.every((u) => !u.includes("session_id"))).toBe(true);
  });

  it("手动刷新重新拉取", async () => {
    let n = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        const u = String(url);
        n += 1;
        if (u.includes("/metrics/global")) return ok({ ...GLOBAL, n: n });
        return ok(SESSION);
      }),
    );
    render(<InterjectMetricsPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId("im-global-n")).toHaveTextContent("1"));
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(screen.getByTestId("im-global-n")).toHaveTextContent("3"));
  });
});
