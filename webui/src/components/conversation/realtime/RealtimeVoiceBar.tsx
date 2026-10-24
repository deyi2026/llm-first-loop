// Realtime voice is an independently visible surface above the composer.
// Tapping starts/stops the microphone on both touch and desktop; never treat
// pointer-up/blur as "stop" while async microphone permission is pending.

import type { ConnectionState } from "../../../core/realtime/mediaSessionClient";
import { FALLBACK_HINT, type ModalityMode } from "../../../core/realtime/modality";

export interface RealtimeVoiceBarProps {
  connectionState: ConnectionState;
  micEnabled: boolean;
  micStarting?: boolean;
  inputState?: "idle" | "recognizing" | "processing";
  playbackState?: "idle" | "synthesizing" | "playing" | "failed";
  modality: ModalityMode;
  chainLabel: string;
  onPress: () => void;
  onRelease: () => void;
  onFallbackText?: () => void;
  disabled?: boolean;
  onClose?: () => void;
  onRetry?: () => void;
  onRetryPlayback?: () => void;
  onInterrupt?: () => void;
  transcript?: string;
  error?: string;
}

const STATE_LABEL: Record<ConnectionState, string> = {
  opening: "正在连接语音，连接后自动开始收音…",
  ready: "语音已就绪 · 麦克风未开启",
  reconnecting: "连接中断，重连中…",
  failed: "连接失败，请改用文字",
  closing: "正在结束…",
  closed: "已结束",
};

export function RealtimeVoiceBar({
  connectionState,
  micEnabled,
  micStarting = false,
  inputState = "idle",
  playbackState = "idle",
  modality,
  chainLabel,
  onPress,
  onRelease,
  onFallbackText,
  disabled,
  onClose, onRetry, onRetryPlayback, onInterrupt, transcript, error,
}: RealtimeVoiceBarProps) {
  const capturing = micEnabled || micStarting;
  const inputPending = inputState !== "idle";
  const canTalk = capturing || (!disabled && !inputPending && modality !== "screenshot_fallback" && connectionState === "ready");
  const status = micEnabled ? "正在听你说话 · 点击结束并发送"
    : micStarting ? "等待麦克风权限…"
    : inputState === "recognizing" ? "正在识别刚才的语音…"
    : inputState === "processing" ? "LFL 正在回复 · 完成后自动播报"
    : playbackState === "playing" ? "正在播放语音回复"
    : playbackState === "synthesizing" ? "正在生成语音回复…"
    : playbackState === "failed" ? "语音回复未播放"
    : STATE_LABEL[connectionState];
  const actionLabel = micEnabled ? "结束并发送"
    : micStarting ? "取消收音"
    : inputState === "recognizing" ? "正在识别…"
    : inputState === "processing" ? "等待回复…"
    : connectionState === "opening" || connectionState === "reconnecting" ? "正在连接…"
    : connectionState === "failed" ? "暂不可用"
    : playbackState === "playing" || playbackState === "synthesizing" ? "打断并说话"
    : "开始说话";
  const guidance = micEnabled ? "麦克风已打开；说完后点击结束并发送"
    : micStarting ? "请在浏览器中允许麦克风访问"
    : inputState === "recognizing" ? "语音已收下，正在生成文字"
    : inputState === "processing" ? "当前问题仍在处理，请等待回复后继续下一轮"
    : playbackState === "playing" ? "点击打断并说话可输入下一轮；停止播报只关闭当前声音"
    : playbackState === "synthesizing" ? "文字回答已生成，正在合成并准备播放"
    : playbackState === "failed" ? "文字回答仍保留；可以重试语音回复"
    : connectionState === "opening" || connectionState === "reconnecting" ? "无需再次点击，连接后会自动开始收音"
    : disabled ? "当前任务仍在处理，结束后可继续语音"
    : "分轮语音对话：点击开始说话，说完点击结束并发送；每轮回复会自动播报";

  return (
    <section
      className="realtime-voice-bar"
      aria-label="实时语音控制"
      data-testid="realtime-voice-bar"
      data-state={connectionState}
      data-playback={playbackState}
      data-input={inputState}
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
        {onFallbackText ? (
          <button type="button" data-testid="realtime-fallback-text" onClick={onFallbackText}>
            改用文字输入
          </button>
        ) : null}
        {(playbackState === "playing" || playbackState === "synthesizing") && onInterrupt ? (
          <button type="button" className="realtime-voice-retry" onClick={onInterrupt}>停止播报</button>
        ) : null}
        {connectionState === "failed" && onRetry ? (
          <button type="button" className="realtime-voice-retry" onClick={onRetry}>重新连接</button>
        ) : null}
        {playbackState === "failed" && connectionState === "ready" && onRetryPlayback ? (
          <button type="button" className="realtime-voice-retry" onClick={onRetryPlayback}>重试语音回复</button>
        ) : null}
      </div>
      {transcript ? <p className="realtime-voice-transcript" aria-live="polite">{transcript}</p> : null}
      {error ? <p className="realtime-voice-error" role="alert">{error}</p> : null}
      {error?.includes("请重新登录") ? (
        <a href={`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`}>
          重新登录
        </a>
      ) : null}
      <details className="realtime-voice-details">
        <summary>语音连接信息</summary>
        <span data-testid="realtime-chain">{chainLabel}</span>
        <span className="realtime-voice-modality" data-testid="realtime-modality">{modality}</span>
        {modality !== "voice_full" ? (
          <span data-testid="realtime-fallback">{FALLBACK_HINT}</span>
        ) : null}

      </details>
    </section>
  );
}