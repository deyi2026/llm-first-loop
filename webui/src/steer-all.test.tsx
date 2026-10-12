// 全部插话（steer-all，对齐 DSH steerQueue）产品契约：
// - 空草稿 + 流式生成中 + 有 queued 项 → Cmd/Ctrl+Enter FIFO 逐条 interject
// - placeholder 切换为“插话发送全部排队消息”提示
// - 任一条 409 即停，剩余项保持 queued（不重复、不丢弃），detail 如实显示

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { conversationStore as conv } from "./core/conversation";
import { sessionStore } from "./core/stores";
import type { QueueItem } from "./core/types";

function queued(id: string, text: string, seq: number): QueueItem {
  return {
    queue_id: id,
    session_id: "s1",
    message: text,
    attachments: [],
    model: null,
    reasoning_effort: null,
    reasoning_mode: "auto",
    attachment_facts: [],
    status: "queued",
    created_at: seq,
  };
}

function installFetch(
  interject: (queueId: string, runGeneration: string) => Response
) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/v1/chat/queue/interject") && init?.method === "POST") {
      const body = JSON.parse(String(init.body ?? "{}")) as {
        queue_id: string;
        run_generation: string;
      };
      return interject(body.queue_id, body.run_generation);
    }
    if (url.includes("/api/v1/models")) {
      return new Response(JSON.stringify({ models: [], current: null, catalog: [] }), { status: 200 });
    }
    if (url.includes("/api/v1/chat/queue?")) {
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
}

beforeEach(() => {
  localStorage.clear();
  sessionStore.setCurrentSession("s1");
  conv.setState({
    messages: [],
    composerPrefill: null,
    streaming: true,
    backgroundRunning: true,
    activeRunGeneration: "gen-steer-all-1",
    streamingIndex: -1,
    queueItems: [queued("q1", "第一条", 1), queued("q2", "第二条", 2)],
    lastError: null,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function pressCtrlEnter() {
  const input = screen.getByTestId("composer-input");
  fireEvent.keyDown(input, { key: "Enter", ctrlKey: true, metaKey: false });
}

describe("Cmd/Ctrl+Enter 全部插话", () => {
  it("空草稿 + 运行中 → FIFO 逐条 interject 并提示条数", async () => {
    const calls: string[] = [];
    installFetch((queueId, runGeneration) => {
      calls.push(`${queueId}:${runGeneration}`);
      return new Response(
        JSON.stringify({ ok: true, queue_id: queueId, state: "interject_pending" }),
        { status: 202 }
      );
    });
    render(<Composer />);
    expect(screen.getByTestId("composer-input")).toHaveAttribute(
      "placeholder",
      "Cmd/Ctrl+Enter 插话发送全部排队消息"
    );
    pressCtrlEnter();
    await waitFor(() => expect(calls).toEqual([
      "q1:gen-steer-all-1",
      "q2:gen-steer-all-1",
    ]));
    await waitFor(() =>
      expect(screen.getByText("已把 2 条排队消息交给当前任务")).toBeInTheDocument()
    );
  });

  it("中途 409 即停：只发已确认条数并显示后端 detail", async () => {
    const calls: string[] = [];
    installFetch((queueId, runGeneration) => {
      calls.push(`${queueId}:${runGeneration}`);
      if (queueId === "q1") {
        return new Response(
          JSON.stringify({ ok: true, queue_id: queueId, state: "interject_pending" }),
          { status: 202 }
        );
      }
      return new Response(
        JSON.stringify({
          ok: false,
          error: "interject_no_live_run",
          detail: "当前会话没有可接收插话的运行任务；消息仍保留在排队中",
        }),
        { status: 409 }
      );
    });
    render(<Composer />);
    pressCtrlEnter();
    await waitFor(() => expect(calls).toEqual([
      "q1:gen-steer-all-1",
      "q2:gen-steer-all-1",
    ]));
    await waitFor(() =>
      expect(
        screen.getByText("当前会话没有可接收插话的运行任务；消息仍保留在排队中")
      ).toBeInTheDocument()
    );
  });

  it("无排队项时空草稿 Cmd+Enter 不再走排队失败文案", async () => {
    conv.setState({ queueItems: [] });
    const calls: string[] = [];
    installFetch((queueId) => {
      calls.push(queueId);
      return new Response(JSON.stringify({ ok: true }), { status: 202 });
    });
    render(<Composer />);
    pressCtrlEnter();
    await waitFor(() =>
      expect(screen.getByText("没有可插话的排队消息。")).toBeInTheDocument()
    );
    expect(calls).toEqual([]);
  });
});
