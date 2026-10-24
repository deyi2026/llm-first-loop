import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { conversationStore } from "../conversation";
import type { AudioBufferSourceLike, AudioContextLike } from "./audioPlayback";
import type { SocketLike } from "./mediaSessionClient";
import { resetShareSourceLedgerForTests } from "./visualShare";
import { useRealtimeVoice, type RealtimeVoiceTransport } from "./useRealtimeVoice";
import type { ChatMessage } from "../types";

class FakeSocket implements SocketLike {
  readonly sent: (string | ArrayBuffer)[] = [];
  closedWith: number | null = null;
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }

  close(code?: number): void {
    this.closedWith = code ?? null;
  }

  sentTextEvents(): Record<string, unknown>[] {
    return this.sent
      .filter((item): item is string => typeof item === "string")
      .map((raw) => JSON.parse(raw) as Record<string, unknown>);
  }
}

class FakeSource implements AudioBufferSourceLike {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  started = false;
  stopped = false;
  connect(): void {}
  start(): void {
    this.started = true;
  }
  stop(): void {
    this.stopped = true;
  }
}

class FakeAudioContext implements AudioContextLike {
  destination = {};
  /** P2：dispose() 关闭计数（teardown 不泄漏 AudioContext 的断言依据）。 */
  closeCount = 0;
  readonly sources: FakeSource[] = [];
  readonly decoded: ArrayBuffer[] = [];
  async decodeAudioData(data: ArrayBuffer): Promise<unknown> {
    this.decoded.push(data);
    return { decoded: true };
  }
  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
  close(): Promise<void> {
    this.closeCount += 1;
    return Promise.resolve();
  }
}

function makeEnv() {
  const sockets: FakeSocket[] = [];
  const contexts: FakeAudioContext[] = [];
  const fetchImpl = vi.fn(async () => ({ ok: true, json: async () => ({ media_session_id: "ms-1" }) }));
  const committed = vi.fn();
  const notices = vi.fn();
  const transport = {
    fetchImpl: fetchImpl as unknown as typeof fetch,
    createSocket: (url: string) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    createAudioContext: () => {
      const context = new FakeAudioContext();
      contexts.push(context);
      return context;
    },
  };
  const render = () =>
    renderHook(() =>
      useRealtimeVoice({ sessionId: "sess-1", onCommittedTranscript: committed, onNotice: notices, transport }),
    );
  return { sockets, contexts, fetchImpl, committed, notices, transport, render };
}

const serverEvent = (over: Record<string, unknown>): string =>
  JSON.stringify({
    version: 1,
    type: "turn.committed",
    event_id: "e1",
    seq: 1,
    connection_epoch: 1,
    session_id: "sess-1",
    media_session_id: "ms-1",
    ...over,
  });

/** M1/M3 两种测试环境共用的最小结构（render 返回带类型的 hook 结果）。 */
type EnableAndOpenEnv = {
  render: () => { result: { current: ReturnType<typeof useRealtimeVoice> }; unmount: () => void };
  sockets: FakeSocket[];
};

async function enableAndOpen(env: EnableAndOpenEnv) {
  const view = env.render();
  await act(async () => {
    await view.result.current.enable();
  });
  expect(view.result.current.connectionState).toBe("opening");
  act(() => {
    env.sockets[0].onopen?.();
  });
  expect(view.result.current.connectionState).toBe("ready");
  return view;
}

function assistantMessage(content: string, ts = 123.45): ChatMessage {
  return { role: "assistant", content, ts };
}

