import { describe, expect, it, vi } from "vitest";

import { RealtimeSessionController } from "./sessionController";
import type { PlaybackOutput } from "./audioPlayback";
import type { MediaSessionClient } from "./mediaSessionClient";
import type { MicCapture } from "./micCapture";
import type { RealtimeEnvelope } from "./realtimeEvents";

function makeDeps(over: { connectionState?: MediaSessionClient["connectionState"] } = {}) {
  const eventListeners: ((event: RealtimeEnvelope) => void)[] = [];
  const connection = {
    state: (over.connectionState ?? "ready") as MediaSessionClient["connectionState"],
  };
  const setConnectionState = (next: MediaSessionClient["connectionState"]): void => {
    connection.state = next;
  };
  const capture = {
    press: vi.fn(async () => true),
    release: vi.fn(),
    cancel: vi.fn(),
    micEnabled: false,
  } as unknown as MicCapture;
  const client = {
    get connectionState(): MediaSessionClient["connectionState"] {
      return connection.state;
    },
    connectionEpoch: 1,
    // 与真实 MediaSessionClient 语义一致：仅 ready 才接受上行/事件发送
    sendAudioFrame: vi.fn(() => connection.state === "ready"),
    sendEvent: vi.fn(() => connection.state === "ready"),
    onEvent: vi.fn((listener: (event: RealtimeEnvelope) => void) => {
      eventListeners.push(listener);
    }),
    noteActiveResponse: vi.fn(),
    requestLocalInterrupt: vi.fn(() => true),
    close: vi.fn(() => {
      connection.state = "closed";
    }),
  } as unknown as MediaSessionClient;
  const playback = {
    stop: vi.fn(() => true),
  } as unknown as PlaybackOutput;
  const sink = { onCommittedTranscript: vi.fn(), onNotice: vi.fn() };
  const deps = {
    capture,
    client,
    playback,
    identity: { sessionId: "sess-1", mediaSessionId: "ms-1" },
    sink,
  };
  return { deps, capture, client, playback, sink, eventListeners, setConnectionState };
}

const envelopeOf = (raw: string): RealtimeEnvelope => JSON.parse(raw) as RealtimeEnvelope;

const serverEnvelope = (over: Record<string, unknown>): string =>
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

describe("RealtimeSessionController", () => {
  it("press delegates to capture and reports failure honestly", async () => {
    const { deps, capture } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(await controller.press()).toBe(true);
    expect(capture.press).toHaveBeenCalledTimes(1);

    (capture.press as ReturnType<typeof vi.fn>).mockResolvedValueOnce(false);
    expect(await controller.press()).toBe(false);
  });

  it("release and cancel delegate to capture", () => {
    const { deps, capture } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    controller.release();
    controller.cancel();
    expect(capture.release).toHaveBeenCalledTimes(1);
    expect(capture.cancel).toHaveBeenCalledTimes(1);
  });

  it("sendFrame forwards to the control channel", () => {
    const { deps, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.sendFrame(new Int16Array(320))).toBe(true);
    expect(client.sendAudioFrame).toHaveBeenCalledTimes(1);
  });

  it("interrupt stops playback locally and notifies the server", () => {
    const { deps, playback, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.interrupt("r1")).toBe(true);
    expect(playback.stop).toHaveBeenCalledTimes(1);
    expect(client.requestLocalInterrupt).toHaveBeenCalledWith("r1");
  });

  it("interrupt returns false when nothing was playing", () => {
    const { deps, playback, client } = makeDeps();
    (playback.stop as ReturnType<typeof vi.fn>).mockReturnValue(false);
    (client.requestLocalInterrupt as ReturnType<typeof vi.fn>).mockReturnValue(false);
    expect(new RealtimeSessionController(deps).interrupt()).toBe(false);
  });

  it("close cleans capture, playback and client", () => {
    const { deps, capture, playback, client } = makeDeps();
    new RealtimeSessionController(deps).close();
    expect(capture.cancel).toHaveBeenCalledTimes(1);
    expect(playback.stop).toHaveBeenCalledTimes(1);
    expect(client.close).toHaveBeenCalledTimes(1);
  });

  it("exposes connection state and mic state", () => {
    const { deps } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.connectionState).toBe("ready");
    expect(controller.micEnabled).toBe(false);
  });
});

