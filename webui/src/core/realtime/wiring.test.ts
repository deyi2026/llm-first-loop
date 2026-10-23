import { describe, expect, it } from "vitest";

import { CapturePipeline } from "./capturePipeline";
import { MediaSessionClient, NON_RETRYABLE_CLOSE_CODES, type SocketLike } from "./mediaSessionClient";
import { PlaybackQueue } from "./playbackQueue";

class FakeSocket implements SocketLike {
  sent: (string | ArrayBuffer)[] = [];
  closedWith: number | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }

  close(code?: number): void {
    this.closedWith = code ?? null;
  }

  socket(): SocketLike {
    return this;
  }
}

function makeClient(ownedSession = false): {
  client: MediaSessionClient;
  playback: PlaybackQueue;
  sockets: FakeSocket[];
  scheduled: { fn: () => void; ms: number }[];
} {
  const sockets: FakeSocket[] = [];
  const scheduled: { fn: () => void; ms: number }[] = [];
  const playback = new PlaybackQueue(() => 1);
  const client = new MediaSessionClient({
    url: "ws://127.0.0.1:8000/api/v1/realtime/sessions/m1/events",
    sessionId: ownedSession ? "s1" : undefined,
    mediaSessionId: ownedSession ? "m1" : undefined,
    playback,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    scheduleTimeout: (fn, ms) => {
      scheduled.push({ fn, ms });
    },
  });
  return { client, playback, sockets, scheduled };
}

const envelope = (over: Record<string, unknown> = {}): string =>
  JSON.stringify({
    version: 1,
    type: "media.closed",
    event_id: "e1",
    seq: 1,
    connection_epoch: 1,
    session_id: "s1",
    media_session_id: "m1",
    ...over,
  });

