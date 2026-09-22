// 安排目录（ScheduleCatalog）产品契约：
// - 只在有提醒时显示 trigger（空态不渲染，对齐 DSH）
// - popover：逾期行排最前 + warn 样式；元数据 = 频率 · 本地时间 · 相对时间
// - 取消是显式用户动作，成功后刷新列表

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ScheduleCatalog } from "./components/conversation/ScheduleCatalog";
import { sessionStore } from "./core/stores";
import type { ScheduleItem } from "./core/api";

function items(): ScheduleItem[] {
  const now = Math.floor(Date.now() / 1000);
  return [
    {
      sid: "sched-future",
      session_id: "s1",
      message: "一小时后检查后台任务",
      trigger_at: now + 3600,
      kind: "once",
      every_seconds: null,
      wake: false,
    },
    {
      sid: "sched-overdue",
      session_id: "s1",
      message: "周期 watchdog 已到点",
      trigger_at: now - 60,
      kind: "every",
      every_seconds: 300,
      repeat_interval: 300,
      max_count: 5,
      wake: true,
    },
  ];
}

function installFetch(
  action: (url: string, init?: RequestInit) => Response | undefined
) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const response = action(url, init);
    if (response) return response;
    if (url.includes("/api/v1/capabilities")) {
      return new Response(JSON.stringify({ capabilities: {} }), { status: 200 });
    }
    if (url.includes("/api/v1/sessions/s1/schedule")) {
      return new Response(JSON.stringify({ schedule: items(), count: 2 }), { status: 200 });
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

describe("schedule catalog (DSH ScheduleCatalogAction parity)", () => {
  it("空态完全不渲染；有提醒时显示计数 trigger", async () => {
    let empty = false;
    installFetch((url) => {
      if (url.includes("/api/v1/sessions/s1/schedule")) {
        return new Response(
          JSON.stringify({ schedule: empty ? [] : items(), count: empty ? 0 : 2 }),
          { status: 200 }
        );
      }
      return undefined;
    });
    const { container } = render(<ScheduleCatalog />);
    await waitFor(() =>
      expect(screen.getByTestId("schedule-catalog-trigger")).toBeInTheDocument()
    );
    expect(screen.getByTestId("schedule-catalog-trigger")).toHaveTextContent("2 个提醒");

    empty = true;
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() =>
      expect(screen.queryByTestId("schedule-catalog-trigger")).not.toBeInTheDocument()
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("打开后逾期行排最前并带 warn 元数据与频率", async () => {
    installFetch(() => undefined);
    render(<ScheduleCatalog />);
    fireEvent.click(await screen.findByTestId("schedule-catalog-trigger"));

    const rows = await screen.findAllByTestId("schedule-catalog-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveClass("overdue");
    expect(rows[0]).toHaveTextContent("已逾期");
    expect(rows[0]).toHaveTextContent("每 5 分钟一次");
    expect(rows[0]).toHaveTextContent(/已逾期 1 分钟/);
    expect(rows[0]).toHaveTextContent("到点自动续跑");
    expect(rows[1]).not.toHaveClass("overdue");
    expect(rows[1]).toHaveTextContent("等待中");
    expect(rows[1]).toHaveTextContent("单次");
  });

  it("取消走独立端点并刷新列表", async () => {
    const calls: string[] = [];
    let remaining = items();
    installFetch((url, init) => {
      if (url.includes("/schedule/sched-overdue/cancel") && init?.method === "POST") {
        calls.push(url);
        remaining = remaining.filter((it) => it.sid !== "sched-overdue");
        return new Response(JSON.stringify({ status: "ok", sid: "sched-overdue" }), {
          status: 200,
        });
      }
      if (url.includes("/api/v1/sessions/s1/schedule")) {
        return new Response(
          JSON.stringify({ schedule: remaining, count: remaining.length }),
          { status: 200 }
        );
      }
      return undefined;
    });
    render(<ScheduleCatalog />);
    fireEvent.click(await screen.findByTestId("schedule-catalog-trigger"));
    fireEvent.click((await screen.findAllByTestId("schedule-catalog-cancel"))[0]);

    await waitFor(() => expect(calls).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByTestId("schedule-catalog-trigger")).toHaveTextContent("1 个提醒")
    );
  });

  it("Escape 关闭菜单", async () => {
    installFetch(() => undefined);
    render(<ScheduleCatalog />);
    fireEvent.click(await screen.findByTestId("schedule-catalog-trigger"));
    const menu = await screen.findByTestId("schedule-catalog-menu");
    fireEvent.keyDown(menu.parentElement as HTMLElement, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("schedule-catalog-menu")).not.toBeInTheDocument()
    );
  });
});