describe("RealtimeSessionController input.commit", () => {
  it("release sends exactly one input.commit with a complete envelope after captured audio", async () => {
    const { deps, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    controller.handleCapturedFrame(new Int16Array(320));
    controller.handleCapturedFrame(new Int16Array(320));
    controller.release();
    controller.release(); // 重复松开：不得重复提交

    expect(client.sendEvent).toHaveBeenCalledTimes(1);
    const envelope = (client.sendEvent as ReturnType<typeof vi.fn>).mock.calls[0][0] as RealtimeEnvelope;
    expect(envelope).toMatchObject({
      version: 1,
      type: "input.commit",
      connection_epoch: 1,
      session_id: "sess-1",
      media_session_id: "ms-1",
    });
    expect(Number.isInteger(envelope.seq)).toBe(true);
    expect(envelope.event_id.length).toBeGreaterThan(0);
  });

  it("does not commit before the connection is ready (notice, no send)", async () => {
    const { deps, client, sink } = makeDeps({ connectionState: "opening" });
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    // opening：sendAudioFrame 拒发 → 无已上行音频
    controller.handleCapturedFrame(new Int16Array(320));
    controller.release();
    expect(client.sendEvent).not.toHaveBeenCalled();
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("未采集到可上传的音频"));
  });

  it("does not commit when audio was captured but connection dropped at release", async () => {
    const { deps, client, sink, setConnectionState } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    controller.handleCapturedFrame(new Int16Array(320));
    setConnectionState("reconnecting");
    controller.release();
    expect(client.sendEvent).not.toHaveBeenCalled();
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("未就绪"));
  });

  it("does not commit when press failed (permission denied)", async () => {
    const { deps, capture, client } = makeDeps();
    (capture.press as ReturnType<typeof vi.fn>).mockResolvedValue(false);
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    controller.release();
    expect(client.sendEvent).not.toHaveBeenCalled();
  });

  it("reports a failed commit visibly without throwing", async () => {
    const { deps, client, sink } = makeDeps();
    (client.sendEvent as ReturnType<typeof vi.fn>).mockReturnValue(false);
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    controller.handleCapturedFrame(new Int16Array(320));
    expect(() => controller.release()).not.toThrow();
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("input.commit 发送失败"));
  });

  it("press interrupts playback first (barge-in before capture)", async () => {
    const { deps, playback, capture } = makeDeps();
    const order: string[] = [];
    (playback.stop as ReturnType<typeof vi.fn>).mockImplementation(() => {
      order.push("stop");
      return true;
    });
    (capture.press as unknown as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      order.push("press");
      return true;
    });
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    expect(order).toEqual(["stop", "press"]);
  });
});

describe("RealtimeSessionController committed turns", () => {
  it("submits a non-empty final transcript exactly once per turn_id", () => {
    const { deps, eventListeners, sink } = makeDeps();
    new RealtimeSessionController(deps);
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "input.final", turn_id: "t1", text: "你好" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t1", text: "你好" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t1", text: "你好" }))); // 迟到重复
    expect(sink.onCommittedTranscript).toHaveBeenCalledTimes(1);
    expect(sink.onCommittedTranscript).toHaveBeenCalledWith("你好", "t1");
  });

  it("falls back to the recorded input.final text when committed carries none", () => {
    const { deps, eventListeners, sink } = makeDeps();
    new RealtimeSessionController(deps);
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "input.final", turn_id: "t2", text: "语音链路" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t2", text: "" })));
    expect(sink.onCommittedTranscript).toHaveBeenCalledTimes(1);
    expect(sink.onCommittedTranscript).toHaveBeenCalledWith("语音链路", "t2");
  });

  it("does not submit an empty final transcript (notice instead, no fake user message)", () => {
    const { deps, eventListeners, sink } = makeDeps();
    new RealtimeSessionController(deps);
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "input.final", turn_id: "t3", text: "" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t3", text: "" })));
    expect(sink.onCommittedTranscript).not.toHaveBeenCalled();
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("终稿为空"));
  });

  it("keeps distinct turns independent", () => {
    const { deps, eventListeners, sink } = makeDeps();
    new RealtimeSessionController(deps);
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "a", text: "第一轮" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "b", text: "第二轮" })));
    expect(sink.onCommittedTranscript).toHaveBeenCalledTimes(2);
  });
});

