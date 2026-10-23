import { describe, expect, it } from "vitest";

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
  readonly sources: FakeSource[] = [];
  async decodeAudioData(): Promise<unknown> {
    return { decoded: true };
  }
  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
}

function makeCapture(devices: MediaDevicesLike) {
  const frames: Int16Array[] = [];
  const ports: FakePort[] = [];
  const capture = new MicCapture({
    mediaDevices: devices,
    pipeline: new CapturePipeline({ frameSamples: 320 }),
    onFrame: (frame) => frames.push(frame),
    createPort: () => {
      const port = new FakePort();
      ports.push(port);
      return port;
    },
  });
  return { capture, frames, ports };
}

describe("MicCapture", () => {
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
});