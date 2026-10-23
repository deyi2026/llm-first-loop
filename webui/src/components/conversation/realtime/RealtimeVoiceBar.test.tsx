import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RealtimeVoiceBar } from "./RealtimeVoiceBar";

afterEach(() => {
  cleanup();
});

function renderBar(over: Partial<Parameters<typeof RealtimeVoiceBar>[0]> = {}) {
  const onPress = vi.fn();
  const onRelease = vi.fn();
  const onFallbackText = vi.fn();
  const props = {
    connectionState: "ready" as const,
    micEnabled: false,
    modality: "voice_full" as const,
    chainLabel: "级联语音链路（ASR→LLM→TTS）",
    onPress,
    onRelease,
    onFallbackText,
    ...over,
  };
  render(<RealtimeVoiceBar {...props} />);
  return { onPress, onRelease, onFallbackText };
}

describe("RealtimeVoiceBar", () => {
  it("renders and exposes push-to-talk when ready", () => {
    renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button).toBeEnabled();
    expect(screen.getByTestId("realtime-state").textContent).toContain("可以说话");
  });

  it("presses on pointer down and releases on pointer up", () => {
    const { onPress, onRelease } = renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    fireEvent.pointerDown(button);
    expect(onPress).toHaveBeenCalledTimes(1);
    fireEvent.pointerUp(button);
    expect(onRelease).toHaveBeenCalledTimes(1);
  });

  it("releases on pointer leave and blur", () => {
    const { onRelease } = renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    fireEvent.pointerLeave(button);
    fireEvent.blur(button);
    expect(onRelease).toHaveBeenCalledTimes(2);
  });

  it("disables talk when connection is not ready", () => {
    renderBar({ connectionState: "failed" });
    expect(screen.getByTestId("realtime-push-to-talk")).toBeDisabled();
    expect(screen.getByTestId("realtime-state").textContent).toContain("改用文字");
  });

  it("shows fallback hint and disables talk in screenshot fallback", () => {
    renderBar({ modality: "screenshot_fallback" });
    expect(screen.getByTestId("realtime-push-to-talk")).toBeDisabled();
    expect(screen.getByTestId("realtime-fallback").textContent).toContain("文字输入");
  });

  it("discloses the actual chain label", () => {
    renderBar({ chainLabel: "原生实时语音链路" });
    expect(screen.getByTestId("realtime-chain").textContent).toBe("原生实时语音链路");
  });

  it("invokes the text fallback entry", () => {
    const { onFallbackText } = renderBar({ modality: "voice_text_fallback" });
    fireEvent.click(screen.getByTestId("realtime-fallback-text"));
    expect(onFallbackText).toHaveBeenCalledTimes(1);
  });

  it("does not render fallback entry without handler", () => {
    const { onFallbackText } = renderBar({ onFallbackText: undefined });
    expect(onFallbackText).not.toHaveBeenCalled();
    expect(screen.queryByTestId("realtime-fallback-text")).toBeNull();
  });

  it("respects the disabled prop", () => {
    renderBar({ disabled: true });
    expect(screen.getByTestId("realtime-push-to-talk")).toBeDisabled();
  });
});