describe("RealtimeSessionController tts.request", () => {
  it("requests TTS once per response and pre-binds the response id", () => {
    const { deps, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.requestTts("回复内容", "resp-1")).toBe(true);
    expect(controller.requestTts("回复内容", "resp-1")).toBe(false); // 同一回复不重复请求
    expect(controller.requestTts("另一条", "resp-2")).toBe(true);

    const calls = (client.sendEvent as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => c[0] as RealtimeEnvelope,
    );
    const ttsCalls = calls.filter((envelope) => envelope.type === "tts.request");
    expect(ttsCalls).toHaveLength(2);
    expect(ttsCalls[0]).toMatchObject({ text: "回复内容", response_id: "resp-1" });
    expect(client.noteActiveResponse).toHaveBeenCalledWith("resp-1");
  });

  it("skips empty text and unknown response ids", () => {
    const { deps, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.requestTts("   ", "resp-1")).toBe(false);
    expect(controller.requestTts("文本", "")).toBe(false);
    expect(client.sendEvent).not.toHaveBeenCalled();
  });

  it("does not request TTS when the connection is not ready (visible notice)", () => {
    const { deps, client, sink } = makeDeps({ connectionState: "reconnecting" });
    const controller = new RealtimeSessionController(deps);
    expect(controller.requestTts("文本", "resp-1")).toBe(false);
    expect(client.sendEvent).not.toHaveBeenCalled();
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("不播报"));
  });

  it("close clears turn dedupe state and the tts ledger", async () => {
    const { deps, client } = makeDeps();
    const controller = new RealtimeSessionController(deps);
    await controller.press();
    controller.close();
    expect(client.requestLocalInterrupt).toHaveBeenCalled();
    expect(controller.requestTts("文本", "resp-1")).toBe(false); // client 已关闭 → 未就绪
  });
});
// ---------------------------------------------------------------------------
// M3：带 visual 的 input.commit（服务端提交任务；客户端不回投终稿）与 visual.clarify
// ---------------------------------------------------------------------------

