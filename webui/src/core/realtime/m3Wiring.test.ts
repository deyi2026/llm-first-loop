import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PreviewBuffer, SamplingThrottle } from "./keyframeSampling";
import { chainDisclosure, resolveModality, FALLBACK_HINT } from "./modality";
import { detectScreenShareSupport, ScreenShareSession, type DisplayMediaDevicesLike, type DisplayStreamLike } from "./screenShare";
import type { RealtimeEnvelope } from "./realtimeEvents";
import {
  nextSourceEpoch,
  resetShareSourceLedgerForTests,
  stableShareSourceId,
  VisualShareController,
  type FrameGrabber,
  type GrabbedFrame,
  type VisualShareClient,
} from "./visualShare";

class FakeVideoTrack {
  stopped = false;
  stop(): void {
    this.stopped = true;
  }
}

class FakeDisplayStream implements DisplayStreamLike {
  constructor(readonly tracks: FakeVideoTrack[]) {}
  getVideoTracks(): FakeVideoTrack[] {
    return this.tracks;
  }
  getTracks(): FakeVideoTrack[] {
    return this.tracks;
  }
}

describe("ScreenShareSession", () => {
  it("only captures the user-selected stream", async () => {
    const track = new FakeVideoTrack();
    const devices: DisplayMediaDevicesLike = {
      getDisplayMedia: async () => new FakeDisplayStream([track]),
    };
    const session = new ScreenShareSession(devices);
    expect(await session.start("tab-1")).toBe(true);
    expect(session.active).toBe(true);
    expect(session.sourceId).toBe("tab-1");
    expect(session.sourceEpoch).toBe(1);
  });

  it("returns false when the user cancels selection", async () => {
    const devices: DisplayMediaDevicesLike = {
      getDisplayMedia: async () => {
        throw new Error("NotAllowedError");
      },
    };
    const session = new ScreenShareSession(devices);
    expect(await session.start()).toBe(false);
    expect(session.active).toBe(false);
    expect(session.sourceId).toBeNull();
  });

  it("stop bumps epoch and notifies invalidation", async () => {
    const track = new FakeVideoTrack();
    const session = new ScreenShareSession({
      getDisplayMedia: async () => new FakeDisplayStream([track]),
    });
    let ended = 0;
    session.onEnded(() => {
      ended += 1;
    });
    await session.start();
    const epoch = session.stop();
    expect(track.stopped).toBe(true);
    expect(epoch).toBe(2);
    expect(session.active).toBe(false);
    expect(ended).toBe(1);
  });

  it("does not start twice", async () => {
    const session = new ScreenShareSession({
      getDisplayMedia: async () => new FakeDisplayStream([new FakeVideoTrack()]),
    });
    await session.start();
    expect(await session.start()).toBe(false);
  });
});

describe("keyframe sampling", () => {
  it("throttles to the sampling interval", () => {
    const throttle = new SamplingThrottle(1000);
    expect(throttle.shouldCapture(0)).toBe(true);
    expect(throttle.shouldCapture(400)).toBe(false);
    expect(throttle.shouldCapture(1000)).toBe(true);
  });

  it("forced capture bypasses the interval", () => {
    const throttle = new SamplingThrottle(1000);
    throttle.shouldCapture(0);
    expect(throttle.shouldCapture(100, true)).toBe(true);
  });

  it("rejects non-positive interval", () => {
    expect(() => new SamplingThrottle(0)).toThrow();
  });

  it("preview buffer replaces only stale previews under congestion", () => {
    const buffer = new PreviewBuffer(2);
    expect(buffer.add("f1").replaced).toBeNull();
    expect(buffer.add("f2").replaced).toBeNull();
    const result = buffer.add("f3");
    expect(result.replaced).toBe("f1"); // 淘汰最旧预览
    expect(buffer.takeLatest()).toBe("f3");
    expect(buffer.size()).toBe(2);
  });
});

