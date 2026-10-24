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
  const onClose = vi.fn();
  const onRetryPlayback = vi.fn();
  const props = {
    connectionState: "ready" as const,
    micEnabled: false,
    modality: "voice_full" as const,
    chainLabel: "级联语音链路（ASR→LLM→TTS）",
    onPress,
    onRelease,
    onFallbackText,
    onClose,
    onRetryPlayback,
    ...over,
  };
  render(<RealtimeVoiceBar {...props} />);
  return { onPress, onRelease, onFallbackText, onClose, onRetryPlayback };
}

describe("RealtimeVoiceBar", () => {
  it("shows an explicit inactive microphone state and a permanent close action", () => {
    renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button).toBeEnabled();
    expect(button).toHaveTextContent("开始说话");
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("麦克风未开启");
    expect(screen.getByRole("button", { name: "关闭语音" })).toBeEnabled();
  });

  it("click or mobile tap toggles recording instead of releasing when the finger lifts", () => {
    const { onPress, onRelease } = renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    fireEvent.pointerDown(button);
    fireEvent.pointerUp(button);
    expect(onPress).not.toHaveBeenCalled();
    expect(onRelease).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(onRelease).not.toHaveBeenCalled();
  });

  it("explains that the first tap starts listening automatically after connecting", () => {
    renderBar({ connectionState: "opening" });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("连接后自动开始收音");
    expect(screen.getByTestId("realtime-push-to-talk")).toHaveTextContent("正在连接");
    expect(screen.getByTestId("realtime-push-to-talk")).toBeDisabled();
    expect(screen.getByRole("button", { name: "关闭语音" })).toBeEnabled();
  });

  it("shows visible live recording with an explicit finish action", () => {
    const { onRelease } = renderBar({ micEnabled: true });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("正在语音输入");
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button).toHaveTextContent("结束并发送");
    expect(button).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(button);
    expect(onRelease).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "关闭语音" })).toBeEnabled();
  });

  it("shows permission wait and allows cancelling microphone startup", () => {
    const { onRelease } = renderBar({ micStarting: true });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("等待麦克风权限");
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button).toHaveTextContent("取消收音");
    fireEvent.click(button);
    expect(onRelease).toHaveBeenCalledTimes(1);
  });

  it("allows mobile microphone input without screen sharing capability", () => {
    const { onPress } = renderBar({ modality: "voice_text_fallback" });
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onPress).toHaveBeenCalledOnce();
    expect(screen.getByTestId("realtime-fallback")).toBeInTheDocument();
  });

  it("never disables finish and close while a text reply starts in the background", () => {
    const { onRelease, onClose } = renderBar({ disabled: true, micEnabled: true });
    const finish = screen.getByTestId("realtime-push-to-talk");
    expect(finish).toBeEnabled();
    fireEvent.click(finish);
    fireEvent.click(screen.getByRole("button", { name: "关闭语音" }));
    expect(onRelease).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the close action visible through opening, connection failure and streaming", () => {
    for (const connectionState of ["opening", "failed", "reconnecting"] as const) {
      cleanup();
      const { onClose } = renderBar({ connectionState, disabled: true });
      const close = screen.getByRole("button", { name: "关闭语音" });
      fireEvent.click(close);
      expect(onClose).toHaveBeenCalledTimes(1);
    }
  });

  it("disables talk when connection is not ready", () => {
    renderBar({ connectionState: "failed" });
    expect(screen.getByTestId("realtime-push-to-talk")).toBeDisabled();
    expect(screen.getByTestId("realtime-state").textContent).toContain("改用文字");
  });

  it("shows generation/playback status and a retry action when speech output fails", () => {
    renderBar({ playbackState: "synthesizing" });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("正在生成语音回复");
    cleanup();
    renderBar({ playbackState: "playing" });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("正在播放语音回复");
    cleanup();
    const { onRetryPlayback } = renderBar({ playbackState: "failed", error: "本地 TTS 合成失败" });
    expect(screen.getByTestId("realtime-state")).toHaveTextContent("语音回复未播放");
    fireEvent.click(screen.getByRole("button", { name: "重试语音回复" }));
    expect(onRetryPlayback).toHaveBeenCalledOnce();
  });

  it("offers a same-origin login link for expired browser sessions", () => {
    renderBar({ connectionState: "failed", error: "登录状态已失效，请重新登录后重试" });
    const link = screen.getByRole("link", { name: "重新登录" });
    expect(link.getAttribute("href")).toBe(
      `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`,
    );
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