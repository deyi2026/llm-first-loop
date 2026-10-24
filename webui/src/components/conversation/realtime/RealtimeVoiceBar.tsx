// Realtime voice is an independently visible surface above the composer.
// Tapping starts/stops the microphone on both touch and desktop; never treat
// pointer-up/blur as "stop" while async microphone permission is pending.

import type { ConnectionState } from "../../../core/realtime/mediaSessionClient";
import { FALLBACK_HINT, type ModalityMode } from "../../../core/realtime/modality";

export interface RealtimeVoiceBarProps {
  connectionState: ConnectionState;
  micEnabled: boolean;
  micStarting?: boolean;
  modality: ModalityMode;
  chainLabel: string;
  onPress: () => void;
  onRelease: () => void;
  onFallbackText?: () => void;
  disabled?: boolean;
  onClose?: () => void;
  onRetry?: () => void;
  transcript?: string;
  error?: string;
}

const STATE_LABEL: Record<ConnectionState, string> = {
  opening: "正在连接语音，连接后自动开始收音…",
  ready: "已连接 · 麦克风未开启",
  reconnecting: "连接中断，重连中…",
  failed: "连接失败，请改用文字",
  closing: "正在结束…",
  closed: "已结束",
};

export function RealtimeVoiceBar({
  connectionState,
  micEnabled,
  micStarting = false,
  modality,
  chainLabel,
  onPress,
  onRelease,
  onFallbackText,
  disabled,
  onClose, onRetry, transcript, error,
}: RealtimeVoiceBarProps) {
  const capturing = micEnabled || micStarting;
  const canTalk = capturing || (!disabled && modality !== "screenshot_fallback" && connectionState === "ready");
  const status = micEnabled
    ? "正在语音输入 · 点击结束并发送"
    : micStarting
      ? "等待麦克风权限…"
      : STATE_LABEL[connectionState];
  const actionLabel = micEnabled
    ? "结束并发送"
    : micStarting
      ? "取消收音"
      : connectionState === "opening" || connectionState === "reconnecting"
        ? "正在连接…"
        : connectionState === "failed"
          ? "暂不可用"
          : "开始说话";
  const guidance = micEnabled
    ? "麦克风已打开"
    : micStarting
      ? "请在浏览器中允许麦克风访问"
      : connectionState === "opening" || connectionState === "reconnecting"
        ? "无需再次点击，连接后会自动开始收音"
        : "点击开始说话，再点击结束并发送";

  return (
    <section
      className="realtime-voice-bar"
      aria-label="实时语音控制"
      data-testid="realtime-voice-bar"
      data-state={connectionState}
      data-recording={micEnabled ? "true" : "false"}
    >
      <div className="realtime-voice-header">
        <div className="realtime-voice-status" role="status" aria-live="polite">
          <span className="realtime-voice-indicator" aria-hidden="true" />
          <span data-testid="realtime-state">{status}</span>
        </div>
        {onClose ? (
          <button className="realtime-voice-close" type="button" aria-label="关闭语音" onClick={onClose}>
            × 关闭语音
          </button>
        ) : null}
      </div>
      <div className="realtime-voice-actions">
        <button
          className="realtime-voice-talk"
          type="button"
          aria-pressed={capturing}
          disabled={!canTalk}
          data-testid="realtime-push-to-talk"
          onClick={() => { if (capturing) onRelease(); else onPress(); }}
        >
          {actionLabel}
        </button>
        <span className="realtime-voice-guidance">{guidance}</span>
        {connectionState === "failed" && onRetry ? (
          <button type="button" className="realtime-voice-retry" onClick={onRetry}>重新连接</button>
        ) : null}
      </div>
      {transcript ? <p className="realtime-voice-transcript" aria-live="polite">{transcript}</p> : null}
      {error ? <p className="realtime-voice-error" role="alert">{error}</p> : null}
      {error?.includes("请重新登录") ? (
        <a href={`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}>
          重新登录
        </a>
      ) : null}
      <div className="realtime-voice-details">
        <span data-testid="realtime-chain">{chainLabel}</span>
        <span className="realtime-voice-modality" data-testid="realtime-modality">{modality}</span>
        {modality !== "voice_full" ? (
          <span data-testid="realtime-fallback">{FALLBACK_HINT}</span>
        ) : null}
        {onFallbackText ? (
          <button type="button" data-testid="realtime-fallback-text" onClick={onFallbackText}>
            改用文字输入
          </button>
        ) : null}
      </div>
    </section>
  );
}