describe("modality degradation", () => {
  it("full when mic and share available", () => {
    expect(resolveModality({ mic: true, screenShare: true })).toBe("voice_full");
  });

  it("text fallback when only mic available", () => {
    expect(resolveModality({ mic: true, screenShare: false })).toBe("voice_text_fallback");
  });

  it("screenshot fallback when mic unavailable", () => {
    expect(resolveModality({ mic: false, screenShare: true })).toBe("screenshot_fallback");
  });

  it("discloses the actual chain and does not promise unmeasured mobile background audio", () => {
    const cascade = chainDisclosure({ cascade: true });
    expect(cascade.label).toContain("级联");
    expect(cascade.mobileBackgroundContinuous).toBe(false);
    const native = chainDisclosure({ cascade: false, mobileBackgroundMeasured: true });
    expect(native.label).toContain("原生");
    expect(native.mobileBackgroundContinuous).toBe(true);
  });

  it("provides an accessible fallback hint", () => {
    expect(FALLBACK_HINT).toContain("文字输入");
  });
});
// ---------------------------------------------------------------------------
// M3 视觉共享控制器（fake devices/grabber/scheduler；契约 docs/M3-KEYFRAME-WIRE-CONTRACT.md）
// ---------------------------------------------------------------------------

class FakeVisualClient implements VisualShareClient {
  connectionState = "ready";
  connectionEpoch = 1;
  readonly sent: RealtimeEnvelope[] = [];
  private readonly listeners: ((event: RealtimeEnvelope) => void)[] = [];

  sendEvent(envelope: RealtimeEnvelope): boolean {
    this.sent.push(envelope);
    return true;
  }

  onEvent(listener: (event: RealtimeEnvelope) => void): void {
    this.listeners.push(listener);
  }

  emit(event: RealtimeEnvelope): void {
    for (const listener of [...this.listeners]) {
      listener(event);
    }
  }

  of(type: string): RealtimeEnvelope[] {
    return this.sent.filter((envelope) => envelope.type === type);
  }
}

class ScriptedGrabber implements FrameGrabber {
  grabs = 0;
  closed = 0;
  constructor(private frames: (GrabbedFrame | null)[]) {}

  async grab(): Promise<GrabbedFrame | null> {
    this.grabs += 1;
    return this.frames.length > 0 ? this.frames.shift() ?? null : null;
  }

  close(): void {
    this.closed += 1;
  }
}

class EndedCapableTrack extends FakeVideoTrack {
  private readonly listeners: (() => void)[] = [];

  addEventListener(_type: string, listener: () => void): void {
    this.listeners.push(listener);
  }

  removeEventListener(_type: string, listener: () => void): void {
    const index = this.listeners.indexOf(listener);
    if (index !== -1) {
      this.listeners.splice(index, 1);
    }
  }

  fireEnded(): void {
    for (const listener of [...this.listeners]) {
      listener();
    }
  }
}

function frame(b64: string, width = 320, height = 240): GrabbedFrame {
  return { dataB64: b64, width, height, mime: "image/jpeg" };
}

function shareEvent(over: Record<string, unknown>): RealtimeEnvelope {
  return {
    version: 1,
    type: "visual.share.started",
    event_id: `evt-${Math.random()}`,
    seq: Math.floor(Math.random() * 1000),
    connection_epoch: 1,
    session_id: "s1",
    media_session_id: "ms1",
    ...over,
  } as RealtimeEnvelope;
}

function makeVisualHarness(over: { frames?: (GrabbedFrame | null)[]; intervalMs?: number; endedTrack?: EndedCapableTrack } = {}) {
  const track = over.endedTrack ?? new EndedCapableTrack();
  const stream = new FakeDisplayStream([track]);
  const devices: DisplayMediaDevicesLike = {
    getDisplayMedia: async () => stream,
  };
  const client = new FakeVisualClient();
  const notices: string[] = [];
  const grabber = new ScriptedGrabber(over.frames ?? []);
  let clock = 100; // 非 0 起点便于断言 captured_at_ms 随时钟
  const controller = new VisualShareController({
    client,
    devices,
    identity: { sessionId: "s1", mediaSessionId: "ms1" },
    createGrabber: () => grabber,
    nowMs: () => clock,
    intervalMs: over.intervalMs,
    sink: { onNotice: (message) => notices.push(message) },
  });
  return {
    controller,
    client,
    grabber,
    notices,
    track,
    advance: async (ms: number) => {
      clock += ms;
      await vi.advanceTimersByTimeAsync(ms);
    },
  };
}

