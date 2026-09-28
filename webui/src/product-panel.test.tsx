import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ContinuityBanner } from "./components/conversation/ContinuityBanner";
import { RightPanel } from "./components/layout/RightPanel";
import { sessionStore, themeStore } from "./core/stores";

const MODEL_CATALOG = {
  models: ["glm/glm-5.3"],
  current: "glm/glm-5.3",
  catalog: [
    {
      id: "glm/glm-5.3",
      provider: "glm",
      model: "glm-5.3",
      context: 1_000_000,
      cost_tier: "high",
      reasoning_capable: true,
      reasoning_control: "always_on_effort",
      reasoning_control_supported: true,
      reasoning_can_disable: false,
      reasoning_efforts: ["low", "high", "max"],
    },
  ],
};

beforeEach(() => {
  sessionStore.setCurrentSession("s1");
  themeStore.setPreference("system");
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("product right panel", () => {
  it("设置页使用真实模型能力/登录事实，主题按钮能实际切换", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/models")) return new Response(JSON.stringify(MODEL_CATALOG), { status: 200 });
      if (url.includes("/auth/status")) return new Response(JSON.stringify({ browser_login: true, authenticated: true }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<RightPanel open={true} />);
    await waitFor(() => expect(screen.getByText("glm/glm-5.3")).toBeInTheDocument());
    expect(screen.getByText(/reasoning\/always_on_effort/)).toBeInTheDocument();
    expect(screen.getByText("已验证")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    expect(themeStore.getState().preference).toBe("dark");
  });

  it("会话绑定页展示当前 conversation、segment 历史和保守 GC 策略", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/sessions/s1/provider-binding")) {
        return new Response(JSON.stringify({
          provider: "chatgpt-web",
          bound: true,
          session_id: "s1",
          session_status: "active",
          binding: {
            conversation_id: "conv-current",
            conversation_url: "https://chatgpt.com/g/g-p/c/conv-current",
            segment_seq: 3,
            segment_request_count: 2,
            segment_request_chars: 54321,
            total_request_count: 7,
            updated_at: "2026-09-28T17:00:00+08:00",
          },
          history: [
            {
              segment_seq: 2,
              conversation_id: "conv-old",
              request_count: 3,
              request_chars: 110000,
              closed_at: "2026-09-28T16:30:00+08:00",
              reason: "cumulative_request_chars",
            },
          ],
          lifecycle: {
            session_exists: true,
            session_status: "active",
            gc_eligible: false,
            gc_reason: "session_exists",
          },
          gc_policy: {
            automatic_gc: false,
            default_min_age_days: 30,
            requires_confirm: true,
            requires_expected_updated_at: true,
          },
        }), { status: 200 });
      }
      if (url.endsWith("/api/v1/chatgpt-web/bindings/health")) {
        return new Response(JSON.stringify({
          schema: "lfl.chatgpt_binding_health.v1",
          status: "warning",
          observed_at: "2026-09-28T17:05:00+08:00",
          metrics: {
            bindings_total: 4,
            exchanges_24h: 12,
            rollovers_24h: 3,
            restore_failures_24h: 1,
            restore_success_rate_24h: 0.875,
            segment_pressure_max_ratio: 0.92,
          },
          alerts: [
            {
              code: "restore_failures_recent",
              severity: "warning",
              message: "ChatGPT conversation restore failures occurred in the last 24h.",
              count: 1,
            },
          ],
          telemetry: {
            coverage: "event_log_only",
            event_count: 18,
            last_event_at: "2026-09-28T17:04:00+08:00",
          },
          notification_outlet: {
            delivery: "macos_system_notification",
            push_severities: ["warning", "critical"],
            repeat_seconds: 3600,
            retry_seconds: 300,
            state: {
              health_status: "warning",
              active: {
                "fp-1": {
                  code: "restore_failures_recent",
                  severity: "warning",
                  last_success_at: "2026-09-28T17:04:30+08:00",
                },
              },
            },
            last_event: {
              event: "notification_delivered",
              ts: "2026-09-28T17:04:30+08:00",
              code: "restore_failures_recent",
              severity: "warning",
              delivery: "macos_system_notification",
            },
          },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<RightPanel open={true} />);
    fireEvent.click(screen.getByRole("button", { name: "会话绑定" }));

    await waitFor(() => expect(screen.getByTestId("session-binding-panel")).toBeInTheDocument());
    expect(screen.getByText("conv-current")).toBeInTheDocument();
    expect(screen.getByText("conv-old")).toBeInTheDocument();
    expect(screen.getByText("cumulative_request_chars")).toBeInTheDocument();
    expect(screen.getByText("session_exists")).toBeInTheDocument();
    expect(screen.getByText("关闭")).toBeInTheDocument();
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("warning");
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("87.5%");
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("92.0%");
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("macOS 系统通知");
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("warning / critical");
    expect(screen.getByTestId("binding-health-card")).toHaveTextContent("notification_delivered");
    expect(screen.getByText("restore_failures_recent")).toBeInTheDocument();
    expect(screen.getByText(/event log，不回填历史调用/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /清理|删除|GC/ })).toBeNull();
    expect(screen.getByText(/Existing\/archived LFL Session 永不自动清理/)).toBeInTheDocument();
  });

  it("后台任务只给本地可控 running job 停止按钮，orphan 只展示事实", async () => {
    let killCalls = 0;
    let killed = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/models")) return new Response(JSON.stringify(MODEL_CATALOG), { status: 200 });
      if (url.includes("/auth/status")) return new Response(JSON.stringify({}), { status: 200 });
      if (url.includes("/jobs/job-local/kill")) {
        killCalls += 1;
        killed = true;
        return new Response(JSON.stringify({ status: "ok", detail: "已请求停止" }), { status: 200 });
      }
      if (url.endsWith("/api/v1/sessions/s1/jobs")) {
        return new Response(JSON.stringify({ jobs: [
          {
            job_id: "job-local",
            executor: "execute_command",
            state: killed ? "killed" : "running",
            local_handle: true,
            command: "sleep 30",
            output: ["started"],
          },
          {
            job_id: "job-orphan",
            executor: "execute_command",
            state: "orphaned",
            local_handle: false,
            durable: true,
            auto_reclaim: false,
          },
        ] }), { status: 200 });
      }
      if (init?.method === "POST") return new Response(JSON.stringify({}), { status: 500 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<RightPanel open={true} />);
    fireEvent.click(screen.getByRole("button", { name: "后台任务" }));
    await waitFor(() => expect(screen.getAllByTestId("job-card")).toHaveLength(2));
    expect(screen.getByText("job-orphan")).toBeInTheDocument();
    expect(screen.getByText(/不自动接管\/重跑/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "停止任务" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "停止任务" }));
    await waitFor(() => expect(killCalls).toBe(1));
    await waitFor(() => expect(screen.queryByRole("button", { name: "停止任务" })).toBeNull());
  });

  it("后台任务瞬时读取失败保留最后已知任务并显示读取错误", async () => {
    let fail = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/sessions/s1/jobs")) {
        return fail
          ? new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503 })
          : new Response(JSON.stringify({ jobs: [{
              job_id: "job-known",
              executor: "execute_command",
              state: "running",
              local_handle: true,
            }] }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<RightPanel open={true} />);
    fireEvent.click(screen.getByRole("button", { name: "后台任务" }));
    await waitFor(() => expect(screen.getByText("job-known")).toBeInTheDocument());

    fail = true;
    fireEvent.click(screen.getByRole("button", { name: /刷新/ }));
    await waitFor(() => expect(screen.getByText(/后台任务读取失败/)).toBeInTheDocument());
    expect(screen.getByText("job-known")).toBeInTheDocument();
  });

  it("jobs 轮询单飞：慢请求期间不按 2s 周期叠加", async () => {
    vi.useFakeTimers();
    let jobCalls = 0;
    let resolveFirst: ((response: Response) => void) | null = null;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/models")) return Promise.resolve(new Response(JSON.stringify(MODEL_CATALOG), { status: 200 }));
      if (url.includes("/auth/status")) return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
      if (url.endsWith("/api/v1/sessions/s1/jobs")) {
        jobCalls += 1;
        if (jobCalls === 1) {
          return new Promise<Response>((resolve) => { resolveFirst = resolve; });
        }
        return Promise.resolve(new Response(JSON.stringify({ jobs: [] }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    }));

    render(<RightPanel open={true} />);
    fireEvent.click(screen.getByRole("button", { name: "后台任务" }));
    await Promise.resolve();
    expect(jobCalls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(6_000); });
    expect(jobCalls).toBe(1);

    await act(async () => {
      resolveFirst?.(new Response(JSON.stringify({ jobs: [] }), { status: 200 }));
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(jobCalls).toBe(2);
  });
});

describe("restart continuity banner", () => {
  it("只展示机械恢复摘要，不展示 checkpoint 正文/推理内容", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      available: true,
      open: true,
      source: "open_stream_checkpoint",
      provider: "glm",
      model: "glm-5.3",
      text_chars: 1800,
      reasoning_chars: 900,
      checkpoint_seq: 42,
      mechanical_execution: {
        tool_executions: [{ execution_id: "e1", state: "started" }],
        external_executions: [{ job_id: "j1", state: "orphaned" }],
      },
    }), { status: 200 })));

    render(<ContinuityBanner sessionId="s1" />);
    await waitFor(() => expect(screen.getByTestId("continuity-banner")).toBeInTheDocument());
    expect(screen.getByText(/输出检查点 1800 字符/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(screen.getByText(/推理检查点：900 字符/)).toBeInTheDocument();
    expect(screen.getByText(/不会因该状态自动重跑/)).toBeInTheDocument();
    expect(screen.queryByText("SECRET MODEL TEXT")).toBeNull();
  });

  it("没有 open interruption 时完全不占 UI", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ available: true, open: false }), { status: 200 })));
    const { container } = render(<ContinuityBanner sessionId="s1" />);
    await waitFor(() => expect(screen.queryByTestId("continuity-banner")).toBeNull());
    expect(container).toBeEmptyDOMElement();
  });

  it("continuity 轮询单飞：上一次未完成时不叠加新请求", async () => {
    vi.useFakeTimers();
    let calls = 0;
    let resolveFirst: ((response: Response) => void) | null = null;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (!url.includes("/continuity")) {
        return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
      }
      calls += 1;
      if (calls === 1) {
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      }
      return Promise.resolve(new Response(JSON.stringify({ available: true, open: false }), { status: 200 }));
    }));

    render(<ContinuityBanner sessionId="s1" />);
    await Promise.resolve();
    expect(calls).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(calls).toBe(1);

    await act(async () => {
      resolveFirst?.(new Response(JSON.stringify({ available: true, open: false }), { status: 200 }));
      await Promise.resolve();
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(calls).toBe(2);
  });
});
