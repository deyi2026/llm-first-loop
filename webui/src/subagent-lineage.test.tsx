// 子代理谱系（SubagentLineage）产品契约：
// - 只在当前会话有子会话时显示 trigger（运行中带 active 点 + 运行计数）
// - 行 = 状态点 · 标题 · 活动/结果/未回收徽标；点击切换会话（导航）
// - topology 未知（无 activity 字段）显示“状态未知”，不伪造
// - 端点缺失 → 整个入口隐藏且不再轮询

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SubagentLineage } from "./components/conversation/SubagentLineage";
import { sessionStore } from "./core/stores";
import type { AgentTreeNode } from "./core/api";

function nodes(): AgentTreeNode[] {
  return [
    { id: "s1", parent_id: null, is_subagent: false },
    {
      id: "subagent_child1",
      parent_id: "s1",
      is_subagent: true,
      activity: "running",
      outcome: "",
      settlement: "uncollected",
    },
    {
      id: "subagent_child2",
      parent_id: "s1",
      is_subagent: true,
      activity: "inactive",
      outcome: "completed",
      settlement: "collected",
    },
    {
      id: "subagent_child3",
      parent_id: "s1",
      is_subagent: true,
      // topology 未知：无 activity 字段
    },
    { id: "subagent_other", parent_id: "s9", is_subagent: true },
  ];
}

function installFetch(
  action: (url: string) => Response | undefined
) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const response = action(url);
    if (response) return response;
    if (url.includes("/api/v1/agents/tree")) {
      return new Response(JSON.stringify({ nodes: nodes() }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStore.setCurrentSession("s1");
  sessionStore.setSessions([
    {
      session_id: "s1",
      title: "父会话",
      created_at: "",
      updated_at: "",
      message_count: 1,
      status: "idle",
      last_message_preview: "",
      pinned: false,
      channel: "web",
    },
    {
      session_id: "subagent_child1",
      title: "调研子代理",
      created_at: "",
      updated_at: "",
      message_count: 1,
      status: "idle",
      last_message_preview: "",
      pinned: false,
      channel: "web",
    },
    {
      session_id: "subagent_child2",
      title: "验证子代理",
      created_at: "",
      updated_at: "",
      message_count: 1,
      status: "idle",
      last_message_preview: "",
      pinned: false,
      channel: "web",
    },
    {
      session_id: "subagent_child3",
      title: "未知状态子代理",
      created_at: "",
      updated_at: "",
      message_count: 1,
      status: "idle",
      last_message_preview: "",
      pinned: false,
      channel: "web",
    },
  ]);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStore.setSessions([]);
});

describe("subagent lineage (DSH SubagentHeaderLineage parity)", () => {
  it("无子会话不渲染；有子会话显示运行计数 + active 点", async () => {
    let empty = false;
    installFetch((url) => {
      if (url.includes("/api/v1/agents/tree")) {
        return new Response(
          JSON.stringify({ nodes: empty ? [{ id: "s1", parent_id: null, is_subagent: false }] : nodes() }),
          { status: 200 }
        );
      }
      return undefined;
    });
    const { container } = render(<SubagentLineage />);
    const trigger = await screen.findByTestId("subagent-lineage-trigger");
    expect(trigger).toHaveTextContent("1 个子代理运行中");
    expect(trigger.querySelector(".v2-catalog-livedot.ongoing")).not.toBeNull();

    empty = true;
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() =>
      expect(screen.queryByTestId("subagent-lineage-trigger")).not.toBeInTheDocument()
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("行展示活动/结果/未回收徽标；topology 未知显示状态未知", async () => {
    installFetch(() => undefined);
    render(<SubagentLineage />);
    fireEvent.click(await screen.findByTestId("subagent-lineage-trigger"));

    const rows = await screen.findAllByTestId("subagent-lineage-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("调研子代理");
    expect(rows[0]).toHaveTextContent("运行中");
    expect(rows[0]).toHaveTextContent("结果未回收");
    expect(rows[1]).toHaveTextContent("验证子代理");
    expect(rows[1]).toHaveTextContent("未运行");
    expect(rows[1]).toHaveTextContent("已完成");
    expect(rows[2]).toHaveTextContent("状态未知");
  });

  it("点击行切换到该子会话", async () => {
    installFetch(() => undefined);
    render(<SubagentLineage />);
    fireEvent.click(await screen.findByTestId("subagent-lineage-trigger"));
    const rows = await screen.findAllByTestId("subagent-lineage-row");
    fireEvent.click(rows[0]);
    expect(sessionStore.getState().currentSessionId).toBe("subagent_child1");
    await waitFor(() =>
      expect(screen.queryByTestId("subagent-lineage-menu")).not.toBeInTheDocument()
    );
  });

  it("端点缺失（非 200）→ 隐藏入口且不再轮询", async () => {
    const calls: string[] = [];
    installFetch((url) => {
      if (url.includes("/api/v1/agents/tree")) {
        calls.push(url);
        return new Response(JSON.stringify({ error: "not_found" }), { status: 404 });
      }
      return undefined;
    });
    const { container } = render(<SubagentLineage />);
    await waitFor(() => expect(calls).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 30));
    expect(calls).toHaveLength(1);
    expect(container).toBeEmptyDOMElement();
  });
});
