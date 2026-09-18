import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatQueue } from "./components/conversation/ChatQueue";
import { Composer } from "./components/conversation/Composer";
import { conversationStore } from "./core/conversation";
import { sessionStore } from "./core/stores";
import type { QueueItem } from "./core/types";

const REF = "attachment://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

function item(status: QueueItem["status"] = "queued"): QueueItem {
  return {
    queue_id: "q1",
    session_id: "s1",
    message: "排队正文",
    attachments: [{ ref: REF }],
    attachment_facts: [{ ref: REF, filename: "queued.txt", content_type: "text/plain" }],
    model: "glm/glm-5.3",
    reasoning_effort: null,
    reasoning_mode: "auto",
    status,
    created_at: 1,
  };
}

function installFetch(
  action: (url: string, init?: RequestInit) => Response | undefined
) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const response = action(url, init);
    if (response) return response;
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
  conversationStore.setState({
    messages: [],
    composerPrefill: null,
    streaming: true,
    backgroundRunning: true,
    streamingIndex: -1,
    queueItems: [item()],
    lastError: null,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("queue withdraw and true interject product contract", () => {
  it("队列默认展开并明确区分撤回编辑与立即插入", () => {
    installFetch(() => undefined);
    render(<ChatQueue />);
    expect(screen.getByTestId("chat-queue-list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "撤回编辑" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "立即插入" })).toBeInTheDocument();
    expect(screen.getByText(/当前任务结束后按序发送/)).toBeInTheDocument();
  });

  it("撤回成功恢复正文与附件且保留已有草稿", async () => {
    installFetch((url, init) => {
      if (url.endsWith("/api/v1/chat/queue") && init?.method === "DELETE") {
        return new Response(JSON.stringify({ ok: true, item: item() }), { status: 200 });
      }
      return undefined;
    });
    render(
      <>
        <ChatQueue />
        <Composer />
      </>
    );
    const input = screen.getByTestId("composer-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "已有草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "撤回编辑" }));
    await waitFor(() => expect(input.value).toBe("已有草稿\n排队正文"));
    expect(screen.getByText("queued.txt")).toBeInTheDocument();
    expect(screen.getByTestId("chat-queue-feedback")).toHaveTextContent("已撤回到输入框");
  });

  it("取消冲突把后端 detail 明确显示出来", async () => {
    installFetch((url, init) => {
      if (url.endsWith("/api/v1/chat/queue") && init?.method === "DELETE") {
        return new Response(
          JSON.stringify({ error: "queue_cancel_conflict", detail: "排队项已在发送中，无法撤回" }),
          { status: 409 }
        );
      }
      return undefined;
    });
    render(<ChatQueue />);
    fireEvent.click(screen.getByRole("button", { name: "撤回编辑" }));
    await waitFor(() =>
      expect(screen.getByTestId("chat-queue-feedback")).toHaveTextContent("排队项已在发送中，无法撤回")
    );
  });

  it("立即插入调用独立 handoff API，并显示后端 pending 状态", async () => {
    let body: Record<string, unknown> | null = null;
    installFetch((url, init) => {
      if (url.endsWith("/api/v1/chat/queue/interject") && init?.method === "POST") {
        body = JSON.parse(String(init.body ?? "{}"));
        return new Response(JSON.stringify({ ok: true, queue_id: "q1", state: "interject_pending" }), {
          status: 202,
        });
      }
      if (url.includes("/api/v1/chat/queue?")) {
        return new Response(JSON.stringify({ items: [item("interject_pending")] }), { status: 200 });
      }
      return undefined;
    });
    render(<ChatQueue />);
    fireEvent.click(screen.getByRole("button", { name: "立即插入" }));
    await waitFor(() => expect(body).toEqual({ session_id: "s1", queue_id: "q1" }));
    await waitFor(() => expect(screen.getByTestId("chat-queue-status")).toHaveTextContent("待接收"));
  });
});