describe("useRealtimeVoice M1 客户端闭环", () => {
  beforeEach(() => {
    conversationStore.setState({
      messages: [],
      streaming: false,
      streamingIndex: -1,
      lastError: null,
      streamStartedAt: null,
      backgroundRunning: false,
      activeRunGeneration: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("connects via the same-origin control channel after creating a media session", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    expect(env.fetchImpl).toHaveBeenCalledWith(
      "/api/v1/realtime/sessions",
      expect.objectContaining({ method: "POST" }),
    );
    expect(env.sockets[0].url).toBe(
      `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/api/v1/realtime/sessions/ms-1/events`,
    );
    act(() => {
      view.result.current.disable();
    });
  });

  it("submits the committed transcript exactly once per turn (dedup by turn_id)", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "input.final", turn_id: "t1", text: "你好，世界" }) });
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "t1", text: "你好，世界" }) });
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "t1", text: "你好，世界" }) });
    });
    expect(env.committed).toHaveBeenCalledTimes(1);
    expect(env.committed).toHaveBeenCalledWith("你好，世界", "t1");
    act(() => {
      view.result.current.disable();
    });
  });

  it("notifies instead of submitting an empty transcript", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "input.final", turn_id: "t2", text: "" }) });
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "t2", text: "" }) });
    });
    expect(env.committed).not.toHaveBeenCalled();
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("终稿为空"));
    act(() => {
      view.result.current.disable();
    });
  });

  it("requests tts.request once for a voice-originated reply and plays the PCM16 binary", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    // 语音终稿提交（上层回调触发 sendMessage：这里由测试直接模拟 streaming 状态）
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "t1", text: "看下天气" }) });
    });
    expect(env.committed).toHaveBeenCalledTimes(1);
    // 回复 run：streaming true → false，最后一条 assistant 消息即终稿回复
    act(() => {
      conversationStore.setState({ streaming: true });
    });
    act(() => {
      conversationStore.setState({ streaming: false, messages: [assistantMessage("今天晴，25 度")] });
    });
    const tts = env.sockets[0].sentTextEvents().filter((event) => event.type === "tts.request");
    expect(tts).toHaveLength(1);
    expect(tts[0]).toMatchObject({ text: "今天晴，25 度", response_id: "123.45:8" });
    // 同一回复的重复 streaming 收敛不重复请求
    act(() => {
      conversationStore.setState({ streaming: true });
    });
    act(() => {
      conversationStore.setState({ streaming: false, messages: [assistantMessage("今天晴，25 度")] });
    });
    expect(env.sockets[0].sentTextEvents().filter((event) => event.type === "tts.request")).toHaveLength(1);
    // 下行二进制（无头 PCM16）→ 本地播放（WAV 包装后 decode）
    await act(async () => {
      env.sockets[0].onmessage?.({ data: new Int16Array(160).buffer });
      await Promise.resolve();
    });
    expect(env.contexts[0].sources.length).toBeGreaterThan(0);
    expect(env.contexts[0].sources.every((source) => source.started)).toBe(true);
    const header = new Uint8Array(env.contexts[0].decoded[0].slice(0, 4));
    expect(String.fromCharCode(...header)).toBe("RIFF");
    act(() => {
      view.result.current.disable();
    });
  });

  it("never sends tts.request for text-originated replies while realtime is enabled", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      conversationStore.setState({ streaming: true });
    });
    act(() => {
      conversationStore.setState({ streaming: false, messages: [assistantMessage("手打字的回复")] });
    });
    expect(env.sockets[0].sentTextEvents().filter((event) => event.type === "tts.request")).toHaveLength(0);
    act(() => {
      view.result.current.disable();
    });
  });

  it("does nothing to the text path when realtime is disabled (zero interaction change)", async () => {
    const env = makeEnv();
    const view = env.render();
    expect(view.result.current.enabled).toBe(false);
    act(() => {
      conversationStore.setState({ streaming: true });
    });
    act(() => {
      conversationStore.setState({ streaming: false, messages: [assistantMessage("纯文本回复")] });
    });
    expect(env.fetchImpl).not.toHaveBeenCalled();
    expect(env.sockets).toHaveLength(0);
    view.unmount();
  });

  it("ignores late committed events after disable", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      view.result.current.disable();
    });
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "t9", text: "迟到事件" }) });
    });
    expect(env.committed).not.toHaveBeenCalled();
    expect(env.sockets[0].closedWith).toBe(1000);
  });

  it("closes the control channel on unmount (local stop, no server wait)", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    view.unmount();
    expect(env.sockets[0].closedWith).toBe(1000);
  });

  it("surfaces session creation failure via a visible notice and stays disabled", async () => {
    const env = makeEnv();
    (env.fetchImpl as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, json: async () => ({}) });
    const view = env.render();
    await act(async () => {
      await view.result.current.enable();
    });
    expect(view.result.current.enabled).toBe(false);
    expect(view.result.current.connectionState).toBe("failed");
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("实时语音会话建立失败"));
    expect(env.sockets).toHaveLength(0);
  });

  // ---- P1-2：会话生命周期接线 -------------------------------------------

  it("retries exactly once with take_over:true when POST returns 409", async () => {
    const env = makeEnv();
    const calls: { body: string }[] = [];
    const responses = [
      { ok: false, status: 409, json: async () => ({ detail: "active writer" }) },
      { ok: true, json: async () => ({ media_session_id: "ms-1" }) },
    ];
    (env.fetchImpl as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (_input: string, init?: { body?: string }) => {
        if (init?.body !== undefined) calls.push({ body: init.body });
        return responses.shift();
      },
    );
    const view = env.render();
    await act(async () => {
      await view.result.current.enable();
    });
    expect(view.result.current.enabled).toBe(true);
    expect(env.sockets).toHaveLength(1);
    // 两次 POST：第一次常规，第二次（仅一次重试）带 take_over:true
    expect(calls).toHaveLength(2);
    expect(JSON.parse(calls[0].body)).toMatchObject({ session_id: "sess-1", take_over: false });
    expect(JSON.parse(calls[1].body)).toMatchObject({ session_id: "sess-1", take_over: true });
    act(() => {
      view.result.current.disable();
    });
  });

  it("gives up visibly after one failed take_over retry (no infinite retries)", async () => {
    const env = makeEnv();
    const responses = [
      { ok: false, status: 409, json: async () => ({}) },
      { ok: false, status: 503, json: async () => ({}) },
    ];
    (env.fetchImpl as unknown as ReturnType<typeof vi.fn>).mockImplementation(async () => responses.shift());
    const view = env.render();
    await act(async () => {
      await view.result.current.enable();
    });
    expect(view.result.current.enabled).toBe(false);
    expect(view.result.current.connectionState).toBe("failed");
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("实时语音会话建立失败"));
    expect(env.fetchImpl).toHaveBeenCalledTimes(2); // 仅一次重试，不再第三发
    expect(env.sockets).toHaveLength(0);
  });

  it("disable fires a fire-and-forget keepalive DELETE of the media session", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      view.result.current.disable();
    });
    expect(env.fetchImpl).toHaveBeenCalledWith("/api/v1/realtime/sessions/ms-1", {
      method: "DELETE",
      keepalive: true,
    });
    expect(view.result.current.enabled).toBe(false);
  });

  it("disable stays non-blocking when the DELETE fails (UI still disabled)", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    (env.fetchImpl as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("network down"));
    expect(() => {
      act(() => {
        view.result.current.disable();
      });
    }).not.toThrow();
    expect(view.result.current.enabled).toBe(false);
    expect(view.result.current.connectionState).toBe("closed");
  });

  it("unmount also fires the keepalive DELETE (server session reclaimed)", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    view.unmount();
    await act(async () => {
      await Promise.resolve();
    });
    expect(env.fetchImpl).toHaveBeenCalledWith("/api/v1/realtime/sessions/ms-1", {
      method: "DELETE",
      keepalive: true,
    });
  });

  // ---- P2：AudioContext 生命周期（teardown 关闭；重复 enable 不泄漏） ------------------

  it("P2: teardown disposes the AudioContext (disable + unmount); a fresh enable stays usable", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    expect(env.contexts).toHaveLength(1);
    act(() => {
      view.result.current.disable();
    });
    expect(env.contexts[0].closeCount).toBe(1); // 旧 context 已关闭（不泄漏）
    // 重新 enable：新 AudioContext 正常工作（播放链路可用，未被误关）
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[1].onopen?.();
    });
    expect(view.result.current.connectionState).toBe("ready");
    await act(async () => {
      env.sockets[1].onmessage?.({ data: new Int16Array(160).buffer });
      await Promise.resolve();
    });
    expect(env.contexts[1].closeCount).toBe(0); // 新 context 未被 teardown 误伤
    expect(env.contexts[1].sources.length).toBeGreaterThan(0); // 新 enable 仍可播放
    view.unmount();
    expect(env.contexts[1].closeCount).toBe(1); // 卸载同样关闭
  });

  // ---- P3：enable 失败路径回收已创建的媒体会话（不漏 DELETE） -----------------------

  it("P3: an enable failure after the media session id is known reclaims it (DELETE) and clears the ref", async () => {
    const env = makeEnv();
    const calls: { url: unknown; init?: { method?: string } }[] = [];
    let mediaSessionId = "ms-1";
    const fetchImpl = vi.fn(async (input: unknown, init?: { method?: string }) => {
      calls.push({ url: input, init });
      if (init?.method === "DELETE") return { ok: true } as never;
      return { ok: true, json: async () => ({ media_session_id: mediaSessionId }) } as never;
    });
    env.transport.fetchImpl = fetchImpl as unknown as typeof fetch;
    // 拿到 media_session_id 之后、完成装配之前抛错（注入 createAudioContext 失败）
    (env.transport as RealtimeVoiceTransport).createAudioContext = () => {
      throw new Error("no audio context");
    };
    const view = env.render();
    let enabled = true;
    await act(async () => {
      enabled = await view.result.current.enable();
    });
    expect(enabled).toBe(false);
    expect(view.result.current.connectionState).toBe("failed");
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("实时语音初始化失败")); // 既有提示不变
    // 已创建的媒体会话被尽力回收（fire-and-forget DELETE，而非等下次 enable 覆盖漏删）
    expect(calls.some((call) => call.url === "/api/v1/realtime/sessions/ms-1" && call.init?.method === "DELETE")).toBe(true);
    // ref 已清空：恢复注入后再次 enable 成功，disable 只回收新会话（旧 id 不残留、不重复 DELETE）
    (env.transport as RealtimeVoiceTransport).createAudioContext = () => {
      const context = new FakeAudioContext();
      env.contexts.push(context);
      return context;
    };
    mediaSessionId = "ms-2";
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    act(() => {
      view.result.current.disable();
    });
    expect(calls.filter((call) => call.init?.method === "DELETE").map((call) => call.url)).toEqual([
      "/api/v1/realtime/sessions/ms-1",
      "/api/v1/realtime/sessions/ms-2",
    ]);
  });

  it("P3: an enable failure while parsing the response body fails gracefully (unknown id → no fabricated DELETE)", async () => {
    const env = makeEnv();
    (env.fetchImpl as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async () => ({ ok: true, json: async () => { throw new Error("bad body"); } }),
    );
    const view = env.render();
    let enabled = true;
    await act(async () => {
      enabled = await view.result.current.enable();
    });
    expect(enabled).toBe(false);
    expect(view.result.current.connectionState).toBe("failed");
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("实时语音初始化失败"));
    // media_session_id 在响应体内：解析失败即不可知（ref 为 null）——不得伪造 DELETE
    expect(env.fetchImpl).toHaveBeenCalledTimes(1);
    view.unmount();
    await act(async () => {
      await Promise.resolve();
    });
    expect(env.fetchImpl).toHaveBeenCalledTimes(1); // 卸载也无补发（无 id 可删）
  });

  // ---- P2-9b：sessionId 响应式（来自 options；会话切换后 POST/DELETE 跟随） ---------

  it("P2-9b: POST body session_id follows the session switch (reactive options, no stale snapshot)", async () => {
    const env = makeEnv();
    const mediaIds = ["ms-1", "ms-2"];
    const calls: { url: unknown; init?: { method?: string; body?: string } }[] = [];
    const fetchImpl = vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      calls.push({ url: input, init });
      if (init?.method === "DELETE") return { ok: true } as never;
      return { ok: true, json: async () => ({ media_session_id: mediaIds.shift() ?? "ms-x" }) } as never;
    });
    env.transport.fetchImpl = fetchImpl as unknown as typeof fetch;
    let sessionId: string | null = "sess-A";
    const view = renderHook(() =>
      useRealtimeVoice({ sessionId, onNotice: env.notices, transport: env.transport }),
    );
    // 会话 A：enable → POST(sess-A) → disable → DELETE(ms-1)
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    act(() => {
      view.result.current.disable();
    });
    // 切换到会话 B（store 订阅触发上层重渲染 → options.sessionId 更新）
    sessionId = "sess-B";
    act(() => {
      view.rerender();
    });
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[1].onopen?.();
    });
    act(() => {
      view.result.current.disable();
    });
    const posts = calls.filter((call) => call.init?.method !== "DELETE");
    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[0].init?.body ?? "{}")).toMatchObject({ session_id: "sess-A" });
    expect(JSON.parse(posts[1].init?.body ?? "{}")).toMatchObject({ session_id: "sess-B" }); // 响应式断言
    // DELETE 按各自媒体会话回收（第一次 ms-1、第二次 ms-2）
    expect(calls.filter((call) => call.init?.method === "DELETE").map((call) => call.url)).toEqual([
      "/api/v1/realtime/sessions/ms-1",
      "/api/v1/realtime/sessions/ms-2",
    ]);
  });

  it("P2-9b: without a session, enable POSTs a per-enable adhoc id (never the fabricated 'local')", async () => {
    const env = makeEnv();
    const bodies: string[] = [];
    (env.fetchImpl as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (_input: string, init?: { body?: string }) => {
        if (init?.body !== undefined) bodies.push(init.body);
        return { ok: true, json: async () => ({ media_session_id: "ms-1" }) };
      },
    );
    const view = renderHook(() =>
      useRealtimeVoice({ sessionId: null, onNotice: env.notices, transport: env.transport }),
    );
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    expect(view.result.current.enabled).toBe(true);
    expect(bodies).toHaveLength(1);
    const posted = JSON.parse(bodies[0]) as { session_id: string };
    expect(posted.session_id).toMatch(/^realtime-adhoc-/); // 一次性临时 id
    expect(posted.session_id).not.toBe("local"); // 不再伪造共享常量
    act(() => {
      view.result.current.disable();
    });
  });

  // ---- P2-11：坏信封丢弃的有界可见提示（复用 onNotice 通道） -------------------------

  it("P2-11: malformed downstream frames surface exactly one bounded notice per connection", async () => {
    const env = makeEnv();
    const view = await enableAndOpen(env);
    act(() => {
      env.sockets[0].onmessage?.({ data: "not-json{" });
      env.sockets[0].onmessage?.({ data: JSON.stringify({ version: 2 }) });
      env.sockets[0].onmessage?.({ data: '{"version":1,"type":"media.closed"}' });
    });
    const protocolNotices = env.notices.mock.calls.filter(([message]) =>
      String(message).includes("无法解析"),
    );
    expect(protocolNotices).toHaveLength(1); // 连续多条坏帧只提示一次（不刷屏）
    expect(env.committed).not.toHaveBeenCalled(); // 坏帧不触发终稿提交
    act(() => {
      view.result.current.disable();
    });
  });
});

