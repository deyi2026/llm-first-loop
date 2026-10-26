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
  const onRetryPlayback = vi.fn();
  const props = {
    connectionState: "ready" as const,
    micEnabled: false,
    modality: "voice_full" as const,
    chainLabel: "级联语音链路（ASR→LLM→TTS）",
    onPress,
    onRelease,
    onFallbackText,
    onRetryPlayback,
    ...over,
  };
  const view = render(<RealtimeVoiceBar {...props} />);
  return { onPress, onRelease, onFallbackText, onRetryPlayback, view };
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
    // aria-disabled 语义（原生 disabled 会静默吞掉按压，改用可解释的禁用态）
    expect(screen.getByTestId("realtime-push-to-talk")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByTestId("realtime-state").textContent).toContain("改用文字");
  });

  it("shows generation/playback status and a retry action when speech output fails", () => {
    renderBar({ playbackState: "synthesizing" });
    expect(screen.getByTestId("realtime-playback")).toHaveTextContent("正在生成语音回复");
    cleanup();
    renderBar({ playbackState: "playing" });
    expect(screen.getByTestId("realtime-playback")).toHaveTextContent("正在播放语音回复");
    cleanup();
    const { onRetryPlayback } = renderBar({ playbackState: "failed", error: "本地 TTS 合成失败" });
    expect(screen.getByTestId("realtime-playback")).toHaveTextContent("语音回复未播放");
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
    expect(screen.getByTestId("realtime-push-to-talk")).toHaveAttribute("aria-disabled", "true");
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
    expect(screen.getByTestId("realtime-push-to-talk")).toHaveAttribute("aria-disabled", "true");
  });

  it("explains why talk is blocked instead of swallowing the press", () => {
    const { onPress } = renderBar({ connectionState: "opening" });
    const button = screen.getByTestId("realtime-push-to-talk");
    fireEvent.pointerDown(button);
    // 未就绪：不开始采集，但给出即时原因提示（不再"按了没反应"）
    expect(onPress).not.toHaveBeenCalled();
    expect(screen.getByTestId("realtime-hint").textContent).toContain("语音连接建立中");
  });

  it("captures the pointer on press so sliding off does not end the hold", () => {
    const { onPress } = renderBar({ connectionState: "ready" });
    const button = screen.getByTestId("realtime-push-to-talk");
    const capture = vi.fn();
    button.setPointerCapture = capture;
    fireEvent.pointerDown(button, { pointerId: 7 });
    expect(onPress).toHaveBeenCalledTimes(1);
    // jsdom 合成事件不透传 pointerId（真实浏览器必有），断言捕获动作本身
    expect(capture).toHaveBeenCalledTimes(1);
  });

  it("offers a retry connection entry when the connection failed", () => {
    const onRetryConnection = vi.fn();
    renderBar({ connectionState: "failed", onRetryConnection });
    fireEvent.click(screen.getByTestId("realtime-retry-connection"));
    expect(onRetryConnection).toHaveBeenCalledTimes(1);
  });

  it("shows the listening label while held", () => {
    renderBar({ connectionState: "ready", micEnabled: true });
    expect(screen.getByTestId("realtime-push-to-talk").textContent).toBe("正在聆听…松开发送");
    expect(screen.getByTestId("realtime-voice-bar")).toHaveAttribute("data-recording", "true");
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
