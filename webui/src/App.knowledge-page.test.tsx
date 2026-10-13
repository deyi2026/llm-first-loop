// EVO-20261013-4 新功能回归：经验卡「使用次数/最近使用」展示 + 学习通道/知识管理按钮页面切换
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, act, fireEvent, within } from "@testing-library/react";
import { App } from "./App";
import { learningPageStore, mainViewStore } from "./core/stores";

const catalog = {
  counts: { active: 1 },
  records: [
    {
      id: "EXPERIENCE-20261001-aaaaaa",
      experience_ref: "experience:EXPERIENCE-20261001-aaaaaa",
      title: "示例经验卡",
      record_kind: "experience",
      verification_state: "verified",
      use_count: 3,
      last_used_at: "2026-10-12T09:30:00+08:00",
      updated_at: "2026-10-01T08:00:00+08:00",
    },
  ],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function renderApp(): Promise<void> {
  await act(async () => {
    render(<App />);
    await new Promise((r) => window.setTimeout(r, 0));
  });
}

describe("知识页：经验卡使用统计与页面切换（4b21343d9 后续）", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/learning/status")) return jsonResponse({ detail: "down" }, 503);
      if (url.includes("/api/v1/knowledge/experiences")) return jsonResponse(catalog);
      if (url.includes("/api/v1/knowledge/methods")) return jsonResponse({ counts: {}, records: [] });
      return jsonResponse({ sessions: [], count: 0 });
    }));
  });
  afterEach(() => {
    cleanup();
    mainViewStore.setView("chat");
    learningPageStore.setPage("knowledge");
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("经验卡展示使用次数与最近使用日期", async () => {
    await renderApp();
    await act(async () => {
      fireEvent.click(screen.getByTestId("knowledge-entry"));
    });
    const useCount = await screen.findByTestId("experience-use-count");
    expect(useCount.textContent).toContain("使用 3 次");
    const lastUsed = await screen.findByTestId("experience-last-used");
    expect(lastUsed.textContent).toContain("最近使用 2026-10-12");
  });

  it("侧栏「学习通道/知识管理」按钮切换页面", async () => {
    await renderApp();
    // 学习通道 → 学习页（status 503 显示不可用占位，亦证明学习面板已挂载）。
    await act(async () => {
      fireEvent.click(screen.getByTestId("learning-entry"));
    });
    expect(await screen.findByText("学习通道状态暂不可用")).toBeTruthy();
    expect(screen.queryByTestId("knowledge-panel")).toBeNull();
    // 知识管理 → 知识页（经验目录加载成功，学习面板不在 DOM）。
    await act(async () => {
      fireEvent.click(screen.getByTestId("knowledge-entry"));
    });
    expect(await screen.findByTestId("knowledge-panel")).toBeTruthy();
    expect(screen.queryByText("学习通道状态暂不可用")).toBeNull();
  });

  it("页面顶部页签可在两页之间切换", async () => {
    await renderApp();
    await act(async () => {
      fireEvent.click(screen.getByTestId("learning-entry"));
    });
    expect(await screen.findByText("学习通道状态暂不可用")).toBeTruthy();
    await act(async () => {
      const tabs = within(screen.getByTestId("learning-pagetabs"));
      fireEvent.click(tabs.getByRole("button", { name: /知识管理/ }));
    });
    expect(await screen.findByTestId("knowledge-panel")).toBeTruthy();
  });
});
