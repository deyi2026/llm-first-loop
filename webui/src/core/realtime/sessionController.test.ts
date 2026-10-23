import { describe, expect, it, vi } from "vitest";

import { RealtimeSessionController } from "./sessionController";
import type { PlaybackOutput } from "./audioPlayback";
import type { MediaSessionClient } from "./mediaSessionClient";
import type { MicCapture } from "./micCapture";

function makeDeps() {
  const capture = {
    press: vi.fn(async () => true),
    release: vi.fn(),
    cancel: vi.fn(),
    micEnabled: false,
  } as unknown as MicCapture;
  const client = {
    connectionState: "ready" as const,
    sendAudioFrame: vi.fn(() => true),
    sendControl: vi.fn(() => true),
    requestLocalInterrupt: vi.fn(() => true),
    close: vi.fn(),
  } as unknown as MediaSessionClient;
  const playback = {
    stop: vi.fn(() => true),
  } as unknown as PlaybackOutput;
  return { capture, client, playback };
}

describe("RealtimeSessionController", () => {
  it("press delegates to capture and reports failure honestly", async () => {
    const deps = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(await controller.press()).toBe(true);
    expect(deps.capture.press).toHaveBeenCalledTimes(1);

    (deps.capture.press as ReturnType<typeof vi.fn>).mockResolvedValueOnce(false);
    expect(await controller.press()).toBe(false);
  });

  it("release and cancel delegate to capture", () => {
    const deps = makeDeps();
    const controller = new RealtimeSessionController(deps);
    controller.release();
    controller.cancel();
    expect(deps.capture.release).toHaveBeenCalledTimes(1);
    expect(deps.capture.cancel).toHaveBeenCalledTimes(1);
  });

  it("sendFrame forwards to the control channel", () => {
    const deps = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.sendFrame(new Int16Array(320))).toBe(true);
    expect(deps.client.sendAudioFrame).toHaveBeenCalledTimes(1);
  });

  it("interrupt stops playback locally and notifies the server", () => {
    const deps = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.interrupt("r1")).toBe(true);
    expect(deps.playback.stop).toHaveBeenCalledTimes(1);
    expect(deps.client.requestLocalInterrupt).toHaveBeenCalledWith("r1");
    expect(deps.client.sendControl).toHaveBeenCalledWith("tts.cancel");
  });

  it("interrupt returns false when nothing was playing", () => {
    const deps = makeDeps();
    (deps.playback.stop as ReturnType<typeof vi.fn>).mockReturnValue(false);
    (deps.client.requestLocalInterrupt as ReturnType<typeof vi.fn>).mockReturnValue(false);
    expect(new RealtimeSessionController(deps).interrupt()).toBe(false);
  });

  it("close cleans capture, playback and client", () => {
    const deps = makeDeps();
    new RealtimeSessionController(deps).close();
    expect(deps.capture.cancel).toHaveBeenCalledTimes(1);
    expect(deps.playback.stop).toHaveBeenCalledTimes(1);
    expect(deps.client.close).toHaveBeenCalledTimes(1);
  });

  it("exposes connection state and mic state", () => {
    const deps = makeDeps();
    const controller = new RealtimeSessionController(deps);
    expect(controller.connectionState).toBe("ready");
    expect(controller.micEnabled).toBe(false);
  });
});