// EVO-20261013-2 回归：journal 降级信号 / knowledge 503 不伪装空库 / candidate_ref 标注
// EVO-20261013-4 改版：学习页改为页签切换（知识管理置顶），回归口径同步更新。
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, act, fireEvent, within } from "@testing-library/react";
import { App } from "./App";
import { learningPageStore, mainViewStore } from "./core/stores";

const learningStatus = {
  enabled: true,
  producer_only: false,
  worker: { running: true, model_ref: "glm/glm-5.3", manifest_present: true },
  counts: { queued: 8, started: 0, saved: 12, failed: 0 },
  jobs: [
    { job_id: "job-a", state: "queued", enqueued_at: "2026-10-13T06:00:00+08:00" },
    {
      job_id: "job-b", state: "saved",
      enqueued_at: "2026-10-13T05:00:00+08:00", finished_at: "2026-10-13T05:01:00+08:00",
      candidate_ref: "memory-extract:abc entries=11",
    },
    {
      job_id: "job-c", state: "saved",
      enqueued_at: "2026-10-13T04:00:00+08:00", finished_at: "2026-10-13T04:01:00+08:00",
      candidate_ref: "method:mth-42",
    },
  ],
  oldest_queued: { age_seconds: 120, job_id: "job-a" },
  admission: { present: true, state: "blocked", reason: "foreground_session_active", queued: 5, age_seconds: 30 },
  requeue_stats: {
    total: { admission_refused: 3, stale_heartbeat: 1 },
    recent: { admission_refused: 1 },
    recent_window_s: 900,
    last_event_ts: 1760300000,
  },
  observability_errors: ["jobs", "count_states"],
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function renderLearningView(page: "learning" | "knowledge" = "knowledge"): Promise<void> {
  await act(async () => {
    render(<App />);
    mainViewStore.setView("learning");
    learningPageStore.setPage(page);
    await new Promise((r) => window.setTimeout(r, 0));
  });
}

describe("learning 通道修复回归（4b21343d9）", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/learning/status")) return jsonResponse(learningStatus);
      if (url.includes("/api/v1/knowledge/experiences")) return jsonResponse({ detail: "down" }, 503);
      if (url.includes("/api/v1/knowledge/methods")) return jsonResponse({ detail: "down" }, 503);
      if (url.includes("/api/v1/knowledge/scores")) return jsonResponse({ count: 0, scores: {}, ledger: [] });
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

  it("journal 降级信号显示警告横幅，而非静默全 0", async () => {
    await renderLearningView("learning");
    const banner = await screen.findByTestId("journal-error");
    expect(banner.textContent).toContain("jobs");
    expect(banner.textContent).toContain("count_states");
  });

  it("knowledge 503 显示读取失败而非伪装成空库", async () => {
    await renderLearningView();
    expect(await screen.findByTestId("exp-load-error")).toBeTruthy();
    const methodTab = await screen.findByRole("button", { name: /方法/ });
    await act(async () => {
      fireEvent.click(methodTab);
    });
    expect(await screen.findByTestId("mth-load-error")).toBeTruthy();
    expect(screen.queryByText("无匹配经验")).toBeNull();
    expect(screen.queryByText("无匹配方法")).toBeNull();
  });

  it("candidate_ref 按前缀标注产物类型", async () => {
    await renderLearningView("learning");
    expect(await screen.findByText("记忆抽取产物")).toBeTruthy();
    expect(await screen.findByText("Method candidate")).toBeTruthy();
  });

  it("learning 视图保持单一滚动容器，页签二选一挂载面板（改版后口径）", async () => {
    await renderLearningView("knowledge");
    const view = await screen.findByTestId("learning-view");
    expect(view.className).toContain("v2-learning-view");
    // 知识管理置顶为默认页：只挂载知识面板，学习面板不在 DOM。
    expect(view.querySelector('[data-testid="knowledge-panel"]')).toBeTruthy();
    expect(view.querySelector("main.v2-learning-panel")).toBeNull();
    // 点击「学习通道」页签切换到学习页（503 时显示不可用占位，亦证明面板已挂载）。
    const tab = within(screen.getByTestId("learning-pagetabs")).getByRole("button", { name: /学习通道/ });
    await act(async () => {
      fireEvent.click(tab);
    });
    expect(view.querySelector("main.v2-learning-panel")).toBeTruthy();
    expect(view.querySelector('[data-testid="knowledge-panel"]')).toBeNull();
  });
});
