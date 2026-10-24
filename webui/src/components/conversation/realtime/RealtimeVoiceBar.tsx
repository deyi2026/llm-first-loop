// M1/M3：对话区实时语音条组件（`T-M1-9` / `T-M3-3`）。
//
// 职责（RTM-AUD-06、A11Y-01/02/05、CAP-09/13）：
// - **按住说话**（按下开始采集、松开结束输入）；失焦/离开等同松开；
// - 显示连接状态与四事实之一（麦克风）；**标明实际链路**；
// - 语音不可用时**提供文字/截图降级入口**（不静默失效）；
// - 纯展示 + 交互，真实采集/播放由父组件经 `MicCapture`/`ScreenShareSession` 注入。

import { useCallback } from "react";

import type { ConnectionState } from "../../../core/realtime/mediaSessionClient";
import { FALLBACK_HINT, type ModalityMode } from "../../../core/realtime/modality";

export interface RealtimeVoiceBarProps {
  connectionState: ConnectionState;
  micEnabled: boolean;
  modality: ModalityMode;
  chainLabel: string;
  onPress: () => void;
  onRelease: () => void;
  onFallbackText?: () => void;
  disabled?: boolean;
  onClose?: () => void;
  transcript?: string;
  error?: string;
}

const STATE_LABEL: Record<ConnectionState, string> = {
  opening: "正在建立连接…",
  ready: "可以说话",
  reconnecting: "连接中断，重连中…",
  failed: "连接失败，请改用文字",
  closing: "正在结束…",
  closed: "已结束",
};

export function RealtimeVoiceBar({
  connectionState,
  micEnabled,
  modality,
  chainLabel,
  onPress,
  onRelease,
  onFallbackText,
  disabled,
  onClose, transcript, error,
}: RealtimeVoiceBarProps) {
  const canTalk = !disabled && modality !== "screenshot_fallback" && connectionState === "ready";

  const release = useCallback((): void => {
    onRelease();
  }, [onRelease]);

  return (
    <div className="realtime-voice-bar" data-testid="realtime-voice-bar" data-state={connectionState}>
      <button
        type="button"
        aria-label="按住说话"
        aria-pressed={micEnabled}
        disabled={!canTalk}
        data-testid="realtime-push-to-talk"
        onPointerDown={(event) => { event.currentTarget.setPointerCapture?.(event.pointerId); onPress(); }}
        onPointerCancel={release}
        onKeyDown={(event) => { if ((event.key === " " || event.key === "Enter") && !event.repeat) { event.preventDefault(); onPress(); } }}
        onKeyUp={(event) => { if (event.key === " " || event.key === "Enter") { event.preventDefault(); release(); } }}
        onPointerUp={release}
        onPointerLeave={release}
        onBlur={release}
      >
        按住说话
      </button>
      {onClose ? <button type="button" onClick={onClose}>关闭语音</button> : null}
      {transcript ? <span aria-live="polite">{transcript}</span> : null}
      {error ? <span role="alert">{error}</span> : null}
      {error?.includes("请重新登录") ? (
        <a href={`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}>
          重新登录
        </a>
      ) : null}
      <span data-testid="realtime-state">{STATE_LABEL[connectionState]}</span>
      <span data-testid="realtime-chain">{chainLabel}</span>
      <span data-testid="realtime-modality">{modality}</span>
      {modality !== "voice_full" ? (
        <span data-testid="realtime-fallback">{FALLBACK_HINT}</span>
      ) : null}
      {onFallbackText ? (
        <button type="button" data-testid="realtime-fallback-text" onClick={() => onFallbackText()}>
          改用文字输入
        </button>
      ) : null}
    </div>
  );
}