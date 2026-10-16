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

// ── 阶段2: 知识打分展示（徽标 + 打分明细页签） ─────────────────────────────

const expRef = "experience:EXPERIENCE-20261001-aaaaaa";

const scoreSummary = {
  top_label: "显著帮助",
  top_level: 4,
  confidence: 0.61,
  expected: 3.2,
  p_evidence_sufficient: 0.8,
  scored_slots: 2,
  last_scored_at: "2026-10-15T11:00:00+08:00",
  evidence_level: "independently_evaluated",
  scorer_model: "27B-Instant-MLX-8bit",
};

const ledgerRows = [
  {
    ledger_seq: 1,
    ref: expRef,
    kind: "experience",
    adopted: true,
    top_label: "显著帮助",
    top_level: 4,
    confidence: 0.61,
    expected: 3.2,
    p_evidence_sufficient: 0.8,
    decision_reported: "adapted",
    error: "",
    ts: "2026-10-15T10:00:00+08:00",
    scorer_model: "27B-Instant-MLX-8bit",
  },
  {
    ledger_seq: 2,
    ref: "method:method-x",
    kind: "method",
    adopted: false,
    top_label: "",
    top_level: -1,
    confidence: 0,
    expected: 0,
    p_evidence_sufficient: 0,
    decision_reported: "applied",
    error: "scorer unavailable",
    ts: "2026-10-16T09:00:00+08:00",
    scorer_model: "",
  },
];

async function openKnowledgePage(
  scoresBody: unknown,
  scoresStatus = 200,
  methodsBody: unknown = { counts: {}, records: [] }
): Promise<void> {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/learning/status")) return jsonResponse({ detail: "down" }, 503);
    if (url.includes("/api/v1/knowledge/experiences")) return jsonResponse(catalog);
    if (url.includes("/api/v1/knowledge/methods")) return jsonResponse(methodsBody);
    if (url.includes("/api/v1/knowledge/scores")) return jsonResponse(scoresBody, scoresStatus);
    return jsonResponse({ sessions: [], count: 0 });
  }));
  await renderApp();
  await act(async () => {
    fireEvent.click(screen.getByTestId("knowledge-entry"));
  });
}

describe("知识页：打分徽标与打分明细页签（阶段2）", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    cleanup();
    mainViewStore.setView("chat");
    learningPageStore.setPage("knowledge");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("经验卡 ref 命中打分索引时显示打分徽标（短模型名·标签 置信度）", async () => {
    await openKnowledgePage({
      count: 2,
      scores: { [expRef]: scoreSummary },
      ledger: ledgerRows,
    });
    const badge = await screen.findByTestId("score-badge");
    expect(badge.textContent).toBe("27B·显著帮助 0.61");
  });

  it("ref 未命中打分索引时不显示徽标，卡片列表正常", async () => {
    await openKnowledgePage({ count: 1, scores: {}, ledger: ledgerRows });
    expect(await screen.findByTestId("experience-card")).toBeTruthy();
    expect(screen.queryByTestId("score-badge")).toBeNull();
  });

  it("方法卡按 key 命中打分索引时显示徽标，未打分卡不显示（阶段2 P1-3）", async () => {
    // 后端 methods inventory 的 card() 投影：key=method:<id>（无 method_ref 字段）
    const methodsBody = {
      counts: { candidate: 2 },
      records: [
        {
          id: "method-x",
          key: "method:method-x",
          summary: "已打分方法卡",
          description: "scored method",
          status: "candidate",
          ts: "2026-10-15T10:00:00+08:00",
        },
        {
          id: "method-unscored",
          key: "method:method-unscored",
          summary: "未打分方法卡",
          description: "unscored method",
          status: "candidate",
          ts: "2026-10-15T10:00:00+08:00",
        },
      ],
    };
    await openKnowledgePage(
      { count: 1, scores: { "method:method-x": scoreSummary }, ledger: ledgerRows },
      200,
      methodsBody
    );
    const panel = await screen.findByTestId("knowledge-panel");
    await act(async () => {
      fireEvent.click(within(panel).getByRole("button", { name: /方法/ }));
    });
    const cards = await screen.findAllByTestId("method-card");
    expect(cards.length).toBe(2);
    // 打分卡：徽标精确文案（短模型名·标签 置信度）
    const badge = within(cards[0]).getByTestId("score-badge");
    expect(badge.textContent).toBe("27B·显著帮助 0.61");
    // 未打分卡：不显示徽标
    expect(within(cards[1]).queryByTestId("score-badge")).toBeNull();
  });

  it("打分明细页签：ledger 条目按时间倒序、采纳标记与 error 红字齐全", async () => {
    await openKnowledgePage({
      count: 2,
      scores: { [expRef]: scoreSummary },
      ledger: ledgerRows,
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /打分明细/ }));
    });
    const entries = await screen.findAllByTestId("score-entry");
    expect(entries.length).toBe(2);
    // 倒序：最新（ts=10-16，error 行）在前
    const firstRef = within(entries[0]).getByTestId("score-entry-ref");
    expect(firstRef.getAttribute("title")).toBe("method:method-x");
    expect(within(entries[0]).getByTestId("score-entry-error").textContent).toContain("scorer unavailable");
    expect(entries[0].textContent).toContain("✗未采纳");
    // 旧的成功行在后
    expect(within(entries[1]).getByTestId("score-entry-ref").getAttribute("title")).toBe(expRef);
    expect(entries[1].textContent).toContain("✓采纳");
    expect(entries[1].textContent).toContain("2026-10-15");
  });

  it("打分接口失败时静默降级：列表正常、无徽标、明细页显示空态并 warn 一次", async () => {
    await openKnowledgePage({ detail: "down" }, 503);
    expect(await screen.findByTestId("experience-card")).toBeTruthy();
    expect(screen.queryByTestId("score-badge")).toBeNull();
    expect(console.warn).toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /打分明细/ }));
    });
    expect(await screen.findByTestId("scores-empty")).toBeTruthy();
    expect(screen.getByTestId("scores-empty").textContent).toContain("暂无打分记录");
  });
});
