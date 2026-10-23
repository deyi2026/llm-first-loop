import { describe, expect, it } from "vitest";

import { PlaybackQueue } from "./playbackQueue";
import { acceptsEpoch, encodeEnvelope, decodeEnvelope, type RealtimeEnvelope } from "./realtimeEvents";
import { TARGET_SAMPLE_RATE, downmixToMono, floatToPcm16, resampleToPcm16 } from "./resampler";

describe("resampler", () => {
  it("clamps float samples to PCM16 range without wrapping", () => {
    expect(floatToPcm16(0)).toBe(0);
    expect(floatToPcm16(1)).toBe(0x7fff);
    expect(floatToPcm16(-1)).toBe(-0x8000);
    expect(floatToPcm16(2)).toBe(0x7fff);
    expect(floatToPcm16(-2)).toBe(-0x8000);
  });

  it("downsamples 48k to 16k at one third length", () => {
    const input = new Float32Array(4800).fill(0.5);
    const out = resampleToPcm16(input, 48000, TARGET_SAMPLE_RATE);
    expect(out.length).toBe(1600);
    expect(out[0]).toBe(floatToPcm16(0.5));
  });

  it("returns empty for empty input", () => {
    expect(resampleToPcm16(new Float32Array(0), 48000).length).toBe(0);
  });

  it("rejects non-positive sample rates", () => {
    expect(() => resampleToPcm16(new Float32Array(10), 0)).toThrow();
    expect(() => resampleToPcm16(new Float32Array(10), 48000, -1)).toThrow();
  });

  it("downmixes interleaved stereo to mono", () => {
    const stereo = new Float32Array([1, -1, 0.5, 0.5]);
    const mono = downmixToMono(stereo, 2);
    expect(mono.length).toBe(2);
    expect(mono[0]).toBeCloseTo(0);
    expect(mono[1]).toBeCloseTo(0.5);
  });
});

describe("playbackQueue", () => {
  const chunk = (responseId: string, epoch = 1): { responseId: string; connectionEpoch: number; data: ArrayBuffer } => ({
    responseId,
    connectionEpoch: epoch,
    data: new ArrayBuffer(8),
  });

  it("starts playing the first enqueued chunk", () => {
    const queue = new PlaybackQueue(() => 1);
    expect(queue.enqueue(chunk("r1"))).toBe(true);
    expect(queue.snapshot().playing).toBe(true);
    expect(queue.snapshot().currentResponseId).toBe("r1");
  });

  it("rejects stale connection epochs", () => {
    const queue = new PlaybackQueue(() => 3);
    expect(queue.enqueue(chunk("r1", 2))).toBe(false);
    expect(queue.snapshot().playing).toBe(false);
  });

  it("barge-in stops playback locally without server confirmation", () => {
    const queue = new PlaybackQueue(() => 1);
    queue.enqueue(chunk("r1"));
    queue.enqueue(chunk("r1"));
    expect(queue.interrupt()).toBe(true);
    expect(queue.snapshot().playing).toBe(false);
    expect(queue.snapshot().queued).toBe(0);
    expect(queue.snapshot().stoppedReason).toBe("user_barge_in");
  });

  it("interrupts a specific response only", () => {
    const queue = new PlaybackQueue(() => 1);
    queue.enqueue(chunk("r1"));
    queue.enqueue(chunk("r2"));
    expect(queue.interrupt("r2")).toBe(false); // r2 尚未在播
    expect(queue.snapshot().currentResponseId).toBe("r1");
    expect(queue.interrupt("r1")).toBe(true);
    expect(queue.snapshot().stoppedReason).toBe("reply_cancel");
  });

  it("advances through queued chunks", () => {
    const queue = new PlaybackQueue(() => 1);
    queue.enqueue(chunk("r1"));
    queue.enqueue(chunk("r2"));
    expect(queue.advance()?.responseId).toBe("r2");
    expect(queue.advance()).toBeNull();
  });

  it("interrupt with nothing playing reports false", () => {
    const queue = new PlaybackQueue(() => 1);
    expect(queue.interrupt()).toBe(false);
  });
});

describe("realtimeEvents", () => {
  const base: RealtimeEnvelope = {
    version: 1,
    type: "media.closed",
    event_id: "e1",
    seq: 1,
    connection_epoch: 1,
    session_id: "s1",
    media_session_id: "m1",
  };

  it("round trips a valid envelope", () => {
    const raw = encodeEnvelope(base);
    expect(decodeEnvelope(raw)).toEqual(base);
  });

  it("rejects missing base fields", () => {
    expect(() => encodeEnvelope({ ...base, event_id: "" })).toThrow(/missing required/);
  });

  it("rejects unsupported version", () => {
    expect(() => encodeEnvelope({ ...base, version: 2 })).toThrow(/version/);
  });

  it("requires type-specific fields without fabricating them", () => {
    expect(() => encodeEnvelope({ ...base, type: "input.final" })).toThrow(/turn_id/);
    expect(() => encodeEnvelope({ ...base, type: "input.final", turn_id: "t1" })).not.toThrow();
  });

  it("rejects stale epoch updates", () => {
    expect(acceptsEpoch({ ...base, connection_epoch: 1 }, 2)).toBe(false);
    expect(acceptsEpoch({ ...base, connection_epoch: 2 }, 2)).toBe(true);
  });
});