describe("MediaSessionClient", () => {
  it("becomes ready on open without waiting for a first frame", () => {
    const { client, sockets } = makeClient();
    client.connect();
    expect(client.connectionState).toBe("opening");
    sockets[0].onopen?.();
    expect(client.connectionState).toBe("ready");
  });

  it("only uploads frames when ready", () => {
    const { client, sockets } = makeClient();
    client.connect();
    expect(client.sendAudioFrame(new Int16Array(320))).toBe(false); // opening
    sockets[0].onopen?.();
    expect(client.sendAudioFrame(new Int16Array(320))).toBe(true);
  });

  it("fails without reconnecting on non-retryable close codes", () => {
    for (const code of NON_RETRYABLE_CLOSE_CODES) {
      const { client, sockets, scheduled } = makeClient();
      client.connect();
      sockets[0].onopen?.();
      sockets[0].onclose?.({ code });
      expect(client.connectionState).toBe("failed");
      expect(scheduled.length).toBe(0); // 不循环重连
    }
  });

  it("reconnects with bounded backoff", () => {
    const { client, sockets, scheduled } = makeClient();
    client.connect();
    sockets[0].onclose?.({ code: 1006 });
    expect(client.connectionState).toBe("reconnecting");
    expect(scheduled[0].ms).toBe(500);
    // Each timer creates a new socket. Repeating an obsolete socket's close
    // callback cannot spend the retry budget a second time.
    sockets[0].onclose?.({ code: 1006 });
    expect(scheduled).toHaveLength(1);
    scheduled[0].fn();
    sockets[1].onclose?.({ code: 1006 });
    expect(scheduled[1].ms).toBe(1000);
    scheduled[1].fn();
    sockets[2].onclose?.({ code: 1006 });
    expect(scheduled[2].ms).toBe(2000);
    scheduled[2].fn();
    sockets[3].onclose?.({ code: 1006 });
    expect(client.connectionState).toBe("failed"); // 超过 3 次上限
    expect(scheduled.length).toBe(3);
  });

  it("ignores stale epoch events", () => {
    const { client, sockets } = makeClient();
    client.connect(5);
    sockets[0].onopen?.();
    const seen: string[] = [];
    client.onEvent((event) => seen.push(event.event_id));
    client.handleMessage(envelope({ connection_epoch: 4, event_id: "old" }));
    client.handleMessage(envelope({ connection_epoch: 5, event_id: "new" }));
    expect(seen).toEqual(["new"]);
  });

  it("routes downstream binary frames to the playback queue", () => {
    const { client, playback, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r1" }));
    client.handleMessage(new ArrayBuffer(16));
    expect(playback.snapshot().playing).toBe(true);
  });

  it("barge-in stops playback locally", () => {
    const { client, playback, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r1" }));
    client.handleMessage(new ArrayBuffer(16));
    expect(client.requestLocalInterrupt()).toBe(true);
    expect(playback.snapshot().playing).toBe(false);
  });

  it("does not replay delayed binary from an interrupted response", () => {
    const { client, sockets, playback } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r-old" }));
    expect(client.requestLocalInterrupt()).toBe(false);
    client.handleMessage(new ArrayBuffer(12));
    expect(playback.peek()).toBeNull();
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r-new" }));
    client.handleMessage(new ArrayBuffer(16));
    expect(playback.peek()?.responseId).toBe("r-new");
  });

  it("rejects unsolicited and late audio after cancel while accepting the next requested reply", () => {
    const { client, playback, sockets } = makeClient(true);
    client.connect();
    sockets[0].onopen?.();
    client.handleMessage(new ArrayBuffer(16)); // Binary without an owned audio.playback envelope.
    expect(playback.peek()).toBeNull();
    expect(client.sendControl("tts.request", { text: "old", response_id: "r-old" })).toBe(true);
    client.requestLocalInterrupt(); // User barges in before the old audio marker arrives.
    client.sendControl("tts.cancel");
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r-old" }));
    client.handleMessage(new ArrayBuffer(12));
    expect(playback.peek()).toBeNull();
    expect(client.sendControl("tts.request", { text: "new", response_id: "r-new" })).toBe(true);
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r-old" }));
    client.handleMessage(new ArrayBuffer(12));
    expect(playback.peek()).toBeNull();
    client.handleMessage(envelope({ type: "audio.playback", response_id: "r-new" }));
    client.handleMessage(new ArrayBuffer(16));
    expect(playback.peek()?.responseId).toBe("r-new");
  });

  it("close moves to closed", () => {
    const { client, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.close();
    expect(client.connectionState).toBe("closed");
  });
});

describe("CapturePipeline", () => {
  it("emits fixed-size 16k frames and keeps the remainder", () => {
    const pipeline = new CapturePipeline({ frameSamples: 320 });
    const frames = pipeline.push(new Float32Array(1000), 16000);
    expect(frames.length).toBe(3); // 960 样本 → 3 帧
    expect(frames[0].length).toBe(320);
    expect(pipeline.pendingSamples).toBe(40);
  });

  it("flush emits the remaining tail as a final frame", () => {
    const pipeline = new CapturePipeline({ frameSamples: 320 });
    pipeline.push(new Float32Array(400), 16000);
    const tail = pipeline.flush();
    expect(tail.length).toBe(1);
    expect(pipeline.pendingSamples).toBe(0);
    expect(pipeline.flush().length).toBe(0); // 幂等：无余量不再发
  });

  it("resamples 48k input before framing", () => {
    const pipeline = new CapturePipeline({ frameSamples: 160 });
    const frames = pipeline.push(new Float32Array(4800), 48000);
    expect(frames.length).toBe(10); // 4800/3 = 1600 样本 → 10 帧
  });

  it("preserves long capture duration across 128-sample worklet chunks", () => {
    for (const sourceRate of [48000, 44100]) {
      const pipeline = new CapturePipeline();
      let emitted = 0;
      for (let index = 0; index < sourceRate; index += 128) {
        const count = Math.min(128, sourceRate - index);
        for (const frame of pipeline.push(new Float32Array(count), sourceRate)) emitted += frame.length;
      }
      for (const frame of pipeline.flush()) emitted += frame.length;
      expect(emitted).toBe(16000);
    }
  });

  it("streaming PCM is invariant to worklet chunk boundaries", () => {
    const input = Float32Array.from({ length: 4410 }, (_, i) => Math.sin(i * 0.03));
    const whole = new CapturePipeline();
    const fragmented = new CapturePipeline();
    const joined = [...whole.push(input, 44100), ...whole.flush()].flatMap((frame) => [...frame]);
    const chunks: Int16Array[] = [];
    for (let index = 0; index < input.length; index += 128) {
      chunks.push(...fragmented.push(input.slice(index, index + 128), 44100));
    }
    chunks.push(...fragmented.flush());
    expect(chunks.flatMap((frame) => [...frame])).toEqual(joined);
  });

  it("downmixes stereo before framing", () => {
    const pipeline = new CapturePipeline({ frameSamples: 2 });
    const frames = pipeline.push(new Float32Array([1, 1, 1, 1]), 16000, 2);
    expect(frames.length).toBe(1);
    expect(frames[0].length).toBe(2);
  });
});