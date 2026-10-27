import { describe, expect, it, vi } from "vitest";

import { CapturePipeline } from "./capturePipeline";
import { PlaybackOutput, type AudioBufferSourceLike, type AudioContextLike } from "./audioPlayback";
import { MicCapture, type MediaDevicesLike, type MediaStreamLike, type WorkletPortLike } from "./micCapture";
import { PlaybackQueue } from "./playbackQueue";

class FakeTrack {
  stopped = false;
  stop(): void {
    this.stopped = true;
  }
}

class FakeStream implements MediaStreamLike {
  constructor(readonly track: FakeTrack) {}
  getTracks(): FakeTrack[] {
    return [this.track];
  }
}

class FakePort implements WorkletPortLike {
  onmessage: WorkletPortLike["onmessage"] = null;
  closed = false;
  close(): void {
    this.closed = true;
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
  state = "suspended";
  resumed = false;
  readonly sources: FakeSource[] = [];
  async resume(): Promise<void> {
    this.state = "running";
    this.resumed = true;
  }
  async decodeAudioData(): Promise<unknown> {
    return { decoded: true };
  }
  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
}

function makeCapture(devices: MediaDevicesLike, onNotice?: (message: string) => void) {
  const frames: Int16Array[] = [];
  const ports: FakePort[] = [];
  const capture = new MicCapture({
    mediaDevices: devices,
    pipeline: new CapturePipeline({ frameSamples: 320 }),
    onFrame: (frame) => frames.push(frame),
    onNotice,
    createPort: () => {
      const port = new FakePort();
      ports.push(port);
      return port;
    },
  });
  return { capture, frames, ports };
}

describe("MicCapture", () => {
  it("releases a stream that arrives after the user has released the button", async () => {
    let resolve!: (stream: FakeStream) => void;
    const track = new FakeTrack();
    const { capture, ports } = makeCapture({ getUserMedia: () => new Promise((r) => { resolve = r; }) });
    const pending = capture.press();
    capture.release();
    resolve(new FakeStream(track));
    expect(await pending).toBe(false);
    expect(capture.micEnabled).toBe(false);
    expect(ports).toHaveLength(0);
    expect(track.stopped).toBe(true);
  });

  it("press acquires stream and enables mic", async () => {
    const track = new FakeTrack();
    const { capture, ports } = makeCapture({ getUserMedia: async () => new FakeStream(track) });
    expect(await capture.press()).toBe(true);
    expect(capture.micEnabled).toBe(true);
    expect(capture.pressedDown).toBe(true);
    expect(ports.length).toBe(1);
  });

  it("permission failure returns false without fabricating capture", async () => {
    const { capture } = makeCapture({
      getUserMedia: async () => {
        throw new Error("NotAllowedError");
      },
    });
    expect(await capture.press()).toBe(false);
    expect(capture.micEnabled).toBe(false);
  });

  it("press returns false with a visible notice when getUserMedia hangs past the 10s bound", async () => {
    vi.useFakeTimers();
    try {
      const notices: string[] = [];
      const { capture } = makeCapture(
        { getUserMedia: () => new Promise<MediaStreamLike>(() => {}) },
        (message) => notices.push(message),
      );
      const pending = capture.press();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(await pending).toBe(false);
      expect(notices).toEqual(["麦克风启动超时，请检查权限/设备后重试"]);
      expect(capture.micEnabled).toBe(false); // 不伪造采集：超时即失败
    } finally {
      vi.useRealTimers();
    }
  });

  it("releases tracks of a stream that resolves after the timeout (no mic leak)", async () => {
    vi.useFakeTimers();
    try {
      const track = new FakeTrack();
      let resolveLate!: (stream: MediaStreamLike) => void;
      const { capture } = makeCapture({
        getUserMedia: () => new Promise<MediaStreamLike>((resolve) => { resolveLate = resolve; }),
      });
      const pending = capture.press();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(await pending).toBe(false);
      resolveLate(new FakeStream(track));
      await vi.advanceTimersByTimeAsync(0); // flush 微任务：迟到 stream 的轨道必须被停掉
      await Promise.resolve();
      expect(track.stopped).toBe(true);
      expect(capture.micEnabled).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("normal resolve inside the bound is unaffected (no notice)", async () => {
    vi.useFakeTimers();
    try {
      const track = new FakeTrack();
      const notices: string[] = [];
      const { capture } = makeCapture(
        {
          getUserMedia: () =>
            new Promise<MediaStreamLike>((resolve) => {
              setTimeout(() => resolve(new FakeStream(track)), 2_000);
            }),
        },
        (message) => notices.push(message),
      );
      const pending = capture.press();
      await vi.advanceTimersByTimeAsync(2_000);
      expect(await pending).toBe(true);
      expect(notices).toEqual([]);
      expect(capture.micEnabled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("release stops tracks and flushes the remainder", async () => {
    const track = new FakeTrack();
    const { capture, frames } = makeCapture({ getUserMedia: async () => new FakeStream(track) });
    await capture.press();
    capture.handleSamples({ samples: new Float32Array(400), sampleRate: 16000 });
    capture.release();
    expect(track.stopped).toBe(true);
    expect(capture.micEnabled).toBe(false);
    // 320 一帧 + flush 余量 80 → 2 帧（不丢尾段）
    expect(frames.length).toBe(2);
  });

  it("blur ends input like release", async () => {
    const track = new FakeTrack();
    const { capture } = makeCapture({ getUserMedia: async () => new FakeStream(track) });
    await capture.press();
    capture.onBlur();
    expect(capture.pressedDown).toBe(false);
    expect(track.stopped).toBe(true);
  });

  it("touch cancel ends input and discards remainder", async () => {
    const track = new FakeTrack();
    const { capture, frames } = makeCapture({ getUserMedia: async () => new FakeStream(track) });
    await capture.press();
    capture.handleSamples({ samples: new Float32Array(100), sampleRate: 16000 });
    capture.cancel();
    expect(frames.length).toBe(0); // 取消不发出余量
    expect(capture.micEnabled).toBe(false);
  });

  it("ignores samples after stream stopped", async () => {
    const { capture, frames } = makeCapture({ getUserMedia: async () => new FakeStream(new FakeTrack()) });
    capture.handleSamples({ samples: new Float32Array(320), sampleRate: 16000 });
    expect(frames.length).toBe(0);
  });
});

describe("PlaybackOutput", () => {
  it("plays the current chunk after decoding", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    const ctx = new FakeAudioContext();
    const output = new PlaybackOutput({ playback, audioContext: ctx });
    expect(await output.playNext()).toBe(true);
    expect(output.isPlaying).toBe(true);
    expect(ctx.resumed).toBe(true);
    expect(ctx.sources[0].started).toBe(true);
  });

  it("returns false when nothing to play", async () => {
    const output = new PlaybackOutput({ playback: new PlaybackQueue(() => 1), audioContext: new FakeAudioContext() });
    expect(await output.playNext()).toBe(false);
  });

  it("stop halts playback locally without server confirmation", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    const ctx = new FakeAudioContext();
    const output = new PlaybackOutput({ playback, audioContext: ctx });
    await output.playNext();
    expect(output.stop()).toBe(true);
    expect(output.isPlaying).toBe(false);
    expect(ctx.sources[0].stopped).toBe(true);
    expect(output.stop()).toBe(false); // 已停止
  });

  it("wraps pcm16 chunks into WAV before decoding (16k mono)", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new Int16Array(160).buffer, format: "pcm16" });
    const decoded: ArrayBuffer[] = [];
    const ctx: AudioContextLike = {
      destination: {},
      decodeAudioData: async (data) => {
        decoded.push(data);
        return { decoded: true };
      },
      createBufferSource: () => new FakeSource(),
    };
    const output = new PlaybackOutput({ playback, audioContext: ctx });
    expect(await output.playNext()).toBe(true);
    expect(decoded).toHaveLength(1);
    expect(decoded[0].byteLength).toBe(44 + 320); // 160 样本 × 2 字节 + 44 字节 WAV 头
    const magic = new TextDecoder("ascii").decode(new Uint8Array(decoded[0].slice(0, 4)));
    expect(magic).toBe("RIFF");
  });

  it("auto-advances to the next chunk when one ends naturally", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    const ctx = new FakeAudioContext();
    const output = new PlaybackOutput({ playback, audioContext: ctx });
    await output.playNext();
    expect(playback.snapshot().currentResponseId).toBe("r1");
    expect(playback.snapshot().queued).toBe(1);
    ctx.sources[0].onended?.(); // 第一段自然结束 → 异步接续
    await new Promise((resolve) => setTimeout(resolve, 0)); // flush decode 微任务
    expect(ctx.sources.length).toBe(2);
    expect(ctx.sources[1].started).toBe(true); // 自动接续第二段
    expect(output.isPlaying).toBe(true);
  });

  it("drops the chunk and degrades visibly when decoding fails", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    const errors: string[] = [];
    const created: FakeSource[] = [];
    const ctx: AudioContextLike = {
      destination: {},
      decodeAudioData: async () => {
        throw new Error("decode failed");
      },
      createBufferSource: () => {
        const source = new FakeSource();
        created.push(source);
        return source;
      },
    };
    const output = new PlaybackOutput({ playback, audioContext: ctx, onError: (_e, responseId) => errors.push(responseId) });
    expect(await output.playNext()).toBe(false);
    expect(errors).toEqual(["r1"]);
    expect(playback.snapshot().playing).toBe(false); // 失败分片被丢弃，不残留
    expect(created.length).toBe(0); // 解码失败：未创建/启动任何播放源
  });

  it("degrades without playing when the AudioContext is suspended (autoplay rejected)", async () => {
    const playback = new PlaybackQueue(() => 1);
    playback.enqueue({ responseId: "r1", connectionEpoch: 1, data: new ArrayBuffer(8) });
    const ctx: AudioContextLike = {
      destination: {},
      state: "suspended",
      decodeAudioData: async () => ({ decoded: true }),
      createBufferSource: () => new FakeSource(),
    };
    const errors: string[] = [];
    const output = new PlaybackOutput({ playback, audioContext: ctx, onError: (_e, responseId) => errors.push(responseId) });
    expect(await output.playNext()).toBe(false);
    expect(errors).toEqual(["r1"]);
    expect(output.isPlaying).toBe(false);
  });
});
  it("recoverIfSuspended resumes a hung context once without touching the queue", async () => {
    const ctx = new FakeAudioContext(); // 初始 state="suspended"
    const output = new PlaybackOutput({ playback: new PlaybackQueue(() => 1), audioContext: ctx });
    await output.recoverIfSuspended();
    expect(ctx.resumed).toBe(true);
    expect(ctx.state).toBe("running");
    expect(output.isPlaying).toBe(false); // 只自愈，不偷跑播放队列
  });

  it("recoverIfSuspended swallows resume failure (self-heal never throws)", async () => {
    let resumeCalls = 0;
    const ctx: AudioContextLike = {
      destination: {},
      state: "suspended",
      resume: () => {
        resumeCalls += 1;
        return Promise.reject(new Error("NotAllowedError"));
      },
      decodeAudioData: async () => ({ decoded: true }),
      createBufferSource: () => new FakeSource(),
    };
    const output = new PlaybackOutput({ playback: new PlaybackQueue(() => 1), audioContext: ctx });
    await expect(output.recoverIfSuspended()).resolves.toBeUndefined();
    expect(resumeCalls).toBe(1);
  });