describe("RealtimeSessionController M3 visual commits", () => {
  function makeVisualDeps() {
    const base = makeDeps();
    const sink = {
      onCommittedTranscript: base.sink.onCommittedTranscript,
      onVisualTurnCommitted: vi.fn(),
      onVisualClarify: vi.fn(),
      onNotice: base.sink.onNotice,
    };
    const visual = {
      commitVisual: vi.fn(
        (): { source_id: string; kind: "current" | "history" } | null => ({ source_id: "share-1", kind: "current" }),
      ),
    };
    const deps = { ...base.deps, sink, visual };
    return { ...base, deps, sink, visual };
  }

  async function pressWithAudio(controller: RealtimeSessionController): Promise<void> {
    await controller.press();
    controller.handleCapturedFrame(new Int16Array(320));
  }

  it("attaches visual {source_id,kind} to input.commit while sharing", async () => {
    const { deps, client, visual } = makeVisualDeps();
    const controller = new RealtimeSessionController(deps);
    await pressWithAudio(controller);
    controller.release();
    const envelope = (client.sendEvent as ReturnType<typeof vi.fn>).mock.calls[0][0] as RealtimeEnvelope;
    expect(envelope.type).toBe("input.commit");
    expect(envelope.visual).toEqual({ source_id: "share-1", kind: "current" });
    expect(visual.commitVisual).toHaveBeenCalledTimes(1);
  });

  it("keeps input.commit without visual when the share source declines (null)", async () => {
    const { deps, client, visual } = makeVisualDeps();
    visual.commitVisual.mockReturnValue(null);
    const controller = new RealtimeSessionController(deps);
    await pressWithAudio(controller);
    controller.release();
    const envelope = (client.sendEvent as ReturnType<typeof vi.fn>).mock.calls[0][0] as RealtimeEnvelope;
    expect(envelope.visual).toBeUndefined();
  });

  it("does NOT resubmit a visual turn transcript after turn.committed (server owns submission)", async () => {
    const { deps, client, sink, eventListeners } = makeVisualDeps();
    const controller = new RealtimeSessionController(deps);
    await pressWithAudio(controller);
    controller.release();
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "input.final", turn_id: "t-vis", text: "看下这页" })));
    dispatch(
      envelopeOf(
        serverEnvelope({
          type: "turn.committed",
          turn_id: "t-vis",
          text: "看下这页",
          visual: [{ frame_id: "frame-1", content_ref: "artifact://v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }],
          evidence_refs: ["artifact://v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
          task_ref: "task-77",
        }),
      ),
    );
    // 客户端不再把该 turn 终稿提交到对话（sendMessage 次数 0 → sink 不触发）
    expect(sink.onCommittedTranscript).not.toHaveBeenCalled();
    expect(sink.onVisualTurnCommitted).toHaveBeenCalledTimes(1);
    expect(sink.onVisualTurnCommitted).toHaveBeenCalledWith({ turnId: "t-vis", text: "看下这页", taskRef: "task-77" });
    // input.commit 只发了一次；后续无新增上行事件
    expect((client.sendEvent as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it("still submits the normal (non-visual) turn exactly once", async () => {
    const { deps, sink, visual, eventListeners } = makeVisualDeps();
    visual.commitVisual.mockReturnValue(null);
    new RealtimeSessionController(deps);
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "input.final", turn_id: "t-plain", text: "纯语音" })));
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t-plain", text: "纯语音" })));
    expect(sink.onCommittedTranscript).toHaveBeenCalledTimes(1);
    expect(sink.onVisualTurnCommitted).not.toHaveBeenCalled();
  });

  it("shows visual.clarify and never auto-resends (kind unchanged, no new upstream event)", async () => {
    const { deps, client, sink, eventListeners } = makeVisualDeps();
    const controller = new RealtimeSessionController(deps);
    await pressWithAudio(controller);
    controller.release();
    const before = (client.sendEvent as ReturnType<typeof vi.fn>).mock.calls.length;
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "visual.clarify", turn_id: "t-vis2", question: "你想问当前画面还是刚才那页？" })));
    expect(sink.onVisualClarify).toHaveBeenCalledWith("你想问当前画面还是刚才那页？", "t-vis2");
    expect((client.sendEvent as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(before); // 不自动重发
  });

  it("surfaces realtime error visibly and releases the visual-pending flag", async () => {
    const { deps, sink, eventListeners } = makeVisualDeps();
    const controller = new RealtimeSessionController(deps);
    await pressWithAudio(controller);
    controller.release();
    const dispatch = eventListeners[0];
    dispatch(envelopeOf(serverEnvelope({ type: "error", code: 500, reason: "internal" })));
    expect(sink.onNotice).toHaveBeenCalledWith(expect.stringContaining("500"));
    // 后续该 turn 的 turn.committed（无 visual 数组、客户端标志已清）走普通提交路径
    dispatch(envelopeOf(serverEnvelope({ type: "turn.committed", turn_id: "t-err", text: "回退文本" })));
    expect(sink.onCommittedTranscript).toHaveBeenCalledTimes(1);
  });
});
