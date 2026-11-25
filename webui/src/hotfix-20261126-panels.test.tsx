// HOTFIX-20261126 定向回归：gen457 三入口性能热修复
// 覆盖：fetchRead 超时/外部取消；KnowledgePanel 每源渐进显示与失败保留旧数据；
// LearningPanel 陈旧标记与防重入/隐藏页暂停；ServicesPanel 首屏 loading 与卸载取消。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { fetchRead } from "./core/api";
import { KnowledgePanel } from "./components/learning/KnowledgePanel";
import { LearningPanel } from "./components/learning/LearningPanel";
import { ServicesPanel } from "./components/services/ServicesPanel";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// fetch 挂起但遵守 abort 信号（真实 fetch 语义）
function stubFetchHanging() {
  return vi.fn((_url: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError"))
      );
    })
  );
}

const expBody = {
  records: [
    {
      experience_id: "exp-1",
      experience_ref: "experience:exp-1",
      title: "经验一",
      summary: "经验一摘要",
      status: "active",
      ts: "2026-11-26T00:00:00",
    },
  ],
  counts: { active: 1 },
};
const mthBody = {
  records: [
    {
      id: "m1",
      key: "method:m1",
      summary: "方法一",
      description: "描述",
      status: "active",
    },
  ],
  counts: { active: 1 },
};
const scoresBody = { count: 0, scores: {}, ledger: [] };
const learningBody = {
  enabled: true,
  producer_only: false,
  worker: { running: true, model_ref: "test-model" },
  counts: { queued: 1, started: 0, saved: 1, failed: 0 },
  jobs: [{ job_id: "j1", state: "saved" }],
};

beforeEach(() => {
  vi.unstubAllGlobals();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchRead（HOTFIX-20261126）", () => {
  it("慢端点在超时上限返回 error=timeout，不再永久挂起", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", stubFetchHanging());
    const p = fetchRead("/api/v1/knowledge/methods");
    await vi.advanceTimersByTimeAsync(12500);
    const result = await p;
    expect(result.status).toBe(0);
    expect(result.error).toBe("timeout");
  });

  it("外部取消返回 error=aborted", async () => {
    vi.stubGlobal("fetch", stubFetchHanging());
    const controller = new AbortController();
    const p = fetchRead("/api/v1/services/status", { signal: controller.signal });
    controller.abort();
    const result = await p;
    expect(result.status).toBe(0);
    expect(result.error).toBe("aborted");
  });
});

describe("KnowledgePanel（HOTFIX-20261126）", () => {
  it("methods 挂起时 experiences 先独立渲染（解除 allSettled 首屏耦合）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/knowledge/experiences")) return jsonResponse(expBody);
        if (url.includes("/api/v1/knowledge/methods")) return new Promise<Response>(() => {});
        if (url.includes("/api/v1/knowledge/scores")) return jsonResponse(scoresBody);
        throw new Error(`unexpected ${url}`);
      })
    );
    await act(async () => {
      render(<KnowledgePanel />);
    });
    await waitFor(() => expect(screen.getByText("经验 (1)")).toBeTruthy());
    expect(screen.queryByTestId("exp-loading")).toBeNull();
  });

  it("在途请求被参数变化取消后，新查询立即接手（独审 P1-1 回归）", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/knowledge/experiences")) return new Promise<Response>(() => {});
      if (url.includes("/api/v1/knowledge/scores")) return jsonResponse(scoresBody);
      throw new Error(`unexpected ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    await act(async () => {
      render(<KnowledgePanel />);
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3)); // 挂载：experiences(挂起)+methods(挂起)+scores
    // 输入新查询 → effect 清理 abort 旧请求 → 新 loader 必须立即接手并发起新查询请求
    await act(async () => {
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: "新词" } });
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some((c) => String(c[0]).includes("query=") && String(c[0]).includes("%E6%96%B0%E8%AF%8D"))
      ).toBeTruthy()
    );
  });

  it("刷新失败保留最近有效数据并标记陈旧（不清空旧数据）", async () => {
    let mthFails = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/knowledge/experiences")) return jsonResponse(expBody);
        if (url.includes("/api/v1/knowledge/methods")) {
          if (mthFails) return jsonResponse({ detail: "down" }, 503);
          return jsonResponse(mthBody);
        }
        if (url.includes("/api/v1/knowledge/scores")) return jsonResponse(scoresBody);
        throw new Error(`unexpected ${url}`);
      })
    );
    await act(async () => {
      render(<KnowledgePanel />);
    });
    await waitFor(() => expect(screen.getByText("方法 (1)")).toBeTruthy());
    // 切到方法页签（错误横幅随页签渲染）
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "方法 (1)" }));
    });
    mthFails = true;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    });
    await waitFor(() => expect(screen.getByTestId("mth-stale")).toBeTruthy());
    expect(screen.getByTestId("mth-stale").textContent).toContain("最近有效数据");
    expect(screen.getByText("方法 (1)")).toBeTruthy(); // 旧数据保留
    expect(screen.getByTestId("method-card")).toBeTruthy(); // 保留列表仍渲染
  });
});

describe("LearningPanel（HOTFIX-20261126）", () => {
  it("轮询失败保留最近有效状态并显示陈旧横幅", async () => {
    vi.useFakeTimers();
    let fail = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/learning/status")) {
          if (fail) return jsonResponse({ detail: "x" }, 503);
          return jsonResponse(learningBody);
        }
        throw new Error(`unexpected ${url}`);
      })
    );
    await act(async () => {
      render(<LearningPanel />);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("j1")).toBeTruthy();
    fail = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(screen.getByTestId("learning-stale")).toBeTruthy();
    expect(screen.getByText("j1")).toBeTruthy(); // 最近有效数据保留
  });

  it("在途请求期间轮询不叠加（防重入）", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetchHanging();
    vi.stubGlobal("fetch", fetchMock);
    await act(async () => {
      render(<LearningPanel />);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000); // 5s tick：在途 → 防重入跳过
    });
    expect(fetchMock).toHaveBeenCalledTimes(1); // 无叠加请求
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000); // 10s 超时释放在途 → 15s tick 允许新请求
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("标签隐藏期间轮询零新增请求（离开页面停止刷新）", async () => {
    vi.useFakeTimers();
    const hiddenSpy = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const fetchMock = vi.fn(async () => jsonResponse(learningBody));
    vi.stubGlobal("fetch", fetchMock);
    await act(async () => {
      render(<LearningPanel />);
      await vi.advanceTimersByTimeAsync(0);
    });
    const afterMount = fetchMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(fetchMock.mock.calls.length).toBe(afterMount);
    hiddenSpy.mockRestore();
  });
});

describe("ServicesPanel（HOTFIX-20261126）", () => {
  it("首屏立即显示明确 loading（修复空白首屏）", () => {
    vi.stubGlobal("fetch", stubFetchHanging());
    render(<ServicesPanel />);
    expect(screen.getByTestId("services-loading")).toBeTruthy();
  });

  it("卸载时取消在途请求（离开页面停止后台刷新）", () => {
    let aborted = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              aborted = true;
              reject(new DOMException("aborted", "AbortError"));
            });
          })
      )
    );
    const { unmount } = render(<ServicesPanel />);
    unmount();
    expect(aborted).toBe(true);
  });
});