describe("VisualShareController share/stop", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetShareSourceLedgerForTests();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends visual.share.start on user gesture with stable source id and epoch 1", async () => {
    const { controller, client } = makeVisualHarness();
    expect(await controller.startShare()).toBe(true);
    const starts = client.of("visual.share.start");
    expect(starts).toHaveLength(1);
    expect(starts[0].source_id).toMatch(/^share-[A-Za-z0-9._:-]+$/);
    expect(starts[0].source_id?.length ?? 0).toBeLessThanOrEqual(128);
    expect(starts[0].source_epoch).toBe(1);
    expect(controller.snapshot.phase).toBe("starting");
    expect(client.of("visual.frame")).toHaveLength(0); // 未收 started 不发帧
  });

  it("frames flow only after visual.share.started, with contract fields and 1fps cadence", async () => {
    const { controller, client, grabber, advance } = makeVisualHarness({
      frames: [frame("QUFB", 320, 240), frame("QkJC", 320, 240)],
    });
    await controller.startShare();
    client.emit(
      shareEvent({
        type: "visual.share.started",
        source_id: client.of("visual.share.start")[0].source_id,
        source_epoch: 1,
        resumed: false,
      }),
    );
    expect(controller.snapshot.phase).toBe("sharing");
    await advance(999);
    expect(client.of("visual.frame")).toHaveLength(0);
    await advance(1); // t=1100：间隔满 1000ms
    const frames = client.of("visual.frame");
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({
      source_id: client.of("visual.share.start")[0].source_id,
      source_epoch: 1,
      frame_id: "frame-1",
      width: 320,
      height: 240,
      mime: "image/jpeg",
      data_b64: "QUFB",
    });
    expect(frames[0].captured_at_ms).toBe(1100); // 客户端单调时钟（注入）
    await advance(1000);
    const second = client.of("visual.frame")[1];
    expect(second).toBeDefined();
    expect(second.captured_at_ms).toBeGreaterThan(frames[0].captured_at_ms as number); // 单调
    expect(grabber.grabs).toBe(2);
  });

  it("skips identical frames without sending", async () => {
    const { controller, client, advance } = makeVisualHarness({
      frames: [frame("QUFB"), frame("QUFB"), frame("Q0ND")],
    });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(1); // 第 2 帧完全相同：跳过
    expect(controller.snapshot.skippedIdentical).toBe(1);
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(2);
  });

  it("registered maps content_ref to frame_id and marks bound for readback", async () => {
    const { controller, client, advance } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    expect(controller.snapshot.lastFrameBound).toBe(false); // 仅预览
    client.emit(
      shareEvent({
        type: "visual.frame.registered",
        frame_id: "frame-1",
        content_ref: "artifact://v1/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        sha256: "deadbeef",
        path: "k/a.jpg",
        received_at_s: 12.5,
      }),
    );
    expect(controller.snapshot.boundCount).toBe(1);
    expect(controller.snapshot.lastFrameBound).toBe(true);
    expect(controller.snapshot.previewDataUrl).toContain("data:image/jpeg;base64,QUFB");
  });

  it("rate_limited backs off silently within the 0.5-1fps contract window", async () => {
    const { controller, client, advance, notices } = makeVisualHarness({
      frames: [frame("QUFB"), frame("QkJC"), frame("Q0ND")],
    });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "rate_limited" }));
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(1); // 退避到 2000ms：原节奏不发
    expect(notices).toHaveLength(0); // 静默：无可见提示
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(2);
    expect(controller.snapshot.lastRejectedReason).toBe("rate_limited");
  });

  it("cache_full pauses sampling with a visible notice", async () => {
    const { controller, client, advance, notices } = makeVisualHarness({ frames: [frame("QUFB"), frame("QkJC")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "cache_full" }));
    expect(controller.snapshot.samplingPaused).toBe(true);
    expect(notices.some((n) => n.includes("缓存已满"))).toBe(true);
    await advance(6000);
    expect(client.of("visual.frame")).toHaveLength(1); // 暂停期间不再上送
  });

  it("other rejection reasons surface bounded visible hints", async () => {
    const { controller, client, notices } = makeVisualHarness();
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-9", reason: "unknown_source" }));
    expect(controller.snapshot.lastRejectedReason).toBe("unknown_source");
    expect(notices.some((n) => n.includes("重新开始共享"))).toBe(true);
    expect(notices.join("")).not.toContain("QUFB"); // 提示不含帧内容
  });

  it("stop halts the track, sends visual.share.stop with epoch, then never sends frames again", async () => {
    const { controller, client, track, advance } = makeVisualHarness({ frames: [frame("QUFB"), frame("QkJC")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    controller.stopShare();
    expect(track.stopped).toBe(true);
    const stops = client.of("visual.share.stop");
    expect(stops).toHaveLength(1);
    expect(stops[0].source_epoch).toBe(1);
    expect(controller.snapshot.phase).toBe("stopped");
    expect(controller.snapshot.previewDataUrl).toBeNull(); // 本地预览与帧映射清空
    await advance(5000);
    expect(client.of("visual.frame")).toHaveLength(1); // 绝不再发帧
  });

  it("stopped commitVisual: current is refused visibly, history still refers to the source", async () => {
    const { controller, client, notices } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    controller.stopShare();
    expect(controller.commitVisual()).toBeNull();
    expect(notices.some((n) => n.includes("问当前画面"))).toBe(true);
    controller.setKind("history");
    expect(controller.commitVisual()).toEqual({ source_id: client.of("visual.share.start")[0].source_id, kind: "history" });
  });

  it("rejection hints are cleared when the share stops or restarts (rate_limited stays silent)", async () => {
    const { controller, client } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "unknown_source" }));
    expect(controller.snapshot.lastRejectedReason).toBe("unknown_source");
    controller.stopShare();
    expect(controller.snapshot.lastRejectedReason).toBeNull(); // 停止即清空，不留过期提示
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-1", reason: "malformed" }));
    expect(controller.snapshot.lastRejectedReason).toBeNull(); // 停止后的迟到拒绝不再置位
    await controller.startShare();
    expect(controller.snapshot.lastRejectedReason).toBeNull(); // 重共享起点干净
    client.emit(
      shareEvent({
        type: "visual.share.started",
        source_id: client.of("visual.share.start")[1].source_id,
        source_epoch: client.of("visual.share.start")[1].source_epoch,
      }),
    );
    client.emit(shareEvent({ type: "visual.frame.rejected", frame_id: "frame-2", reason: "rate_limited" }));
    expect(controller.snapshot.lastRejectedReason).toBe("rate_limited"); // 语义保留：静默退避（UI 侧不显示）
    controller.stopShare();
    expect(controller.snapshot.lastRejectedReason).toBeNull();
  });

  it("re-share with the same source id bumps the epoch", async () => {
    const { controller, client } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    controller.stopShare();
    expect(await controller.startShare()).toBe(true);
    const starts = client.of("visual.share.start");
    expect(starts).toHaveLength(2);
    expect(starts[1].source_id).toBe(starts[0].source_id); // 稳定 id
    expect(starts[1].source_epoch).toBe(2); // 重共享 +1
  });

  it("browser-side stop (track ended) takes the same stop path", async () => {
    const endedTrack = new EndedCapableTrack();
    const { controller, client, advance } = makeVisualHarness({ frames: [frame("QUFB"), frame("QkJC")], endedTrack });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    endedTrack.fireEnded(); // 浏览器「停止共享」按钮
    expect(client.of("visual.share.stop")).toHaveLength(1);
    expect(controller.snapshot.phase).toBe("stopped");
    await advance(5000);
    expect(client.of("visual.frame")).toHaveLength(1);
  });

  it("share.start rejected by the server returns to idle honestly", async () => {
    const { controller, client, notices } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    client.emit(shareEvent({ type: "error", code: 409, reason: "stale_epoch" }));
    expect(controller.snapshot.phase).toBe("idle");
    expect(notices.some((n) => n.includes("拒绝"))).toBe(true);
    await vi.advanceTimersByTimeAsync(5000);
    expect(client.of("visual.frame")).toHaveLength(0);
  });

  it("grab failures are skipped and counted without crashing", async () => {
    const { controller, client, advance } = makeVisualHarness({ frames: [null, frame("QUFB")] });
    await controller.startShare();
    client.emit(shareEvent({ source_id: client.of("visual.share.start")[0].source_id, source_epoch: 1 }));
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(0);
    expect(controller.snapshot.skippedFrames).toBe(1);
    await advance(1000);
    expect(client.of("visual.frame")).toHaveLength(1);
  });

  it("close releases the grabber and stops sharing", async () => {
    const { controller, client, grabber } = makeVisualHarness({ frames: [frame("QUFB")] });
    await controller.startShare();
    controller.close();
    expect(grabber.closed).toBe(1);
    expect(client.of("visual.share.stop")).toHaveLength(1);
    expect(controller.snapshot.phase).toBe("idle");
  });

  it("intervalMs outside the 0.5-1fps contract range is rejected", () => {
    const client = new FakeVisualClient();
    const make = (intervalMs: number) =>
      new VisualShareController({
        client,
        devices: { getDisplayMedia: async () => new FakeDisplayStream([new FakeVideoTrack()]) },
        identity: { sessionId: "s1", mediaSessionId: "ms1" },
        createGrabber: () => new ScriptedGrabber([]),
        intervalMs,
      });
    expect(() => make(500)).toThrow();
    expect(() => make(2500)).toThrow();
    expect(() => make(1000)).not.toThrow();
    expect(() => make(2000)).not.toThrow();
  });

  it("source ledger: stable id per page lifecycle, epochs strictly increase", () => {
    resetShareSourceLedgerForTests();
    const first = stableShareSourceId();
    expect(stableShareSourceId()).toBe(first);
    expect(nextSourceEpoch(first)).toBe(1);
    expect(nextSourceEpoch(first)).toBe(2);
    resetShareSourceLedgerForTests();
    expect(stableShareSourceId()).not.toBe(first); // 刷新（模块重置）后从 1 重新开始
  });
});

