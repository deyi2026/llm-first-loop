// 复现用户事故（2026-09-22）：侧栏点击不同会话，主区显示不变化。
// 链路：Sidebar onClick -> sessionStore.setCurrentSession -> Conversation
// useEffect([currentId]) -> loadHistory -> /messages。本测试用真实 <App/> 壳
// 与按 session_id 区分内容的 mock 后端，断言点击后会话标题与消息都切换。

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup, act } from "@testing-library/react";
import { App } from "./App";
import { sessionStore } from "./core/stores";
import { conversationStore as conv } from "./core/conversation";

const SESS_A = "sess-alpha";
const SESS_B = "sess-beta";

async function renderAppSettled(): Promise<void> {
  await act(async () => {
    render(<App />);
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

const sessionMeta = (id: string, title: string) => ({
  session_id: id,
  title,
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-22T11:00:00Z",
  message_count: 2,
  status: "active",
  last_message_preview: `${title} preview`,
  pinned: false,
  channel: "web",
});

const messagesOf = (id: string) => ({
  session_id: id,
  total: 2,
  has_more: false,
  messages: [
    { role: "user", content: `${id} 的用户消息` },
    { role: "assistant", content: `${id} 的助手回答`, reasoning_content: null, model_used: "m", tokens_in: 1, tokens_out: 1, ts: 1 },
  ],
});

function mockBackend() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes(`/api/v1/sessions/${SESS_A}/messages`)) {
        return new Response(JSON.stringify(messagesOf(SESS_A)), { status: 200 });
      }
      if (url.includes(`/api/v1/sessions/${SESS_B}/messages`)) {
        return new Response(JSON.stringify(messagesOf(SESS_B)), { status: 200 });
      }
      if (url.startsWith("/api/v1/sessions?") || url.endsWith("/api/v1/sessions")) {
        return new Response(
          JSON.stringify({ sessions: [sessionMeta(SESS_A, "会话甲"), sessionMeta(SESS_B, "会话乙")], count: 2 }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/session/current")) {
        return new Response(JSON.stringify({ current: SESS_A }), { status: 200 });
      }
      if (url.includes("/api/v1/agents/tree")) {
        return new Response(JSON.stringify({ nodes: [] }), { status: 200 });
      }
      if (url.includes("/api/v1/workspaces")) {
        return new Response(JSON.stringify({ workspaces: [], current: null }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    })
  );
}

describe("侧栏会话切换", () => {
  beforeEach(() => {
    mockBackend();
    sessionStore.setSessions([]);
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(false);
    sessionStore.setModelChangePending(false);
    conv.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("点击另一会话后，主区标题与消息切换为新会话内容", async () => {
    await renderAppSettled();

    // 初始：shared current -> 会话甲加载
    await waitFor(() => {
      expect(screen.getByText(`${SESS_A} 的用户消息`)).toBeInTheDocument();
    });

    // 点击侧栏的会话乙条目
    fireEvent.click(screen.getByText("会话乙"));

    // 主区必须显示会话乙的消息（而不是停留在会话甲）
    await waitFor(() => {
      expect(screen.getByText(`${SESS_B} 的用户消息`)).toBeInTheDocument();
    });
    expect(screen.queryByText(`${SESS_A} 的用户消息`)).not.toBeInTheDocument();
    expect(sessionStore.getState().currentSessionId).toBe(SESS_B);
  });

  it("慢会话的历史请求被切换取消，不能阻塞后续会话或覆盖新视图", async () => {
    let slowAborted = false;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes(`/api/v1/sessions/${SESS_A}/messages`)) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            slowAborted = true;
            reject(new DOMException("aborted", "AbortError"));
          }, { once: true });
        });
      }
      if (url.includes(`/api/v1/sessions/${SESS_B}/messages`)) {
        return Promise.resolve(new Response(JSON.stringify(messagesOf(SESS_B)), { status: 200 }));
      }
      if (url.endsWith("/api/v1/sessions")) {
        return Promise.resolve(new Response(JSON.stringify({
          sessions: [sessionMeta(SESS_A, "会话甲"), sessionMeta(SESS_B, "会话乙")], count: 2,
        }), { status: 200 }));
      }
      if (url.endsWith("/api/v1/session/current")) {
        return Promise.resolve(new Response(JSON.stringify({ current: SESS_A }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    }));
    sessionStore.setSessions([sessionMeta(SESS_A, "会话甲"), sessionMeta(SESS_B, "会话乙")]);
    sessionStore.setCurrentSession(SESS_A);
    await renderAppSettled();
    expect(screen.getByTestId("history-loading")).toBeInTheDocument();
    fireEvent.click(screen.getByText("会话乙"));
    await waitFor(() => {
      expect(slowAborted).toBe(true);
      expect(screen.getByText(`${SESS_B} 的用户消息`)).toBeInTheDocument();
    });
    expect(screen.queryByText(`${SESS_A} 的用户消息`)).not.toBeInTheDocument();
    expect(sessionStore.getState().currentSessionId).toBe(SESS_B);
  });

  it("队列接力的 run_started 不得把用户已切走的视图拉回（点击会话无变化事故）", async () => {
    // 事故重放（2026-09-22）：fc0ed66c 队列有毒丸项 → 用户停在该会话时 relay 认领
    // 并发起 run；用户点击其他会话后 run_started 才到达 —— onRunStarted 的无条件
    // setCurrentSession 把视图拽回原会话，表现为"点击不同会话显示没变化"。
    const release = { fn: null as null | (() => void) };
    let dispatchCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/chat/stream")) {
          const enc = new TextEncoder();
          const body = JSON.parse(String(init?.body ?? "{}") || "{}");
          const isRelayRun = Boolean(body.queue_id);
          if (!isRelayRun) {
            return new Response(
              new ReadableStream({
                start(c) {
                  c.enqueue(enc.encode(`data: {"type":"done","data":{"session_id":"${SESS_A}"}}\n\n`));
                  c.close();
                },
              }),
              { status: 200 }
            );
          }
          // 接力 run：先不吐任何帧；测试放行后才发 run_started（模拟慢 admission）
          let streamCtrl: ReadableStreamDefaultController<Uint8Array> | null = null;
          release.fn = () => {
            streamCtrl?.enqueue(
              enc.encode(
                `data: {"type":"run_started","data":{"session_id":"${SESS_A}","run_generation":"g1"}}\n\n`
              )
            );
            streamCtrl?.enqueue(enc.encode(`data: {"type":"done","data":{"session_id":"${SESS_A}"}}\n\n`));
            streamCtrl?.close();
          };
          return new Response(
            new ReadableStream({
              start(c) {
                streamCtrl = c as unknown as ReadableStreamDefaultController<Uint8Array>;
              },
            }),
            { status: 200 }
          );
        }
        if (url.includes("/api/v1/chat/queue/dispatch")) {
          dispatchCount += 1;
          return new Response(
            JSON.stringify({
              claimed: { queue_id: "q_poison", session_id: SESS_A, status: "claimed", message: "resume" },
            }),
            { status: 200 }
          );
        }
        if (url.includes("/api/v1/chat/queue")) {
          return new Response(
            JSON.stringify({
              items: [{ queue_id: "q_poison", session_id: SESS_A, status: "queued", message: "resume" }],
              count: 1,
              queued: 1,
              claimed: 0,
            }),
            { status: 200 }
          );
        }
        if (url.includes(`/api/v1/sessions/${SESS_A}/messages`)) {
          return new Response(JSON.stringify(messagesOf(SESS_A)), { status: 200 });
        }
        if (url.includes(`/api/v1/sessions/${SESS_B}/messages`)) {
          return new Response(JSON.stringify(messagesOf(SESS_B)), { status: 200 });
        }
        if (url.startsWith("/api/v1/sessions?") || url.endsWith("/api/v1/sessions")) {
          return new Response(
            JSON.stringify({ sessions: [sessionMeta(SESS_A, "会话甲"), sessionMeta(SESS_B, "会话乙")], count: 2 }),
            { status: 200 }
          );
        }
        if (url.includes("/api/v1/session/current")) {
          return new Response(JSON.stringify({ current: SESS_A }), { status: 200 });
        }
        if (url.includes("/api/v1/agents/tree")) {
          return new Response(JSON.stringify({ nodes: [] }), { status: 200 });
        }
        if (url.includes("/api/v1/workspaces")) {
          return new Response(JSON.stringify({ workspaces: [], current: null }), { status: 200 });
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );

    sessionStore.setSessions([sessionMeta(SESS_A, "会话甲"), sessionMeta(SESS_B, "会话乙")]);
    sessionStore.setCurrentSession(SESS_A);
    await renderAppSettled();
    await waitFor(() => {
      expect(screen.getByText(`${SESS_A} 的用户消息`)).toBeInTheDocument();
    });
    // 等 relay 真正认领（claim 在途，run_started 未达）再模拟用户点击
    await waitFor(() => {
      expect(dispatchCount).toBeGreaterThan(0);
    });
    fireEvent.click(screen.getByText("会话乙"));
    await waitFor(() => {
      expect(screen.getByText(`${SESS_B} 的用户消息`)).toBeInTheDocument();
    });
    expect(sessionStore.getState().currentSessionId).toBe(SESS_B);

    // 接力 run 的 run_started 现在到达 —— 视图必须留在会话乙（不得拉回甲）
    await act(async () => {
      release.fn?.();
      await new Promise((r) => setTimeout(r, 120));
    });
    expect(sessionStore.getState().currentSessionId).toBe(SESS_B);
    expect(screen.getByText(`${SESS_B} 的用户消息`)).toBeInTheDocument();
  });

  it("新会话首条消息的 run_started 仍绑定服务端新 sid（防过度修复）", async () => {
    const NEW_SID = "sess-newly-created";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/chat/stream")) {
          const enc = new TextEncoder();
          const body = JSON.parse(String(init?.body ?? "{}") || "{}");
          if (body.new_session) {
            return new Response(
              new ReadableStream({
                start(c) {
                  c.enqueue(
                    enc.encode(
                      `data: {"type":"run_started","data":{"session_id":"${NEW_SID}","run_generation":"g9"}}\n\n`
                    )
                  );
                  c.enqueue(
                    enc.encode(`data: {"type":"done","data":{"session_id":"${NEW_SID}","final_answer":"好"}}\n\n`)
                  );
                  c.close();
                },
              }),
              { status: 200 }
            );
          }
          return new Response(JSON.stringify({}), { status: 200 });
        }
        if (url.includes(`/api/v1/sessions/${NEW_SID}/messages`)) {
          return new Response(JSON.stringify(messagesOf(NEW_SID)), { status: 200 });
        }
        if (url.startsWith("/api/v1/sessions?") || url.endsWith("/api/v1/sessions")) {
          return new Response(
            JSON.stringify({ sessions: [sessionMeta(NEW_SID, "新会话")], count: 1 }),
            { status: 200 }
          );
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );
    sessionStore.setSessions([sessionMeta(NEW_SID, "新会话")]);
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(true);
    await renderAppSettled();
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "第一条" } });
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => {
      expect(sessionStore.getState().currentSessionId).toBe(NEW_SID);
    });
    expect(sessionStore.getState().newSessionPending).toBe(false);
  });
});
