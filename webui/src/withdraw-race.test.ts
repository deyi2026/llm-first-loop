// 撤回竞态回归（r5）：withdrawQueueTurn 的 cancelQueueItem 返回前用户切走会话时，
// 撤回内容进入 deferredWithdrawals[原会话]；切回原会话时消费必须与实际应用 prefill
// 严格同步：
// - reset 分支（视图重建）：prefill 应用后删除条目；
// - 保留视图分支（前台 run 跟随 / resume 接管，store 不重建）：把草稿并入现有
//   prefill 后删除——r4 的无条件 delete 会在不应用的情况下吞掉撤回内容。
//
// 保留视图分支经真实公开路径构造：sendMessage（无会话态）→ onRunStarted 机械绑定
// 先设 abortSessionId=sid 再 setCurrentSession(sid)，订阅者据此走保留视图分支。
// resumeFollows 变体与该分支共享同一 else-if 代码路径，未单独构造（见交付报告边界）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  conversationStore as conv,
  sendMessage,
  withdrawQueueTurn,
} from "./core/conversation";
import { sessionStore } from "./core/stores";

const SESS_A = "sess-withdraw-a";
const SESS_B = "sess-withdraw-b";

const withdrawnFact = { ref: "ref-note-1", filename: "note.txt" };
const withdrawnPrefill = {
  text: "被撤回的排队草稿",
  attachments: [withdrawnFact],
};

function resetStores(): void {
  sessionStore.setSessions([]);
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
  sessionStore.setModelChangePending(false);
  conv.setState({
    messages: [],
    composerPrefill: null,
    hasMoreHistory: false,
    loadedHistoryCount: 0,
    streaming: false,
    backgroundRunning: false,
    activeRunGeneration: null,
    streamingIndex: -1,
    lastError: null,
    streamStartedAt: null,
    queueItems: [],
  });
}

/** mock 后端：撤回取消请求被门控，测试在放行前先切换会话（制造竞态窗口）。 */
function installBackend(): { resolveCancel: () => void } {
  let resolveCancel!: () => void;
  const cancelGate = new Promise<Response>((resolve) => {
    resolveCancel = () =>
      resolve(
        new Response(
          JSON.stringify({
            ok: true,
            status: 200,
            item: {
              queue_id: "q1",
              session_id: SESS_A,
              status: "queued",
              message: "被撤回的排队草稿",
              attachment_facts: [withdrawnFact],
            },
          }),
          { status: 200 }
        )
      );
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/v1/chat/queue") && init?.method === "DELETE") {
        return cancelGate;
      }
      if (url.includes("/api/v1/chat/queue")) {
        return new Response(
          JSON.stringify({ items: [], count: 0, queued: 0, claimed: 0 }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/chat/stream") && init?.method === "POST") {
        // 无会话态首条消息的 run：run_started 把流 owner 机械绑定到 SESS_A
        // （模块对 sessionId=null 的发送接受服务端返回的 sid 并发布 setCurrentSession）。
        // 流保持打开：run 仍在途，不触发终态/断流续联路径。
        return new Response(
          new ReadableStream<Uint8Array>({
            start(c) {
              const enc = new TextEncoder();
              c.enqueue(
                enc.encode(
                  `data: {"type":"run_started","data":{"session_id":"${SESS_A}","run_generation":"g1"}}\n\n`
                )
              );
            },
          }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    })
  );
  return { resolveCancel };
}

describe("withdrawQueueTurn 撤回草稿的会话切换竞态", () => {
  beforeEach(() => {
    resetStores();
  });
  afterEach(() => {
    // 切回空会话触发 detach，解除本测试遗留的流订阅后再卸载 fetch stub
    sessionStore.setCurrentSession("");
    vi.unstubAllGlobals();
  });

  it("reset 分支：切回时应用撤回草稿，且只应用一次、不残留", async () => {
    const { resolveCancel } = installBackend();
    sessionStore.setCurrentSession(SESS_A);
    const pending = withdrawQueueTurn("q1");
    sessionStore.setCurrentSession(SESS_B); // cancel 返回前切走 → 内容进入 deferred
    resolveCancel();
    await pending;
    // 切走期间不得直接写入当前视图
    expect(conv.getState().composerPrefill).toBeNull();

    sessionStore.setCurrentSession(SESS_A); // 切回：reset 分支应用撤回草稿
    expect(conv.getState().composerPrefill).toEqual(withdrawnPrefill);

    // 再切走再切回：条目已消费，不得第二次应用（deferredWithdrawals 无残留）
    sessionStore.setCurrentSession(SESS_B);
    sessionStore.setCurrentSession(SESS_A);
    expect(conv.getState().composerPrefill).toBeNull();
  });

  it("保留视图分支（run_started 机械绑定）：切回时并入 prefill，撤回内容不丢失", async () => {
    const { resolveCancel } = installBackend();
    sessionStore.setCurrentSession(SESS_A);
    const pending = withdrawQueueTurn("q1");
    sessionStore.setCurrentSession(""); // cancel 返回前切到“新会话待建”
    resolveCancel();
    await pending;
    expect(conv.getState().composerPrefill).toBeNull();

    // 无会话态发送首条消息：onRunStarted 先设 abortSessionId=SESS_A 再机械发布
    // setCurrentSession(SESS_A) —— 订阅者走保留视图分支（store 不重建）。
    void sendMessage("新会话首条", []).catch(() => undefined);
    await vi.waitFor(() => {
      expect(sessionStore.getState().currentSessionId).toBe(SESS_A);
    });
    // 保留视图分支证据：乐观 user/assistant 消息未被 reset 清空
    expect(conv.getState().messages.length).toBe(2);
    // 撤回草稿必须并入 prefill（r4：条目被无条件 delete，内容丢失）
    expect(conv.getState().composerPrefill).toEqual(withdrawnPrefill);

    // 条目已消费：再切走切回不重复应用（deferredWithdrawals 无残留）
    sessionStore.setCurrentSession(SESS_B);
    sessionStore.setCurrentSession(SESS_A);
    expect(conv.getState().composerPrefill).toBeNull();
  });
});
