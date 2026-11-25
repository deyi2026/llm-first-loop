// 侧栏轻量化专项（2026-11-25）回归：
// 1) 左栏不常驻显示运行版本 gen/SHA/CLI 详情；仅未知/陈旧/异常时出现紧凑可点击提示；
// 2) 低频入口（知识管理/学习通道/服务身份）收纳为列表下方紧凑工具区，testid 保持兼容；
// 3) 会话优先：新建/搜索/会话列表在工具区之前；七个标签与协调通道保留。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { computeRuntimeAlert } from "./components/sidebar/RuntimeConvergenceStrip";
import { __resetCapabilitiesForTest } from "./core/capabilities";
import { mainViewStore, sessionStore, sidebarViewStore } from "./core/stores";

const h = vi.hoisted(() => {
  const listeners: Array<(value: Record<string, unknown> | null) => void> = [];
  return {
    reset: () => {
      listeners.length = 0;
    },
    push: (value: Record<string, unknown> | null) => {
      for (const listener of [...listeners]) listener(value);
    },
    subscribe: (listener: (value: Record<string, unknown> | null) => void) => {
      listeners.push(listener);
      return () => {
        const index = listeners.indexOf(listener);
        if (index >= 0) listeners.splice(index, 1);
      };
    },
  };
});

vi.mock("./core/coordinationBoard", () => ({
  subscribeCoordinationBoard: h.subscribe,
  fetchCoordinationBoard: () => Promise.resolve(null),
  refreshCoordinationBoard: () => Promise.resolve(),
}));

const sessions = [
  {
    session_id: "m1", title: "长会话甲", channel: "web", message_count: 3, pinned: false,
    status: "active", created_at: "2026-11-25T08:00:00Z", updated_at: "2026-11-25T09:00:00Z",
    last_message_preview: "内容甲",
  },
  {
    session_id: "m2", title: "长会话乙", channel: "web", message_count: 2, pinned: false,
    status: "active", created_at: "2026-11-25T07:00:00Z", updated_at: "2026-11-25T08:00:00Z",
    last_message_preview: "内容乙",
  },
  {
    session_id: "m3", title: "长会话丙", channel: "web", message_count: 1, pinned: false,
    status: "active", created_at: "2026-11-24T08:00:00Z", updated_at: "2026-11-24T09:00:00Z",
    last_message_preview: "内容丙",
  },
];

const okSnapshot = {
  desired_generation: 456,
  desired_git_head: "6349346d8a93cfd98d2ba464fc0dc45a4db84b51",
  desired_version: "0.6.0",
  services: {
    web: { state: "artifact_matches", pid: 101, git_head: "6349346d8a", version: "0.6.0", wheel_sha256: "a1", inferred: false },
    feishu: { state: "identity_matches_target", pid: 102, git_head: "6349346d8a", version: "0.6.0", wheel_sha256: "b2", inferred: false },
    wecom: { state: "artifact_matches", pid: 103, git_head: "6349346d8a", version: "0.6.0", wheel_sha256: "c3", inferred: false },
    learning: { state: "identity_matches_target", pid: 104, git_head: "6349346d8a", version: "0.6.0", wheel_sha256: "d4", inferred: false },
  },
  cli: {
    state: "identity_matches_target",
    processes: [{ pid: 900, generation: 456, git_head: "6349346d8a", state: "identity_matches_target" }],
    uncertain: 0,
  },
};

async function mountSidebar(): Promise<void> {
  render(<Sidebar collapsed={false} />);
  await screen.findByText("长会话甲");
}

beforeEach(() => {
  h.reset();
  __resetCapabilitiesForTest();
  mainViewStore.setView("chat");
  sidebarViewStore.setView("sessions");
  sessionStore.setSessions(sessions as never);
  sessionStore.setCurrentSession("m1");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const res = (status: number, body: unknown) =>
        ({ ok: status < 400, status, json: async () => body }) as Response;
      if (url.includes("/api/v1/workspaces/secondary/sessions")) return res(200, []);
      if (url.includes("/api/v1/workspaces") && !url.includes("/sessions")) {
        return res(200, {
          current: "primary",
          workspaces: [
            { id: "primary", path: "/project/primary" },
            { id: "secondary", path: "/project/secondary" },
          ],
        });
      }
      if (url.includes("/api/v1/session/current")) return res(200, { current: "m1" });
      if (url === "/api/v1/sessions" || url.includes("/api/v1/sessions?")) return res(200, { sessions });
      if (url.includes("/api/v1/agents/tree")) return res(200, { agents: [] });
      return res(200, {});
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStore.setCurrentSession("");
  sessionStore.setSessions([]);
});

