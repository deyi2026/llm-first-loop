import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
});