// ---------------------------------------------------------------------------
// M3：视觉共享接线（fake getDisplayMedia/grabber/port + fake timers）
// ---------------------------------------------------------------------------

class EndedCapableFakeTrack {
  stopped = false;
  private readonly listeners: (() => void)[] = [];
  stop(): void {
    this.stopped = true;
  }
  addEventListener(_type: string, listener: () => void): void {
    this.listeners.push(listener);
  }
  removeEventListener(_type: string, listener: () => void): void {
    const index = this.listeners.indexOf(listener);
    if (index !== -1) this.listeners.splice(index, 1);
  }
  fireEnded(): void {
    for (const listener of [...this.listeners]) listener();
  }
}

class FakeDisplayStreamForHook {
  constructor(readonly track: EndedCapableFakeTrack) {}
  getVideoTracks(): EndedCapableFakeTrack[] {
    return [this.track];
  }
  getTracks(): EndedCapableFakeTrack[] {
    return [this.track];
  }
}

function makeVisualEnv(over: { frames?: string[] } = {}) {
  const track = new EndedCapableFakeTrack();
  const frames = [...(over.frames ?? ["QUFB", "QkJC", "Q0ND"])];
  const grabs = { count: 0, closed: 0 };
  const ports: {
    onmessage: ((event: { data: { samples: Float32Array; sampleRate: number } }) => void) | null;
    close(): void;
  }[] = [];
  const desktopUa = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";
  const supportEnv = {
    getDisplayMedia: () => undefined,
    userAgent: desktopUa,
    matchMedia: (query: string) => ({ matches: query === "(pointer: fine)" }),
  };
  const env = makeEnv();
  const transport = env.transport as RealtimeVoiceTransport;
  transport.getDisplayMedia = async () => new FakeDisplayStreamForHook(track);
  transport.createGrabber = () => ({
    grab: async () => {
      grabs.count += 1;
      const b64 = frames.length > 0 ? frames.shift() ?? null : null;
      return b64 === null ? null : { dataB64: b64, width: 320, height: 240, mime: "image/jpeg" as const };
    },
    close: () => {
      grabs.closed += 1;
    },
  });
  transport.createPort = () => {
    const port = {
      onmessage: null as ((event: { data: { samples: Float32Array; sampleRate: number } }) => void) | null,
      close: () => undefined,
    };
    ports.push(port);
    return port;
  };
  const render = (options?: { supportEnv?: object; sessionId?: string | null }) =>
    renderHook(() =>
      useRealtimeVoice({
        // 注意：显式 null（无会话）不能被 ?? 回退成默认会话
        sessionId: options?.sessionId === undefined ? "sess-1" : options.sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport,
        visual: { supportEnv: (options?.supportEnv ?? supportEnv) as never },
      }),
    );
  return { ...env, transport, track, ports, grabs, render, supportEnv };
}

