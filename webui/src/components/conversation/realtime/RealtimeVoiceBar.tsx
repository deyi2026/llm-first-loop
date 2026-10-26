// M1/M3：对话区实时语音条组件（`T-M1-9` / `T-M3-3`）。
//
// 职责（RTM-AUD-06、A11Y-01/02/05、CAP-09/13、RTM-VIS-01..09）：
// - **按住说话**（按下开始采集、松开结束输入）；失焦/离开等同松开；
// - 显示连接状态与四事实之一（麦克风）；**标明实际链路**；
// - 语音不可用时**提供文字/截图降级入口**（不静默失效）；
// - M3：共享画面入口（能力检测不过 → 隐藏按钮 + 文字/截图降级提示，不声称支持）；
//   共享中显示预览缩略图/状态/帧龄/源标签，**不隐藏停止入口**；kind 切换可见、可键盘操作；
//   `visual.clarify` 问题 aria-live 展示（不自动重发）；不展示任何伪造的画面理解结果；
// - 纯展示 + 交互，真实采集/播放/采样由父组件注入（`MicCapture`/`VisualShareController`）。

import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";

import type { ConnectionState } from "../../../core/realtime/mediaSessionClient";
import { FALLBACK_HINT, type ModalityMode } from "../../../core/realtime/modality";
import type { VisualRefKind } from "../../../core/realtime/visualShare";

export interface RealtimeVisualBarState {
  supported: boolean;
  phase: "idle" | "starting" | "sharing" | "stopped";
  sourceId: string | null;
  previewDataUrl: string | null;
  lastFrameAtMs: number | null;
  lastFrameBound: boolean;
  boundCount: number;
  samplingPaused: boolean;
  lastRejectedReason: string | null;
  kind: VisualRefKind;
  clarifyQuestion: string | null;
  /**
   * P2-9：当前存在可绑定的会话（false = 无会话，共享入口禁用 + 降级提示；
   * 缺省 true 向后兼容）。仅约束**开始**共享；共享中的停止入口永不禁用。
   */
  canShare?: boolean;
}

export type BarPlaybackState = "idle" | "synthesizing" | "playing" | "failed";

const PLAYBACK_LABEL: Record<BarPlaybackState, string> = {
  idle: "",
  synthesizing: "正在生成语音回复",
  playing: "正在播放语音回复",
  failed: "语音回复未播放",
};

export interface RealtimeVoiceBarProps {
  connectionState: ConnectionState;
  micEnabled: boolean;
  modality: ModalityMode;
  chainLabel: string;
  /** 87aa41fd2 语义移植：语音回复可见状态（缺省 idle = 不展示，向后兼容）。 */
  playbackState?: BarPlaybackState;
  /** 6a45f1741 语义移植：连接层错误（含 401 时展示同源重新登录入口）。 */
  error?: string;
  /** 87aa41fd2 语义移植：重试语音回复。 */
  onRetryPlayback?: () => void;
  /** 连接失败后的重试入口（重走 enable 建连；未提供则不展示该按钮）。 */
  onRetryConnection?: () => void;
  onPress: () => void;
  onRelease: () => void;
  onFallbackText?: () => void;
  disabled?: boolean;
  visual?: RealtimeVisualBarState;
  onStartShare?: () => void;
  onStopShare?: () => void;
  onSetVisualKind?: (kind: VisualRefKind) => void;
}

const STATE_LABEL: Record<ConnectionState, string> = {
  opening: "正在建立连接…",
  ready: "可以说话",
  reconnecting: "连接中断，重连中…",
  failed: "连接失败，请改用文字",
  closing: "正在结束…",
  closed: "已结束",
};

const SHARE_PHASE_LABEL: Record<RealtimeVisualBarState["phase"], string> = {
  idle: "未共享",
  starting: "正在开始共享…",
  sharing: "共享中",
  stopped: "已停止",
};

/** 按住说话的键盘触发键（A11Y-05：`event.key` 的空格为 " "，旧浏览器为 "Spacebar"）。 */
const HOLD_KEYS: ReadonlySet<string> = new Set([" ", "Spacebar", "Enter"]);

/** 有界中文拒绝提示（rate_limited 静默退避不在展示范围）。 */
const REJECT_LABEL: Record<string, string> = {
  unknown_source: "画面来源未登记，请重新开始共享",
  source_not_active: "共享已停止，画面来源不再活动",
  source_epoch_mismatch: "画面来源代次不匹配，请重新开始共享",
  mime_unsupported: "画面格式不受支持，该帧已跳过",
  frame_too_large: "画面过大，该帧已跳过",
  duplicate_frame_id: "重复帧已跳过",
  malformed: "帧数据无效，该帧已跳过",
  session_closed: "实时会话已关闭，画面链路不可用",
};

