import { describe, expect, it, vi } from "vitest";

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

function makeClient(
  over: { onProtocolError?: (info: { kind: "parse" | "envelope"; malformedFrames: number }) => void } = {},
): {
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
    playback,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    scheduleTimeout: (fn, ms) => {
      scheduled.push({ fn, ms });
    },
    onProtocolError: over.onProtocolError,
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
    client.noteActiveResponse("r-old");
    client.handleMessage(new ArrayBuffer(12)); // 旧回复分片按请求预绑定入队（noteActiveResponse）
    expect(playback.peek()?.responseId).toBe("r-old");
    client.requestLocalInterrupt("r-old"); // 用户打断：本地立即丢弃该回复的排队分片（D27）
    expect(playback.peek()).toBeNull();
    client.noteActiveResponse("r-new");
    client.handleMessage(new ArrayBuffer(16)); // 下一个请求的分片照常入队
    expect(playback.peek()?.responseId).toBe("r-new");
  });

  it("close moves to closed", () => {
    const { client, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.close();
    expect(client.connectionState).toBe("closed");
  });

  it("close stops late events from reaching listeners", () => {
    const { client, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    const seen: string[] = [];
    client.onEvent((event) => seen.push(event.event_id));
    client.close();
    client.handleMessage(envelope({ type: "turn.committed", turn_id: "t1", text: "迟到" }));
    expect(seen).toEqual([]);
  });

  // ---- P2：close() 与重连定时器（disable 落在退避窗口不得产生僵尸 socket） -------------

  it("P2: close during the reconnect window leaves no zombie socket (pending retry cannot revive)", () => {
    const states: string[] = [];
    const sockets: FakeSocket[] = [];
    const scheduled: { fn: () => void; ms: number }[] = [];
    const client = new MediaSessionClient({
      url: "ws://127.0.0.1:8000/api/v1/realtime/sessions/m1/events",
      playback: new PlaybackQueue(() => 1),
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      scheduleTimeout: (fn, ms) => {
        scheduled.push({ fn, ms });
      },
      onStateChange: (state) => states.push(state),
    });
    client.connect();
    sockets[0].onopen?.();
    sockets[0].onclose?.({ code: 1006 }); // → reconnecting，排期 500ms 重连
    expect(client.connectionState).toBe("reconnecting");
    expect(scheduled).toHaveLength(1);
    client.close(); // disable 落在 0.5–2s 退避窗口内
    expect(client.connectionState).toBe("closed");
    const statesAfterClose = states.length;
    // 推进所有已排期重连（注入式调度器不可取消 → 由 openSocket closed 守卫兜底）
    for (const item of [...scheduled]) {
      item.fn();
    }
    expect(sockets).toHaveLength(1); // 无新 socket（僵尸）
    expect(client.connectionState).toBe("closed"); // 状态保持 closed
    expect(states).toHaveLength(statesAfterClose); // 无 onStateChange 回调（状态不复活）
  });

  it("P2: close() clears the default-scheduler reconnect timer (advancing all timers revives nothing)", async () => {
    vi.useFakeTimers();
    try {
      const sockets: FakeSocket[] = [];
      const client = new MediaSessionClient({
        url: "ws://127.0.0.1:8000/api/v1/realtime/sessions/m1/events",
        playback: new PlaybackQueue(() => 1),
        createSocket: () => {
          const socket = new FakeSocket();
          sockets.push(socket);
          return socket;
        },
        // 不注入 scheduleTimeout → 默认 setTimeout 路径（句柄可被 close() 取消）
      });
      client.connect();
      sockets[0].onopen?.();
      sockets[0].onclose?.({ code: 1006 });
      expect(client.connectionState).toBe("reconnecting");
      client.close();
      await vi.advanceTimersByTimeAsync(10_000); // 推进所有退避档（500/1000/2000ms）
      expect(sockets).toHaveLength(1); // 定时器已被 close() 取消：无新 socket
      expect(client.connectionState).toBe("closed");
    } finally {
      vi.useRealTimers();
    }
  });

  it("P2: a late onclose after close() does not resurrect the client (no reconnect scheduled)", () => {
    const { client, sockets, scheduled } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.close();
    sockets[0].onclose?.({ code: 1006 }); // close() 之后的迟到 onclose（真实浏览器会触发）
    expect(client.connectionState).toBe("closed");
    expect(scheduled).toHaveLength(0); // 不排期重连
    expect(sockets).toHaveLength(1); // 也不开新 socket
  });

  // ---- P2-11：下行坏信封不得打断处理链（丢弃 + 有界上报，不携带载荷） -------------

  it("P2-11: drops malformed envelopes (missing field / wrong version / non-JSON) without throwing", () => {
    const protocolErrors: { kind: string; malformedFrames: number }[] = [];
    const { client, sockets } = makeClient({
      onProtocolError: (info) => protocolErrors.push({ ...info }),
    });
    client.connect();
    sockets[0].onopen?.();
    const seen: string[] = [];
    client.onEvent((event) => seen.push(event.event_id));
    expect(() => {
      // 缺 event_id（信封断言失败）
      client.handleMessage(
        '{"version":1,"type":"media.closed","seq":1,"connection_epoch":1,"session_id":"s1","media_session_id":"m1"}',
      );
      // 错 version（信封断言失败）
      client.handleMessage(envelope({ version: 2 }));
      // 非 JSON 文本（解析失败）
      client.handleMessage("not-json{");
    }).not.toThrow();
    expect(seen).toEqual([]); // 坏帧不进监听器
    expect(client.malformedFrameCount).toBe(3); // 计数如实
    expect(protocolErrors).toHaveLength(1); // 有界：连续多条只上报一次
    expect(protocolErrors[0]).toEqual({ kind: "envelope", malformedFrames: 1 }); // 首个坏帧即上报
    // 上报不携带原始载荷（隐私契约 §6）
    expect(JSON.stringify(protocolErrors)).not.toContain("not-json");
    // 坏帧之后的合法事件照常分发（处理链未被打断）
    client.handleMessage(envelope({ event_id: "good", type: "turn.committed", turn_id: "t1", text: "恢复" }));
    expect(seen).toEqual(["good"]);
    expect(client.malformedFrameCount).toBe(3); // 好帧不计坏帧
  });

  it("P2-11: a fresh connection re-arms the bounded protocol-error report", () => {
    const protocolErrors: { kind: string }[] = [];
    const { client, sockets, scheduled } = makeClient({
      onProtocolError: (info) => protocolErrors.push({ kind: info.kind }),
    });
    client.connect();
    sockets[0].onopen?.();
    client.handleMessage("broken-1");
    client.handleMessage("broken-2");
    expect(protocolErrors).toEqual([{ kind: "parse" }]);
    sockets[0].onclose?.({ code: 1006 }); // 触发有界重连
    scheduled[0].fn();
    sockets[1].onopen?.();
    client.handleMessage("broken-3");
    expect(protocolErrors).toEqual([{ kind: "parse" }, { kind: "parse" }]); // 新连接再给一次
    expect(client.malformedFrameCount).toBe(1); // 计数按连接重置
  });

  it("sendEvent rejects malformed envelopes instead of fabricating fields", () => {
    const { client, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    expect(() =>
      client.sendEvent({
        version: 1,
        type: "tts.request",
        event_id: "",
        seq: 1,
        connection_epoch: 1,
        session_id: "s1",
        media_session_id: "m1",
        text: "hi",
        response_id: "r1",
      }),
    ).toThrow(/missing required/);
    expect(() =>
      client.sendEvent({
        version: 1,
        type: "tts.request",
        event_id: "e1",
        seq: 1,
        connection_epoch: 1,
        session_id: "s1",
        media_session_id: "m1",
        text: "hi",
      }),
    ).toThrow(/response_id/);
    expect(sockets[0].sent).toHaveLength(0);
  });

  it("sendEvent delivers control events when ready and refuses otherwise", () => {
    const { client, sockets } = makeClient();
    client.connect();
    expect(
      client.sendEvent({
        version: 1,
        type: "input.commit",
        event_id: "e1",
        seq: 1,
        connection_epoch: 1,
        session_id: "s1",
        media_session_id: "m1",
      }),
    ).toBe(false); // opening 未就绪
    sockets[0].onopen?.();
    expect(
      client.sendEvent({
        version: 1,
        type: "input.commit",
        event_id: "e1",
        seq: 1,
        connection_epoch: 1,
        session_id: "s1",
        media_session_id: "m1",
      }),
    ).toBe(true);
    expect(JSON.parse(sockets[0].sent[0] as string)).toMatchObject({ type: "input.commit" });
  });

  it("noteActiveResponse binds downstream binaries to the requested reply as pcm16", () => {
    const { client, playback, sockets } = makeClient();
    client.connect();
    sockets[0].onopen?.();
    client.noteActiveResponse("resp-9");
    client.handleMessage(new ArrayBuffer(16)); // 成为当前分片
    client.handleMessage(new ArrayBuffer(16)); // 追加排队
    expect(playback.snapshot().currentResponseId).toBe("resp-9");
    expect(playback.snapshot().queued).toBe(1);
    const next = playback.advance(); // 当前结束 → 推进到下一段
    expect(next?.format).toBe("pcm16");
    expect(next?.responseId).toBe("resp-9");
  });

  it("notifies connection state transitions", () => {
    const states: string[] = [];
    const playback = new PlaybackQueue(() => 1);
    const sockets: FakeSocket[] = [];
    const scheduled: { fn: () => void; ms: number }[] = [];
    const client = new MediaSessionClient({
      url: "ws://127.0.0.1:8000/api/v1/realtime/sessions/m1/events",
      playback,
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      scheduleTimeout: (fn, ms) => {
        scheduled.push({ fn, ms });
      },
      onStateChange: (state) => states.push(state),
    });
    client.connect();
    sockets[0].onopen?.();
    sockets[0].onclose?.({ code: 1006 });
    expect(states).toEqual(["opening", "ready", "reconnecting"]);
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