describe("computeRuntimeAlert（未知/陈旧不冒充正常）", () => {
  it("缺快照/stale/无代次/服务或 CLI 未确认都给出需关注原因", () => {
    expect(computeRuntimeAlert(null, true)).toBe("运行状态待刷新");
    expect(computeRuntimeAlert(null, false)).toBe("运行状态未知");
    expect(computeRuntimeAlert({ ...okSnapshot, desired_generation: null }, false)).toBe("运行代次未知");
    const degraded = {
      ...okSnapshot,
      services: { ...okSnapshot.services, web: { ...okSnapshot.services.web, state: "update_required" } },
    };
    const reason = computeRuntimeAlert(degraded, false);
    expect(reason).toContain("1 项需关注");
    expect(reason).toContain("web");
    expect(computeRuntimeAlert(okSnapshot, false)).toBeNull();
    const cliUncertain = { ...okSnapshot, cli: { ...okSnapshot.cli, state: "update_required" } };
    expect(computeRuntimeAlert(cliUncertain, false)).toContain("CLI");
  });
});

describe("侧栏轻量化：运行信息收纳", () => {
  it("全部正常时左栏不渲染任何运行版本信息", async () => {
    await mountSidebar();
    act(() => {
      h.push({ runtime_convergence: okSnapshot });
    });
    expect(screen.queryByTestId("runtime-alert-strip")).not.toBeInTheDocument();
    expect(screen.queryByText(/运行版本/)).toBeNull();
    expect(screen.queryByText(/gen\s*456/)).toBeNull();
  });

  it("服务异常时渲染紧凑可点击提示，点击进入服务身份页", async () => {
    await mountSidebar();
    act(() => {
      h.push({
        runtime_convergence: {
          ...okSnapshot,
          services: { ...okSnapshot.services, web: { ...okSnapshot.services.web, state: "update_required" } },
        },
      });
    });
    const alert = screen.getByTestId("runtime-alert-strip");
    expect(alert).toHaveTextContent("1 项需关注");
    expect(alert).toHaveTextContent("web 待切换");
    fireEvent.click(alert);
    expect(mainViewStore.getState().view).toBe("services");
  });

  it("快照缺失或陈旧时提示待刷新/未知，不冒充正常", async () => {
    await mountSidebar();
    act(() => {
      h.push(null);
    });
    expect(screen.getByTestId("runtime-alert-strip")).toHaveTextContent("运行状态待刷新");
    act(() => {
      h.push({});
    });
    expect(screen.getByTestId("runtime-alert-strip")).toHaveTextContent("运行状态未知");
  });

  it("CLI 未确认也触发提示（工件匹配信息由服务身份页承载）", async () => {
    await mountSidebar();
    act(() => {
      h.push({
        runtime_convergence: {
          ...okSnapshot,
          cli: { ...okSnapshot.cli, state: "update_required" },
        },
      });
    });
    expect(screen.getByTestId("runtime-alert-strip")).toHaveTextContent("CLI 待切换");
  });
});

describe("侧栏轻量化：会话优先与低频入口收纳", () => {
  it("新建/搜索/会话列表在工具区之前；三个入口与七个标签保留", async () => {
    await mountSidebar();
    act(() => {
      h.push({ runtime_convergence: okSnapshot });
    });
    const newSession = screen.getByTestId("new-session");
    const search = screen.getByPlaceholderText("搜索会话…");
    const list = screen.getByTestId("session-list");
    const tools = screen.getByTestId("sidebar-tools");
    const following = (a: Element, b: Element) =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(following(newSession, list)).toBe(true);
    expect(following(search, list)).toBe(true);
    expect(following(list, tools)).toBe(true);
    for (const testId of [
      "knowledge-entry",
      "learning-entry",
      "services-entry",
      "tab-sessions",
      "tab-files",
      "tab-evo",
      "tab-esc",
      "tab-archived",
      "tab-metrics",
      "tab-lanes",
      "coordination-channel",
    ]) {
      expect(screen.getByTestId(testId)).toBeInTheDocument();
    }
  });

  it("低频入口点击仍能切换到对应视图", async () => {
    await mountSidebar();
    fireEvent.click(screen.getByTestId("knowledge-entry"));
    expect(mainViewStore.getState().view).toBe("learning");
    fireEvent.click(screen.getByTestId("services-entry"));
    expect(mainViewStore.getState().view).toBe("services");
    expect(screen.getByTestId("services-entry").className).toContain("active");
    fireEvent.click(screen.getByTestId("learning-entry"));
    expect(mainViewStore.getState().view).toBe("learning");
  });
});