export function RealtimeVoiceBar({
  connectionState,
  micEnabled,
  modality,
  chainLabel,
  playbackState = "idle",
  error = "",
  onRetryPlayback,
  onRetryConnection,
  onPress,
  onRelease,
  onFallbackText,
  disabled,
  visual,
  onStartShare,
  onStopShare,
  onSetVisualKind,
}: RealtimeVoiceBarProps) {
  const canTalk = !disabled && modality !== "screenshot_fallback" && connectionState === "ready";

  // 未就绪时的按压即时反馈：disabled 语义保留（aria-disabled + 样式），
  // 但不再静默吞掉按压——按下即闪示原因（连接中/失败/会话结束等）。
  const [hint, setHint] = useState<string | null>(null);
  const hintTimerRef = useRef<number | null>(null);
  const showHint = useCallback((message: string) => {
    setHint(message);
    if (hintTimerRef.current !== null) {
      window.clearTimeout(hintTimerRef.current);
    }
    hintTimerRef.current = window.setTimeout(() => setHint(null), 1600);
  }, []);
  useEffect(
    () => () => {
      if (hintTimerRef.current !== null) {
        window.clearTimeout(hintTimerRef.current);
      }
    },
    [],
  );

  const blockedReason =
    modality === "screenshot_fallback"
      ? "当前环境不支持语音，请改用文字或截图"
      : connectionState === "opening" || connectionState === "reconnecting"
        ? "语音连接建立中，稍候即可按住说话"
        : connectionState === "failed"
          ? "语音连接失败：可点「重试连接」或改用文字输入"
          : connectionState === "closing" || connectionState === "closed"
            ? "语音会话已结束"
            : disabled
              ? "当前不可语音输入"
              : "";

  const talkLabel = micEnabled ? "正在聆听…松开发送" : canTalk ? "按住说话" : "语音未就绪";

  const release = useCallback((): void => {
    onRelease();
  }, [onRelease]);

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      if (!canTalk) {
        if (blockedReason !== "") {
          showHint(blockedReason);
        }
        return;
      }
      // Pointer capture：按住期间手指/鼠标滑出按钮不再被判定为松开
      //（此前 onPointerLeave 直接 release，触摸微滑即断，形同“没反应”）。
      event.currentTarget.setPointerCapture?.(event.pointerId);
      onPress();
    },
    [canTalk, blockedReason, onPress, showHint],
  );

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLButtonElement>) => {
      // A11Y-05：键盘按住 = keydown 开始、keyup 结束；
      // preventDefault 抑制 Space 滚屏与按键原生 click（避免与按住语义重复触发）。
      if (!HOLD_KEYS.has(event.key)) return;
      event.preventDefault();
      if (event.repeat) return; // 自动重复的 keydown 不重复开始采集
      if (!canTalk) {
        if (blockedReason !== "") {
          showHint(blockedReason);
        }
        return;
      }
      onPress();
    },
    [canTalk, blockedReason, onPress, showHint],
  );

  const sharing = visual?.phase === "sharing";
  const starting = visual?.phase === "starting";
  const shareActive = sharing || starting;
  // P2-9：无会话时只禁“开始共享”；共享已进行（starting/sharing）时保持停止入口可用
  const shareBlockedNoSession = visual?.canShare === false && !shareActive;
  const currentSelectable = sharing;
  const historySelectable = sharing || visual?.phase === "stopped";
  const stoppedWithCurrent = visual?.phase === "stopped" && visual.kind === "current";
  const frameAgeLabel =
    visual?.lastFrameAtMs !== null && visual?.lastFrameAtMs !== undefined && typeof performance !== "undefined"
      ? `${Math.max(0, (performance.now() - visual.lastFrameAtMs) / 1000).toFixed(1)}s`
      : "—";

  return (
    <div
      className="realtime-voice-bar"
      data-testid="realtime-voice-bar"
      data-state={connectionState}
      data-recording={micEnabled ? "true" : undefined}
      data-playback={playbackState !== "idle" ? playbackState : undefined}
    >
      <div className="realtime-voice-header">
        <span className="realtime-voice-status">
          <span className="realtime-voice-indicator" data-state={connectionState} aria-hidden="true" />
          <span data-testid="realtime-state">{STATE_LABEL[connectionState]}</span>
        </span>
        <span data-testid="realtime-chain">{chainLabel}</span>
        {playbackState !== "idle" ? (
          <span data-testid="realtime-playback" data-playback={playbackState} role="status">
            {PLAYBACK_LABEL[playbackState]}
          </span>
        ) : null}
      </div>
      <div className="realtime-voice-actions">
        {connectionState === "failed" && onRetryConnection ? (
          <button
            type="button"
            className="realtime-voice-retry"
            data-testid="realtime-retry-connection"
            onClick={() => onRetryConnection()}
          >
            重试连接
          </button>
        ) : null}
        <button
          type="button"
          aria-label="按住说话"
          aria-pressed={micEnabled}
          aria-disabled={!canTalk || undefined}
          className="realtime-voice-talk"
          data-testid="realtime-push-to-talk"
          data-state={canTalk ? "ready" : connectionState}
          onPointerDown={handlePointerDown}
          onPointerUp={release}
          onPointerLeave={release}
          onPointerCancel={release}
          onBlur={release}
          onContextMenu={(event) => event.preventDefault()}
          onKeyDown={handleKeyDown}
          onKeyUp={(event) => {
            if (!HOLD_KEYS.has(event.key)) return;
            release();
          }}
        >
          {talkLabel}
        </button>
        {playbackState === "failed" && connectionState === "ready" && onRetryPlayback ? (
          <button
            type="button"
            className="realtime-voice-retry"
            data-testid="realtime-retry-playback"
            onClick={() => onRetryPlayback()}
          >
            重试语音回复
          </button>
        ) : null}
        {onFallbackText ? (
          <button
            type="button"
            className="realtime-voice-close"
            data-testid="realtime-fallback-text"
            onClick={() => onFallbackText()}
          >
            改用文字输入
          </button>
        ) : null}
      </div>
      {error ? (
        <p className="realtime-voice-error" role="alert" data-testid="realtime-error">
          {error}
          {error.includes("请重新登录") ? (
            <>
              {" "}
              <a href={'/login?next=' + encodeURIComponent(window.location.pathname + window.location.search)}>
                重新登录
              </a>
            </>
          ) : null}
        </p>
      ) : null}
      {hint ? (
        <p className="realtime-voice-hint" role="status" data-testid="realtime-hint">
          {hint}
        </p>
      ) : null}
      <span data-testid="realtime-modality">{modality}</span>
      {modality !== "voice_full" ? (
        <span data-testid="realtime-fallback">{FALLBACK_HINT}</span>
      ) : null}
      {visual !== undefined && !visual.supported ? (
        <span data-testid="realtime-share-unsupported">
          当前环境不支持共享画面：可继续用文字输入或上传截图提问
        </span>
      ) : null}
      {visual !== undefined && visual.supported ? (
        <span className="realtime-share" data-testid="realtime-share">
          <button
            type="button"
            data-testid="realtime-share-toggle"
            aria-pressed={shareActive}
            aria-label={shareActive ? "停止共享画面" : "共享画面"}
            disabled={(!onStartShare && !onStopShare) || shareBlockedNoSession}
            onClick={() => (shareActive ? onStopShare?.() : onStartShare?.())}
          >
            {shareActive ? "停止共享" : "共享画面"}
          </button>
          {shareBlockedNoSession ? (
            <span data-testid="realtime-share-no-session" role="status">
              还没有打开的会话：先发送一条消息或选择会话，再共享画面
            </span>
          ) : null}
          <span data-testid="realtime-share-status" aria-live="polite">
            {SHARE_PHASE_LABEL[visual.phase]}
            {visual.phase === "sharing" || visual.phase === "stopped" ? (
              <>
                {visual.lastFrameBound ? "（已绑定）" : "（仅预览）"}
                {visual.samplingPaused ? "（采样已暂停）" : ""}
              </>
            ) : null}
          </span>
          {visual.sourceId !== null ? (
            <span data-testid="realtime-share-source">{visual.sourceId}</span>
          ) : null}
          {visual.phase === "sharing" ? (
            <span data-testid="realtime-share-frame-age">帧龄 {frameAgeLabel}</span>
          ) : null}
          {visual.previewDataUrl !== null ? (
            <img
              data-testid="realtime-share-preview"
              src={visual.previewDataUrl}
              alt="共享画面最新预览（客户端本地预览，非理解结果）"
              width={96}
            />
          ) : null}
          <span role="radiogroup" aria-label="视觉指代" data-testid="realtime-visual-kind">
            <label>
              <input
                type="radio"
                name="realtime-visual-kind"
                value="current"
                checked={visual.kind === "current"}
                disabled={!currentSelectable || onSetVisualKind === undefined}
                onChange={() => onSetVisualKind?.("current")}
                data-testid="realtime-visual-kind-current"
              />
              问当前画面
            </label>
            <label>
              <input
                type="radio"
                name="realtime-visual-kind"
                value="history"
                checked={visual.kind === "history"}
                disabled={!historySelectable || onSetVisualKind === undefined}
                onChange={() => onSetVisualKind?.("history")}
                data-testid="realtime-visual-kind-history"
              />
              问刚才那页
            </label>
          </span>
          {stoppedWithCurrent ? (
            <span data-testid="realtime-share-current-unavailable">
              共享已停止，“问当前画面”不可用；可改选“问刚才那页”或重新共享
            </span>
          ) : null}
          {visual.lastRejectedReason !== null &&
          visual.lastRejectedReason !== "rate_limited" &&
          visual.lastRejectedReason !== "cache_full" ? (
            <span data-testid="realtime-share-rejected" role="status">
              {REJECT_LABEL[visual.lastRejectedReason] ?? `画面帧被拒绝（${visual.lastRejectedReason}）`}
            </span>
          ) : null}
          {visual.clarifyQuestion !== null ? (
            <span data-testid="realtime-clarify" aria-live="polite">
              需要澄清：{visual.clarifyQuestion}
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}