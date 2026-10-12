// 会话头部任务列表（JobsCatalog）产品契约：
// - 空态不渲染；有任务时显示 live/总计数 trigger（live 带运行点）
// - 状态语义对齐 DSH：cancel_requested → 正在停止；killed → 已取消；orphaned → 已失联
// - 排序：live 在前按开始时间升序；settled 按结束时间降序
// - 时长由 started_at/finished_at 机械事实计算；缺时间事实显示 "—"（不伪造）

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { JobsCatalog } from "./components/conversation/JobsCatalog";
import { sessionStore } from "./core/stores";
import type { JobFact } from "./core/api";

function jobs(): JobFact[] {
  const now = Date.now();
  return [
    {
      job_id: "job-running",
      executor: "execute_command",
      state: "running",
      command: "npm run build",
      started_at: now / 1000 - 30,
    },
    {
      job_id: "job-stopping",
      executor: "execute_command",
      state: "running",
      cancel_requested: true,
      command: "pytest -q tests/web",
      started_at: now / 1000 - 120,
    },
    {
      job_id: "job-done",
      executor: "dsh_task",
      state: "completed",
      command: "ls -la",
      started_at: now / 1000 - 600,
      finished_at: now / 1000 - 540,
    },
    {
      job_id: "job-killed",
      executor: "execute_command",
      state: "killed",
      command: "sleep 1000",
      started_at: now / 1000 - 900,
      finished_at: now / 1000 - 300,
    },
    {
      job_id: "job-orphaned",
      executor: "execute_command",
      state: "orphaned",
      command: "restart-survivor",
    },
  ];
}

function installFetch(
  action: (url: string) => Response | undefined
) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const response = action(url);
    if (response) return response;
    if (url.includes("/api/v1/capabilities")) {
      return new Response(JSON.stringify({ capabilities: {} }), { status: 200 });
    }
    if (url.includes("/api/v1/sessions/s1/jobs")) {
      return new Response(JSON.stringify({ jobs: jobs(), count: 5 }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStore.setCurrentSession("s1");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("jobs catalog (DSH JobListAction parity)", () => {
  it("transient read failure preserves last known jobs instead of fabricating an empty catalog", async () => {
    let fail = false;
    installFetch((url) => {
      if (url.includes("/api/v1/sessions/s1/jobs")) {
        return fail
          ? new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503 })
          : new Response(JSON.stringify({ jobs: jobs(), count: 5 }), { status: 200 });
      }
      return undefined;
    });
    render(<JobsCatalog />);
    const trigger = await screen.findByTestId("jobs-catalog-trigger");
    expect(trigger).toHaveTextContent("2 个后台任务运行中");

    fail = true;
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(screen.getByTestId("jobs-catalog-trigger")).toBeInTheDocument());
    expect(screen.getByTestId("jobs-catalog-trigger")).toHaveTextContent("2 个后台任务运行中");
  });

  it("空态不渲染；有任务时显示 live 计数 trigger", async () => {
    let empty = false;
    installFetch((url) => {
      if (url.includes("/api/v1/sessions/s1/jobs")) {
        return new Response(
          JSON.stringify({ jobs: empty ? [] : jobs(), count: empty ? 0 : 5 }),
          { status: 200 }
        );
      }
      return undefined;
    });
    const { container } = render(<JobsCatalog />);
    const trigger = await screen.findByTestId("jobs-catalog-trigger");
    expect(trigger).toHaveTextContent("2 个后台任务运行中");
    expect(trigger.querySelector(".v2-catalog-livedot")).not.toBeNull();

    empty = true;
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() =>
      expect(screen.queryByTestId("jobs-catalog-trigger")).not.toBeInTheDocument()
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("live 在前且 stopping/killed 语义分色文案正确", async () => {
    installFetch(() => undefined);
    render(<JobsCatalog />);
    fireEvent.click(await screen.findByTestId("jobs-catalog-trigger"));

    const rows = await screen.findAllByTestId("jobs-catalog-row");
    expect(rows).toHaveLength(5);
    // live（running/stopping）在最前，按开始时间升序（120s 前的 stopping 在 30s 前的 running 前）
    expect(rows[0]).toHaveTextContent("正在停止");
    expect(rows[1]).toHaveTextContent("运行中");
    // settled 按结束时间降序：killed(300s 前) 在 completed(540s 前) 前
    expect(rows[2]).toHaveTextContent("已取消");
    expect(rows[3]).toHaveTextContent("已完成");
    // orphaned 缺时间事实 → "—"，不伪造
    expect(rows[4]).toHaveTextContent("已失联");
    expect(rows[4].querySelector(".v2-jobs-duration")).toHaveTextContent("—");
    // 命令以等宽 label 呈现
    expect(rows[1].querySelector(".v2-jobs-label")).toHaveTextContent("npm run build");
  });

  it("live 行时长随 started_at 计算", async () => {
    installFetch(() => undefined);
    render(<JobsCatalog />);
    fireEvent.click(await screen.findByTestId("jobs-catalog-trigger"));
    const rows = await screen.findAllByTestId("jobs-catalog-row");
    expect(rows[1].querySelector(".v2-jobs-duration")).toHaveTextContent(/30秒/);
  });
});