const desktopMediaDevices = {
  getUserMedia: async () => ({ getTracks: () => [] }),
};

describe("useRealtimeVoice M3 视觉接线", () => {
  beforeEach(() => {
    conversationStore.setState({
      messages: [],
      streaming: false,
      streamingIndex: -1,
      lastError: null,
      streamStartedAt: null,
      backgroundRunning: false,
      activeRunGeneration: null,
    });
    Object.defineProperty(navigator, "mediaDevices", { value: desktopMediaDevices, configurable: true });
    // P2-9c：source_id/epoch 是模块级台账（页面生命周期语义）——逐测试重置，
    // 使各测试（含既有 epoch===1 断言）与执行顺序解耦（同 m3Wiring.test.ts）。
    resetShareSourceLedgerForTests();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("reports unsupported when getDisplayMedia is absent (entry hidden by UI)", () => {
    const env = makeVisualEnv();
    const view = env.render({
      supportEnv: { getDisplayMedia: undefined, userAgent: "Mozilla/5.0 (Macintosh)", matchMedia: () => ({ matches: true }) },
    });
    expect(view.result.current.visual.supported).toBe(false);
    view.unmount();
  });

  // ---- P2-9b：无会话 → 禁止启动视觉共享（不伪造会话 id 入队） ------------------------

  it("P2-9b: without a session, startShare refuses visibly and never sends visual.share.start", async () => {
    const env = makeVisualEnv();
    const view = env.render({ sessionId: null });
    expect(view.result.current.visual.canShare).toBe(false); // UI 据此禁用入口并提示
    let enabled = false;
    await act(async () => {
      enabled = await view.result.current.enable();
    });
    expect(enabled).toBe(true); // 语音链路不受影响（临时 id 建媒体会话）
    act(() => {
      env.sockets[0].onopen?.();
    });
    let started = true;
    await act(async () => {
      started = await view.result.current.startShare();
    });
    expect(started).toBe(false); // 无会话：拒绝启动
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("还没有打开的会话"));
    // 不上送任何视觉事件；共享状态保持 idle（帧/任务无会话可归属）
    expect(env.sockets[0].sentTextEvents().some((event) => event.type === "visual.share.start")).toBe(false);
    expect(view.result.current.visual.phase).toBe("idle");
    act(() => {
      view.result.current.disable();
    });
  });

  it("P2-9b: a session appearing after rerender alone does not unlock sharing (options stay reactive)", async () => {
    const env = makeVisualEnv();
    let sessionId: string | null = null;
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    expect(view.result.current.visual.canShare).toBe(false);
    sessionId = "sess-42"; // 会话由首条消息/选择产生 → 上层重渲染传入
    act(() => {
      view.rerender();
    });
    // P2-9c：仅有会话不够——尚未 enable，没有与当前会话一致的媒体会话 identity，
    // 共享入口保持禁用（正例：enable 且 identity 一致 → 见下方 P2-9c 控制组）。
    expect(view.result.current.visual.canShare).toBe(false);
    view.unmount();
  });

  // ---- P2-9c：媒体会话 identity 冻结于 enable——跨会话共享一律拒绝/立即停止 ------

  it("P2-9c: adhoc enable then a session appears → canShare stays false; startShare refuses (no visual.share.start)", async () => {
    const env = makeVisualEnv();
    let sessionId: string | null = null;
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    await act(async () => {
      await view.result.current.enable(); // 无会话 → adhoc 临时 id 建媒体会话（语音可用）
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    expect(view.result.current.enabled).toBe(true);
    sessionId = "sess-B"; // 发送首条文本后会话 B 出现 → 上层重渲染传入
    act(() => {
      view.rerender();
    });
    expect(view.result.current.visual.canShare).toBe(false); // identity 是 adhoc id ≠ sess-B
    let started = true;
    await act(async () => {
      started = await view.result.current.startShare();
    });
    expect(started).toBe(false); // 帧/提交若发出会错投 adhoc 会话或被服务端 409 拒收
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("重新开启实时语音"));
    expect(env.sockets[0].sentTextEvents().some((event) => event.type === "visual.share.start")).toBe(false);
    expect(view.result.current.visual.phase).toBe("idle");
    act(() => {
      view.result.current.disable();
    });
  });

  it("P2-9c: a session switch mid-share stops sharing immediately; the next commit carries no visual", async () => {
    const env = makeVisualEnv();
    let sessionId: string | null = "sess-A";
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    await act(async () => {
      await view.result.current.enable(); // identity 冻结为 sess-A
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    expect(starts).toHaveLength(1);
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    expect(view.result.current.visual.phase).toBe("sharing");
    // 切到会话 B：正在共享 → 立即停止（丢弃，不做跨会话续传）并提示一次
    sessionId = "sess-B";
    act(() => {
      view.rerender();
    });
    const stops = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.stop");
    expect(stops).toHaveLength(1);
    expect(stops[0]).toMatchObject({ source_id: starts[0].source_id, source_epoch: starts[0].source_epoch });
    expect(env.track.stopped).toBe(true); // 本地轨道同步停止
    expect(view.result.current.visual.phase).toBe("stopped");
    expect(env.notices).toHaveBeenCalledWith("会话已切换，已停止画面共享");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000); // 停止后绝不再上送帧
    });
    expect(env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.frame")).toHaveLength(0);
    // 随后的语音提交不带 visual（identity 仍是 A，不跨会话续传视觉指代）
    await act(async () => {
      await view.result.current.press();
    });
    act(() => {
      env.ports[0].onmessage?.({ data: { samples: new Float32Array(320), sampleRate: 16000 } });
    });
    act(() => {
      view.result.current.release();
    });
    const commits = env.sockets[0].sentTextEvents().filter((event) => event.type === "input.commit");
    expect(commits).toHaveLength(1);
    expect(commits[0].visual).toBeUndefined();
    // 纯语音不受影响：会话切换只停共享，语音链路保持启用（不得 disable）
    expect(view.result.current.enabled).toBe(true);
    act(() => {
      view.result.current.disable();
    });
  });

  it("P2-9c (control): within the same session canShare stays true and startShare succeeds", async () => {
    const env = makeVisualEnv();
    let sessionId: string | null = "sess-1";
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    await act(async () => {
      await view.result.current.enable(); // identity 冻结为 sess-1（= 当前会话）
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    expect(view.result.current.visual.canShare).toBe(true);
    act(() => {
      view.rerender(); // 同一会话重渲染：不得误停/过度收紧
    });
    expect(view.result.current.visual.canShare).toBe(true);
    let started = false;
    await act(async () => {
      started = await view.result.current.startShare();
    });
    expect(started).toBe(true);
    expect(env.sockets[0].sentTextEvents().some((event) => event.type === "visual.share.start")).toBe(true);
    expect(view.result.current.visual.phase).toBe("starting");
    act(() => {
      view.result.current.disable();
    });
  });

  // ---- P2-9c 时窗：getDisplayMedia 等待期间切会话 → 上送前复查，拒绝并释放轨道 ------

  it("P2-9c: a session switch while the picker is open aborts before share.start (track released, notice shown)", async () => {
    const env = makeVisualEnv();
    let resolvePicker: ((stream: FakeDisplayStreamForHook) => void) | undefined;
    env.transport.getDisplayMedia = () =>
      new Promise<FakeDisplayStreamForHook>((resolve) => {
        resolvePicker = resolve;
      });
    let sessionId: string | null = "sess-A";
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    await act(async () => {
      await view.result.current.enable(); // identity 冻结为 sess-A
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    // 用户点击共享：getDisplayMedia pending（选择器弹窗打开，resolve 由测试控制）
    let startPromise: Promise<boolean> | undefined;
    act(() => {
      startPromise = view.result.current.startShare();
    });
    expect(resolvePicker).toBeDefined();
    expect(view.result.current.visual.phase).toBe("idle"); // 选择器期间尚未进入 starting
    // 等待期间用户切换到会话 B：phase 仍是 idle → 切换 effect no-op（缺陷时窗本体）
    sessionId = "sess-B";
    act(() => {
      view.rerender();
    });
    let started = true;
    await act(async () => {
      resolvePicker?.(new FakeDisplayStreamForHook(env.track));
      started = await startPromise!;
    });
    expect(started).toBe(false); // 拒绝开始
    expect(env.track.stopped).toBe(true); // 轨道立即停止释放
    const events = env.sockets[0].sentTextEvents();
    expect(events.some((event) => event.type === "visual.share.start")).toBe(false); // 不上送 share.start
    expect(events.some((event) => event.type === "visual.frame")).toBe(false); // 也不上送帧
    expect(events.some((event) => event.type === "visual.share.stop")).toBe(false); // 从未开始：无停止事件
    expect(env.notices).toHaveBeenCalledWith("会话已切换，未开始画面共享"); // 一次可见提示
    expect(view.result.current.visual.phase).toBe("idle");
    act(() => {
      view.result.current.disable();
    });
  });

  it("P2-9c (control): same session while the picker is open → share.start still goes out (no over-tightening)", async () => {
    const env = makeVisualEnv();
    let resolvePicker: ((stream: FakeDisplayStreamForHook) => void) | undefined;
    env.transport.getDisplayMedia = () =>
      new Promise<FakeDisplayStreamForHook>((resolve) => {
        resolvePicker = resolve;
      });
    let sessionId: string | null = "sess-A";
    const view = renderHook(() =>
      useRealtimeVoice({
        sessionId,
        onCommittedTranscript: env.committed,
        onNotice: env.notices,
        transport: env.transport,
        visual: { supportEnv: env.supportEnv as never },
      }),
    );
    await act(async () => {
      await view.result.current.enable();
    });
    act(() => {
      env.sockets[0].onopen?.();
    });
    let startPromise: Promise<boolean> | undefined;
    act(() => {
      startPromise = view.result.current.startShare();
    });
    expect(resolvePicker).toBeDefined();
    // 等待期间仅发生同会话重渲染（上游无关 state 变化）：不得拒绝
    act(() => {
      view.rerender();
    });
    let started = false;
    await act(async () => {
      resolvePicker?.(new FakeDisplayStreamForHook(env.track));
      started = await startPromise!;
    });
    expect(started).toBe(true);
    expect(env.track.stopped).toBe(false); // 轨道保持活动
    expect(env.sockets[0].sentTextEvents().some((event) => event.type === "visual.share.start")).toBe(true);
    expect(view.result.current.visual.phase).toBe("starting");
    act(() => {
      view.result.current.disable();
    });
  });

  it("start → visual.share.start over the control channel; frames only after started ack", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    expect(view.result.current.visual.supported).toBe(true);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    expect(starts).toHaveLength(1);
    expect(typeof starts[0].source_id).toBe("string");
    expect(starts[0].source_epoch).toBe(1);
    expect(view.result.current.visual.phase).toBe("starting");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch, resumed: false }),
      });
    });
    expect(view.result.current.visual.phase).toBe("sharing");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    const frames = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.frame");
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ frame_id: "frame-1", mime: "image/jpeg", data_b64: "QUFB", width: 320, height: 240 });
    act(() => {
      view.result.current.disable();
    });
  });

  it("commit carries visual {source_id,kind} and the kind switch is visible in state", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    act(() => {
      view.result.current.setVisualKind("history");
    });
    expect(view.result.current.visual.kind).toBe("history");

    // 驱动一轮语音提交：press → 注入采集帧 → release
    await act(async () => {
      await view.result.current.press();
    });
    const port = env.ports[0];
    act(() => {
      port.onmessage?.({ data: { samples: new Float32Array(320), sampleRate: 16000 } });
    });
    act(() => {
      view.result.current.release();
    });
    const commits = env.sockets[0].sentTextEvents().filter((event) => event.type === "input.commit");
    expect(commits).toHaveLength(1);
    expect(commits[0].visual).toEqual({ source_id: starts[0].source_id, kind: "history" });
    act(() => {
      view.result.current.disable();
    });
  });

  it("a visual turn does NOT resubmit its transcript after input.final + turn.committed", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    await act(async () => {
      await view.result.current.press();
    });
    env.ports[0].onmessage?.({ data: { samples: new Float32Array(320), sampleRate: 16000 } });
    act(() => {
      view.result.current.release();
    });
    expect(env.committed).not.toHaveBeenCalled(); // 带视觉：服务端提交，客户端不回投
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "input.final", turn_id: "tv1", text: "这页讲了什么" }) });
      env.sockets[0].onmessage?.({
        data: serverEvent({
          type: "turn.committed",
          turn_id: "tv1",
          text: "这页讲了什么",
          visual: [{ frame_id: "frame-1", content_ref: "artifact://v1/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }],
          task_ref: "task-9",
        }),
      });
    });
    expect(env.committed).toHaveBeenCalledTimes(0); // sendMessage 次数为 0
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("task-9"));
    // 普通语音提交仍提交一次
    act(() => {
      view.result.current.stopShare();
    });
    await act(async () => {
      await view.result.current.press();
    });
    env.ports[env.ports.length - 1].onmessage?.({ data: { samples: new Float32Array(320), sampleRate: 16000 } });
    act(() => {
      view.result.current.release();
    });
    const commits = env.sockets[0].sentTextEvents().filter((event) => event.type === "input.commit");
    expect(commits).toHaveLength(2);
    expect(commits[1].visual).toBeUndefined(); // 已停止 + kind=current → 不附带
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "turn.committed", turn_id: "tv2", text: "纯语音轮" }) });
    });
    expect(env.committed).toHaveBeenCalledTimes(1); // 无 visual 的普通提交仍为 1
    act(() => {
      view.result.current.disable();
    });
  });

  it("visual.clarify is displayed and is not auto-resubmitted; next release clears it", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.clarify", turn_id: "tv3", question: "要当前画面还是刚才那页？" }),
      });
    });
    expect(view.result.current.visual.clarifyQuestion).toContain("当前画面");
    const sentBefore = env.sockets[0].sent.length;
    act(() => {
      view.result.current.release();
    });
    expect(view.result.current.visual.clarifyQuestion).toBeNull(); // 下一轮提问清除
    expect(env.sockets[0].sent.length).toBe(sentBefore); // 不自动重发
    act(() => {
      view.result.current.disable();
    });
  });

  it("registered/rejected update the visual snapshot (bound mapping, cache_full pause)", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({
          type: "visual.frame.registered",
          frame_id: "frame-1",
          content_ref: "artifact://v1/cccccccccccccccccccccccccccccccc",
        }),
      });
    });
    expect(view.result.current.visual.boundCount).toBe(1);
    expect(view.result.current.visual.lastFrameBound).toBe(true);
    act(() => {
      env.sockets[0].onmessage?.({ data: serverEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "cache_full" }) });
    });
    expect(view.result.current.visual.samplingPaused).toBe(true);
    expect(env.notices).toHaveBeenCalledWith(expect.stringContaining("缓存已满"));
    act(() => {
      view.result.current.disable();
    });
  });

  // ---- P2-7 / P2-10：rejected 后静止画面重发、重复拒绝提示节流 -------------

  it("P2-7: a rejected frame is resent on the next tick even when the screen is static", async () => {
    const env = makeVisualEnv({ frames: ["QUFB", "QUFB", "QUFB", "QUFB"] });
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    let frames = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.frame");
    expect(frames).toHaveLength(1);
    // 服务端拒绝 frame-1：未注册成功 → 不留“已发送”标记
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "malformed" }),
      });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // 静止画面（与被拒帧完全相同字节）也必须重发，不得被 identical-skip 永久吞掉
    frames = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.frame");
    expect(frames).toHaveLength(2);
    expect(frames[1]).toMatchObject({ data_b64: "QUFB" });
    // 快照不含 skippedIdentical 计数；重发行为由 frames 长度直接断言（上一行）
    act(() => {
      view.result.current.disable();
    });
  });

  it("P2-10: duplicate rejection notices are throttled (one per reason within the window)", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    const rejectDuplicate = () => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.frame.rejected", frame_id: "frame-x", reason: "duplicate_frame_id" }),
      });
    };
    act(() => {
      rejectDuplicate();
      rejectDuplicate();
      rejectDuplicate();
    });
    const duplicateNotices = env.notices.mock.calls.filter(([message]) =>
      String(message).includes("重复帧"),
    );
    expect(duplicateNotices).toHaveLength(1); // 同因 5s 窗口内只提示一次
    // 不同拒绝码不受影响（各自一条）
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.frame.rejected", frame_id: "frame-x", reason: "mime_unsupported" }),
      });
    });
    expect(env.notices.mock.calls.some(([message]) => String(message).includes("格式不受支持"))).toBe(true);
    expect(view.result.current.visual.lastRejectedReason).toBe("mime_unsupported");
    act(() => {
      view.result.current.disable();
    });
  });

  it("stopShare sends visual.share.stop and no further frames; unmount closes the grabber", async () => {
    const env = makeVisualEnv();
    const view = await enableAndOpen(env);
    await act(async () => {
      await view.result.current.startShare();
    });
    const starts = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.start");
    act(() => {
      env.sockets[0].onmessage?.({
        data: serverEvent({ type: "visual.share.started", source_id: starts[0].source_id, source_epoch: starts[0].source_epoch }),
      });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    act(() => {
      view.result.current.stopShare();
    });
    expect(env.track.stopped).toBe(true);
    const stops = env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.share.stop");
    expect(stops).toHaveLength(1);
    expect(view.result.current.visual.previewDataUrl).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(env.sockets[0].sentTextEvents().filter((event) => event.type === "visual.frame")).toHaveLength(1);
    view.unmount(); // 卸载清理
    expect(env.grabs.closed).toBeGreaterThanOrEqual(1);
  });
});
