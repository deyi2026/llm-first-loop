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
  const view = render(<RealtimeVoiceBar {...props} />);
  return { onPress, onRelease, onFallbackText, view };
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

  it("releases on pointercancel (touch cancel must not strand the pressed state)", () => {
    const { onRelease } = renderBar();
    fireEvent.pointerCancel(screen.getByTestId("realtime-push-to-talk"));
    expect(onRelease).toHaveBeenCalledTimes(1);
  });

  it("keyboard hold: Space/Enter keydown presses once (auto-repeat ignored), keyup releases", () => {
    const { onPress, onRelease } = renderBar();
    const button = screen.getByTestId("realtime-push-to-talk");
    expect(button.getAttribute("aria-pressed")).toBe("false"); // aria-pressed 反映 micEnabled 事实
    fireEvent.keyDown(button, { key: " " });
    fireEvent.keyDown(button, { key: " ", repeat: true }); // 长按自动重复：不得再次开始
    expect(onPress).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(button, { key: " " });
    expect(onRelease).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.keyUp(button, { key: "Enter" });
    expect(onPress).toHaveBeenCalledTimes(2);
    expect(onRelease).toHaveBeenCalledTimes(2);
    // 非按住键不产生开始/结束语义
    fireEvent.keyDown(button, { key: "Tab" });
    fireEvent.keyUp(button, { key: "Tab" });
    expect(onPress).toHaveBeenCalledTimes(2);
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
// ---------------------------------------------------------------------------
// M3：共享画面入口/预览/kind 切换/澄清展示（A11Y 与降级）
// ---------------------------------------------------------------------------

function visualState(over: Partial<Parameters<typeof RealtimeVoiceBar>[0]["visual"]> = {}) {
  return {
    supported: true,
    phase: "idle" as const,
    sourceId: null,
    previewDataUrl: null,
    lastFrameAtMs: null,
    lastFrameBound: false,
    boundCount: 0,
    samplingPaused: false,
    lastRejectedReason: null,
    kind: "current" as const,
    clarifyQuestion: null,
    ...over,
  };
}

describe("RealtimeVoiceBar M3 共享画面", () => {
  it("hides the share entry and shows the text/screenshot fallback hint when unsupported", () => {
    renderBar({ visual: visualState({ supported: false }) });
    expect(screen.queryByTestId("realtime-share-toggle")).toBeNull();
    expect(screen.getByTestId("realtime-share-unsupported").textContent).toContain("文字输入");
    expect(screen.getByTestId("realtime-share-unsupported").textContent).toContain("截图");
  });

  it("starts sharing on click (aria-pressed reflects state)", () => {
    const onStartShare = vi.fn();
    renderBar({ visual: visualState(), onStartShare });
    const button = screen.getByTestId("realtime-share-toggle");
    expect(button.getAttribute("aria-label")).toBe("共享画面");
    expect(button.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(button);
    expect(onStartShare).toHaveBeenCalledTimes(1);
  });

  it("P2-9: disables the share entry with a visible hint when no session is open (canShare=false)", () => {
    renderBar({ visual: visualState({ canShare: false }), onStartShare: vi.fn() });
    expect(screen.getByTestId("realtime-share-toggle")).toBeDisabled();
    expect(screen.getByTestId("realtime-share-no-session").textContent).toContain("会话");
  });

  it("P2-9: keeps the stop entry available if the session disappears mid-share (canShare=false)", () => {
    renderBar({ visual: visualState({ phase: "sharing", canShare: false }), onStopShare: vi.fn() });
    expect(screen.getByTestId("realtime-share-toggle")).toBeEnabled(); // 不隐藏停止入口
    expect(screen.queryByTestId("realtime-share-no-session")).toBeNull();
  });

  it("while sharing: keeps the stop entry visible, shows preview, status, source and frame age", () => {
    renderBar({
      visual: visualState({
        phase: "sharing",
        sourceId: "share-abc123",
        previewDataUrl: "data:image/jpeg;base64,QUFB",
        lastFrameAtMs: typeof performance !== "undefined" ? performance.now() : 0,
      }),
      onStopShare: vi.fn(),
    });
    const button = screen.getByTestId("realtime-share-toggle");
    expect(button.textContent).toContain("停止共享");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("realtime-share-status").textContent).toContain("共享中");
    expect(screen.getByTestId("realtime-share-status").getAttribute("aria-live")).toBe("polite");
    expect(screen.getByTestId("realtime-share-source").textContent).toBe("share-abc123");
    expect(screen.getByTestId("realtime-share-frame-age").textContent).toContain("帧龄");
    expect(screen.getByTestId("realtime-share-preview")).toBeTruthy();
    fireEvent.click(button);
  });

  it("kind radios: visible, keyboard-operable labels, current selectable only while sharing", () => {
    const onSetVisualKind = vi.fn();
    const { view } = renderBar({ visual: visualState({ phase: "sharing" }), onSetVisualKind });
    const current = screen.getByTestId("realtime-visual-kind-current") as HTMLInputElement;
    const history = screen.getByTestId("realtime-visual-kind-history") as HTMLInputElement;
    expect(current).toBeEnabled();
    expect(history).toBeEnabled();
    expect(current.checked).toBe(true); // 默认 current
    expect(screen.getByText("问当前画面")).toBeTruthy();
    expect(screen.getByText("问刚才那页")).toBeTruthy();
    fireEvent.click(history);
    expect(onSetVisualKind).toHaveBeenCalledWith("history");

    // 停止后：current 不可选，且有可见提示；history 仍可选
    view.rerender(
      <RealtimeVoiceBar
        connectionState="ready"
        micEnabled={false}
        modality="voice_full"
        chainLabel="级联"
        onPress={vi.fn()}
        onRelease={vi.fn()}
        visual={visualState({ phase: "stopped", kind: "current" })}
        onSetVisualKind={onSetVisualKind}
      />,
    );
    const currentStopped = screen.getByTestId("realtime-visual-kind-current") as HTMLInputElement;
    const historyStopped = screen.getByTestId("realtime-visual-kind-history") as HTMLInputElement;
    expect(currentStopped).toBeDisabled();
    expect(historyStopped).toBeEnabled();
    expect(screen.getByTestId("realtime-share-current-unavailable").textContent).toContain("问当前画面");
  });

  it("shows bounded visible hints for rejections (not rate_limited)", () => {
    const { view } = renderBar({ visual: visualState({ phase: "sharing", lastRejectedReason: "unknown_source" }) });
    expect(screen.getByTestId("realtime-share-rejected").textContent).toContain("重新开始共享");
    view.rerender(
      <RealtimeVoiceBar
        connectionState="ready"
        micEnabled={false}
        modality="voice_full"
        chainLabel="级联"
        onPress={vi.fn()}
        onRelease={vi.fn()}
        visual={visualState({ phase: "sharing", lastRejectedReason: "rate_limited" })}
      />,
    );
    expect(screen.queryByTestId("realtime-share-rejected")).toBeNull(); // 静默退避：不可见提示
  });

  it("clears the stale rejection hint once the share stops (no resurrection)", () => {
    const { view } = renderBar({ visual: visualState({ phase: "sharing", lastRejectedReason: "unknown_source" }) });
    expect(screen.getByTestId("realtime-share-rejected").textContent).toContain("重新开始共享");
    view.rerender(
      <RealtimeVoiceBar
        connectionState="ready"
        micEnabled={false}
        modality="voice_full"
        chainLabel="级联"
        onPress={vi.fn()}
        onRelease={vi.fn()}
        visual={visualState({ phase: "stopped", lastRejectedReason: null })}
      />,
    );
    expect(screen.queryByTestId("realtime-share-rejected")).toBeNull();
  });

  it("displays clarify question with aria-live and never auto-resends", () => {
    renderBar({ visual: visualState({ clarifyQuestion: "要问当前画面还是刚才那页？" }) });
    const clarify = screen.getByTestId("realtime-clarify");
    expect(clarify.getAttribute("aria-live")).toBe("polite");
    expect(clarify.textContent).toContain("当前画面");
  });

  it("shows 已绑定/仅预览 and pause states honestly", () => {
    const base = {
      connectionState: "ready" as const,
      micEnabled: false,
      modality: "voice_full" as const,
      chainLabel: "级联",
      onPress: vi.fn(),
      onRelease: vi.fn(),
    };
    const view = render(<RealtimeVoiceBar {...base} visual={visualState({ phase: "stopped", lastFrameBound: true, boundCount: 1 })} />);
    expect(screen.getByTestId("realtime-share-status").textContent).toContain("已绑定");
    view.rerender(<RealtimeVoiceBar {...base} visual={visualState({ phase: "sharing", samplingPaused: true })} />);
    expect(screen.getByTestId("realtime-share-status").textContent).toContain("采样已暂停");
  });
});