describe("visual preview buffer eviction (RET-04)", () => {
  it("evicts only the oldest unbound preview; bound previews never evicted", () => {
    const bound = new Set<string>(["f1"]);
    const isBound = (id: string) => bound.has(id);
    const buffer = new PreviewBuffer(2);
    expect(buffer.add("f1", isBound).dropped).toBe(false);
    expect(buffer.add("f2", isBound).dropped).toBe(false);
    const result = buffer.add("f3", isBound);
    expect(result.replaced).toBe("f2"); // f1 已绑定：只淘汰未绑定的 f2
    bound.add("f3");
    expect(buffer.add("f4", isBound)).toMatchObject({ replaced: null, dropped: true }); // 满环全绑定：宁可丢新预览
    expect(buffer.takeLatest()).toBe("f3");
    expect(buffer.size()).toBe(2);
  });
});

describe("screen share capability detection", () => {
  const desktopUa = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36";

  it("supported on desktop with getDisplayMedia and a fine pointer", () => {
    expect(
      detectScreenShareSupport({
        getDisplayMedia: () => undefined,
        userAgent: desktopUa,
        matchMedia: (query: string) => ({ matches: query === "(pointer: fine)" }),
      }),
    ).toBe(true);
  });

  it("hidden without getDisplayMedia", () => {
    expect(
      detectScreenShareSupport({
        getDisplayMedia: undefined,
        userAgent: desktopUa,
        matchMedia: () => ({ matches: true }),
      }),
    ).toBe(false);
  });

  it("hidden on mobile UA", () => {
    expect(
      detectScreenShareSupport({
        getDisplayMedia: () => undefined,
        userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile",
        matchMedia: () => ({ matches: true }),
      }),
    ).toBe(false);
  });

  it("hidden when touch is the primary pointer (no fine pointer)", () => {
    expect(
      detectScreenShareSupport({
        getDisplayMedia: () => undefined,
        userAgent: desktopUa,
        matchMedia: () => ({ matches: false }),
      }),
    ).toBe(false);
    // matchMedia 不可用时退回 maxTouchPoints
    expect(
      detectScreenShareSupport({ getDisplayMedia: () => undefined, userAgent: desktopUa, maxTouchPoints: 2 }),
    ).toBe(false);
    expect(
      detectScreenShareSupport({ getDisplayMedia: () => undefined, userAgent: desktopUa, maxTouchPoints: 0 }),
    ).toBe(true);
  });
});
