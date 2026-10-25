// P1-1 前端回归：relayNextQueued 不得把无 ref 的 realtime_visual_evidence fact
// 映射成 attachment_ref=undefined 的假附件；浏览器 payload 只回放真正上传过的附件
// （realtime 视觉证据由服务端冻结 facts 注入 run 输入，不经浏览器重建）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { conversationStore, relayNextQueued } from "../conversation";
import { sessionStore } from "../stores";
import type { QueueItem } from "../types";

const SESSION_ID = "sess-relay";

interface RecordedStreamCall {
  body: Record<string, unknown>;
}

function makeClaimed(attachmentFacts: Record<string, unknown>[]): QueueItem {
  return {
    queue_id: "q_relay1",
    session_id: SESSION_ID,
    message: "看当前画面哪里报错",
    attachments: [],
    model: null,
    reasoning_effort: null,
    reasoning_mode: "auto",
    attachment_facts: attachmentFacts as unknown as QueueItem["attachment_facts"],
    status: "claimed",
    created_at: 1,
    claimed_at: 2,
  };
}

const UPLOAD_FACT = {
  ref: "attachment://uploads/abc123",
  filename: "log.txt",
  content_type: "text/plain",
  size_bytes: 12,
  sha256: "0".repeat(64),
};

const REALTIME_FACT = {
  kind: "realtime_visual_evidence",
  media_session_id: "ms-1",
  turn_id: "turn-1-1",
  evidence_refs: ["artifact://v1/" + "a".repeat(32)],
  frames: [],
};

function makeFetch(claimed: QueueItem | null) {
  const streamCalls: RecordedStreamCall[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/v1/chat/queue/dispatch")) {
      return { ok: true, json: async () => ({ claimed }) };
    }
    if (url.includes("/api/v1/chat/queue")) {
      return { ok: true, json: async () => ({ items: claimed ? [claimed] : [] }) };
    }
    if (url.includes("/api/v1/chat/stream")) {
      streamCalls.push({ body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      return { ok: false, status: 500, text: async () => "server boom" };
    }
    return { ok: true, json: async () => ({}) };
  });
  return { fetchImpl, streamCalls };
}

describe("relayNextQueued P1-1：realtime facts 不进浏览器 attachments", () => {
  beforeEach(() => {
    conversationStore.setState({
      messages: [],
      streaming: false,
      streamingIndex: -1,
      lastError: null,
      streamStartedAt: null,
      backgroundRunning: false,
      activeRunGeneration: null,
      queueItems: [],
    });
    sessionStore.setCurrentSession(SESSION_ID);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends only ref-backed upload facts; the realtime fact is not rebuilt client-side", async () => {
    const claimed = makeClaimed([UPLOAD_FACT, REALTIME_FACT]);
    const { fetchImpl, streamCalls } = makeFetch(claimed);
    vi.stubGlobal("fetch", fetchImpl);
    conversationStore.setState({ queueItems: [{ ...claimed, status: "queued" }] as never });

    await relayNextQueued(SESSION_ID);
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0);
    });

    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0].body.queue_id).toBe("q_relay1");
    expect(streamCalls[0].body.attachments).toEqual([{ ref: UPLOAD_FACT.ref }]);
    const payload = JSON.stringify(streamCalls[0].body);
    expect(payload).not.toContain("realtime_visual_evidence");
    expect(payload).not.toContain("undefined");
  });

  it("realtime-only queue item sends an empty attachments array (server injects frozen facts)", async () => {
    const claimed = makeClaimed([REALTIME_FACT]);
    const { fetchImpl, streamCalls } = makeFetch(claimed);
    vi.stubGlobal("fetch", fetchImpl);
    conversationStore.setState({ queueItems: [{ ...claimed, status: "queued" }] as never });

    await relayNextQueued(SESSION_ID);
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0);
    });

    expect(streamCalls).toHaveLength(1);
    expect(streamCalls[0].body.attachments).toEqual([]);
    expect(streamCalls[0].body.message).toBe("看当前画面哪里报错");
    expect(streamCalls[0].body.queue_id).toBe("q_relay1");
  });
});
