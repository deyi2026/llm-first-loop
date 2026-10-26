// M1：把实时语音接入对话区的 React hook（`T-M1-9/10/12`）。
//
// 关键：浏览器**同源**访问 LFL Web（默认 8903）的 `/api/v1/realtime/*`，由**服务端**回环
// 代理到本机 `mlx-audio`（8000）。浏览器**不直连** 8000（SEC-08），
// 也避免把 `mlx-audio` 的端口误当作 LFL Web。
//
// 默认**不触发**任何浏览器媒体 API；仅在 `enable()` 后创建采集/播放/控制通道。
//
// M1 客户端闭环：
// - `turn.committed` 终稿 → `onCommittedTranscript`（由上层复用既有 sendMessage 提交，不另造路径）；
// - 语音终稿触发的回复在 streaming 结束后自动 `tts.request`（仅语音来源的回合；纯文本路径零变化）；
// - 降级提示经 `onNotice`（可见非阻塞）；组件卸载/disable 立即本地停播并释放连接。

import { useCallback, useEffect, useRef, useState } from "react";

import { conversationStore } from "../conversation";
import type { ConnectionState } from "./mediaSessionClient";
import { MediaSessionClient, type SocketLike } from "./mediaSessionClient";
import { MicCapture, type MediaDevicesLike } from "./micCapture";
import { PlaybackOutput, type AudioContextLike } from "./audioPlayback";
import { CapturePipeline } from "./capturePipeline";
import { PlaybackQueue } from "./playbackQueue";
import { RealtimeSessionController } from "./sessionController";
import { chainDisclosure, resolveModality, type ModalityMode } from "./modality";
import {
  VisualShareController,
  type FrameGrabber,
  type VisualRefKind,
  type VisualSharePhase,
  type VisualShareSnapshot,
} from "./visualShare";
import {
  detectScreenShareSupport,
  type DisplayMediaDevicesLike,
  type ScreenShareCapabilityEnv,
} from "./screenShare";
import type { MicPressErrorKind } from "./micCapture";

/** 采集失败 → 面向用户的可操作提示（分类驱动，避免裸报设备错误名）。 */
export function micPressErrorMessage(kind: MicPressErrorKind | null): string {
  switch (kind) {
    case "not-allowed":
      return "麦克风权限被拒绝：请在浏览器地址栏允许麦克风访问后重试";
    case "not-found":
      return "未检测到麦克风设备：请确认麦克风已连接后重试";
    case "not-readable":
      return "麦克风无法读取：可能被其他应用占用，请关闭占用后重试";
    default:
      return "麦克风启动失败：请检查设备与权限后重试";
  }
}

export interface RealtimeVoiceTransport {
  /** 建会话 REST（默认 `fetch`；测试注入）。 */
  fetchImpl?: typeof fetch;
  /** 控制通道 WS 工厂（默认浏览器 `WebSocket`；测试注入）。 */
  createSocket?: (url: string) => SocketLike;
  /** 播放 `AudioContext` 工厂（默认浏览器 `AudioContext`；测试注入）。 */
  createAudioContext?: () => AudioContextLike;
  /** M3：`getDisplayMedia` 工厂（默认浏览器 `navigator.mediaDevices`；测试注入）。 */
  getDisplayMedia?: DisplayMediaDevicesLike["getDisplayMedia"];
  /** M3：抓帧器工厂（默认 `CanvasFrameGrabber`；测试注入）。 */
  createGrabber?: () => FrameGrabber;
  /** M1 补充：worklet 端口工厂（测试注入以驱动采集帧）。 */
  createPort?: () => { onmessage: ((event: { data: { samples: Float32Array; sampleRate: number; channels?: number } }) => void) | null; close(): void };
}

export interface RealtimeVoiceVisualOptions {
  /** 采样间隔（契约 0.5–1fps → 1000–2000ms；默认 1000）。 */
  intervalMs?: number;
  /** 能力探测环境（测试注入）。 */
  supportEnv?: ScreenShareCapabilityEnv;
}

export interface RealtimeVoiceOptions {
  /**
   * 绑定的会话 id（响应式：由调用方随 store 订阅传入，切换后下次 `enable()` 生效）。
   * `null`/空串 = 当前无会话（P2-9）：**不伪造占位 id**——语音仍可用（enable 时生成
   * 一次性临时 id 满足服务端非空 opaque key 契约），但视觉共享被禁止（`canShare=false`）；
   * 语音终稿照旧走 sendMessage（无会话由服务端按新建会话处理，文本路径零变化）。
   */
  sessionId: string | null;
  /** `turn.committed` 终稿提交回调：上层应复用既有 sendMessage 路径（不新造第二套提交）。 */
  onCommittedTranscript?: (text: string, turnId: string) => void;
  /** 可见但非阻塞的降级提示（空终稿/发送失败/播放被拒等）。 */
  onNotice?: (message: string) => void;
  transport?: RealtimeVoiceTransport;
  visual?: RealtimeVoiceVisualOptions;
}

export interface RealtimeVisualWiring {
  /** 共享入口能力检测结果（不支持 → UI 隐藏按钮并给降级提示）。 */
  supported: boolean;
  /**
   * P2-9：允许启动视觉共享（false → UI 禁用共享入口并给降级提示；仅约束开始，不约束停止）。
   * P2-9c：进一步要求当前会话与 enable 时固定的媒体会话 identity 一致——无会话、
   * adhoc 临时 id（enable 时无会话）、已切换到别的会话、尚未 enable 均为 false。
   */
  canShare: boolean;
  phase: VisualSharePhase;
  sourceId: string | null;
  sourceEpoch: number | null;
  /** 最新预览缩略图（data URL；仅客户端展示，无帧为 null）。 */
  previewDataUrl: string | null;
  /** 最近上送帧的客户端单调时钟（帧龄计算）。 */
  lastFrameAtMs: number | null;
  lastFrameBound: boolean;
  boundCount: number;
  samplingPaused: boolean;
  lastRejectedReason: string | null;
  kind: VisualRefKind;
  /** 最近一次 `visual.clarify` 问题（展示后由用户改选重问；不自动重发）。 */
  clarifyQuestion: string | null;
}

export type PlaybackState = "idle" | "synthesizing" | "playing" | "failed";

export interface RealtimeVoiceWiring {
  enabled: boolean;
  connectionState: ConnectionState;
  micEnabled: boolean;
  modality: ModalityMode;
  chainLabel: string;
  visual: RealtimeVisualWiring;
  /** 87aa41fd2 语义移植：语音回复可见状态（生成中/播放中/未播放）。 */
  playbackState: PlaybackState;
  /** 87aa41fd2 语义移植：重试语音回复（原样重发最近一次 TTS 请求）。 */
  retryPlayback: () => void;
  /** 6a45f1741 语义移植：连接层错误（含 401 重新登录指引；空串 = 无错）。 */
  error: string;
  enable: () => Promise<boolean>;
  disable: () => void;
  press: () => void;
  release: () => void;
  interrupt: () => void;
  startShare: () => Promise<boolean>;
  stopShare: () => void;
  setVisualKind: (kind: VisualRefKind) => void;
}

function browserCaps(): { mic: boolean; screenShare: boolean } {
  if (typeof navigator === "undefined") {
    return { mic: false, screenShare: false };
  }
  const media = (navigator as unknown as { mediaDevices?: { getUserMedia?: unknown; getDisplayMedia?: unknown } }).mediaDevices;
  return {
    mic: Boolean(media?.getUserMedia),
    screenShare: Boolean(media?.getDisplayMedia),
  };
}

const IDLE_VISUAL_SNAPSHOT: VisualShareSnapshot = {
  phase: "idle",
  sourceId: null,
  sourceEpoch: null,
  previewDataUrl: null,
  lastFrameAtMs: null,
  lastFrameBound: false,
  boundCount: 0,
  sentFrames: 0,
  skippedFrames: 0,
  skippedIdentical: 0,
  samplingPaused: false,
  lastRejectedReason: null,
  kind: "current",
};

/**
 * P2-9：无会话时 enable 的一次性临时 id。服务端 `POST /sessions` 只要求非空 opaque key
 * （不校验对话会话存在性），但绝不能复用共享常量（旧 "local" 会跨标签页互踩 active
 * writer→409/take_over），也不得冒充对话会话 id。每次 enable 独立生成、随 DELETE 回收。
 */
function newAdhocRealtimeSessionId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return `realtime-adhoc-${uuid ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
}

export function useRealtimeVoice(options: RealtimeVoiceOptions): RealtimeVoiceWiring {
  const { sessionId } = options;
  const [enabled, setEnabled] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("closed");
  const [micEnabled, setMicEnabled] = useState(false);
  const [shareSupported] = useState(() => detectScreenShareSupport(options.visual?.supportEnv));
  const [clarifyQuestion, setClarifyQuestion] = useState<string | null>(null);
  const [, setVisualVersion] = useState(0);
  const controllerRef = useRef<RealtimeSessionController | null>(null);
  const visualRef = useRef<VisualShareController | null>(null);
  /** 当前播放输出（P2：teardown 时 `dispose()` 关闭其 AudioContext，不泄漏；未启用为 null）。 */
  const playbackRef = useRef<PlaybackOutput | null>(null);
  /** 当前媒体会话（disable/卸载时 fire-and-forget DELETE 回收；无会话为 null）。 */
  const mediaSessionIdRef = useRef<string | null>(null);
  /**
   * P2-9c：enable 时固定的会话 id（媒体会话 identity 的 `sessionId` 部分；无会话时为
   * adhoc 临时 id）。`canShare`/`startShare` 与"会话切换即停共享"守卫都以它与**当前**
   * 会话比对——identity 冻结于 enable，跨会话续传会把帧/视觉提交错投到旧会话。
   * disable/卸载清空。
   */
  const activeSessionIdRef = useRef<string | null>(null);
  /** 语音终稿提交后期待的回合：只有它触发 tts.request（纯文本路径不播报）。 */
  const voiceReplyPendingRef = useRef(false);
  // 87aa41fd2 语义移植：语音回复可见状态 + 连接层错误（401 等）。
  const [playbackState, setPlaybackState] = useState<PlaybackState>("idle");
  const [error, setError] = useState("");
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const caps = browserCaps();
  const modality = resolveModality(caps);
  const chain = chainDisclosure({ cascade: true }); // 本地栈为级联链路（ASR→LLM→TTS）

  const releaseServerSession = useCallback((): void => {
    // P1-2：本地立即关闭控制通道/停播；服务端会话用 keepalive DELETE 尽力回收。
    // fire-and-forget：失败不阻塞 UI、不抛错（服务端幂等 + reaper 兜底回收）。
    const mediaSessionId = mediaSessionIdRef.current;
    mediaSessionIdRef.current = null;
    if (mediaSessionId === null) {
      return;
    }
    const fetchImpl = optionsRef.current.transport?.fetchImpl ?? ((input: string, init?: RequestInit) => fetch(input, init));
    void fetchImpl(`/api/v1/realtime/sessions/${mediaSessionId}`, {
      method: "DELETE",
      keepalive: true,
    }).catch(() => undefined);
  }, []);

  const enable = useCallback(async (): Promise<boolean> => {
    if (controllerRef.current !== null) {
      setEnabled(true);
      return true;
    }
    const fetchImpl = optionsRef.current.transport?.fetchImpl ?? ((input: string, init?: RequestInit) => fetch(input, init));
    // P2-9：服务端契约要求非空 session_id；无会话（null/""）时用一次性临时 id，
    // 不再伪造共享常量 "local"。视觉共享另由 canShare/startShare 守卫禁止。
    const activeSessionId = sessionId || newAdhocRealtimeSessionId();
    try {
      const postSession = (takeOver: boolean) =>
        fetchImpl("/api/v1/realtime/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: activeSessionId, take_over: takeOver }),
        });
      let created = await postSession(false);
      if (created.status === 409) {
        // P1-2：已有活跃 writer（旧标签页残留等）→ 自动接管重试一次（仅一次）。
        created = await postSession(true);
      }
      if (created.status === 401) {
        // 6a45f1741 语义移植：登录态失效给出明确指引（语音条渲染重新登录入口）。
        setConnectionState("failed");
        setError("语音连接失败（HTTP 401）：登录状态已失效，请重新登录后重试");
        return false;
      }
      if (!created.ok) {
        setConnectionState("failed");
        setError("");
        optionsRef.current.onNotice?.("实时语音会话建立失败，可继续使用文字输入");
        return false;
      }
      setError("");
      const body = (await created.json()) as { media_session_id: string };
      mediaSessionIdRef.current = body.media_session_id;
      // P2-9c：记住 enable 时固定的会话 id（无会话时为上面的 adhoc 临时 id）。
      // visualController/sessionController 的 identity 已冻结为该值；canShare/startShare
      // 与会话切换守卫都以它与当前会话比对。
      activeSessionIdRef.current = activeSessionId;
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${scheme}://${window.location.host}/api/v1/realtime/sessions/${body.media_session_id}/events`;

      let clientRef: MediaSessionClient | null = null;
      let playbackOutput: PlaybackOutput | null = null;
      const noticedPlaybackFailures = new Set<string>();
      // 分片成为当前待播 → 触发播放（自然结束由 PlaybackOutput 自动接续）
      const playbackQueue = new PlaybackQueue(
        () => clientRef?.connectionEpoch ?? 1,
        () => {
          void playbackOutput?.playNext();
        },
      );
      const client = new MediaSessionClient({
        url,
        playback: playbackQueue,
        createSocket: optionsRef.current.transport?.createSocket
          ?? ((target: string) => new WebSocket(target) as unknown as SocketLike),
        onStateChange: (state) => setConnectionState(state),
        // P2-11：坏信封丢弃的有界可见上报（客户端每连接只回调一次，不逐帧刷屏）
        onProtocolError: () => {
          optionsRef.current.onNotice?.("实时通道收到无法解析的消息，该帧已丢弃（不影响后续对话）");
        },
      });
      clientRef = client;
      let controllerRefForCapture: RealtimeSessionController | null = null;
      const capture = new MicCapture({
        mediaDevices: navigator.mediaDevices as unknown as MediaDevicesLike,
        pipeline: new CapturePipeline({}),
        onFrame: (frame) => {
          controllerRefForCapture?.handleCapturedFrame(frame);
        },
        createPort: optionsRef.current.transport?.createPort
          ?? (() => ({ onmessage: null, close: () => undefined })),
      });
      const audioContext = optionsRef.current.transport?.createAudioContext
        ? optionsRef.current.transport.createAudioContext()
        : (new AudioContext() as unknown as AudioContextLike);
      playbackOutput = new PlaybackOutput({
        playback: playbackQueue,
        audioContext,
        onError: (_error, responseId) => {
          // autoplay 被拒/解码失败：按回复去重提示一次，不轰炸
          setPlaybackState("failed"); // 87aa41fd2：可见「未播放」状态 + 重试入口
          if (noticedPlaybackFailures.has(responseId)) return;
          noticedPlaybackFailures.add(responseId);
          optionsRef.current.onNotice?.("语音播报不可用（浏览器未授权自动播放），回复文本已保留在对话中");
        },
        onStart: () => setPlaybackState("playing"),
        onEnd: () => setPlaybackState("idle"),
      });
      playbackRef.current = playbackOutput; // P2：teardown（disable/卸载/装配失败）时 dispose
      // M3：视觉共享控制器（同一条控制通道；devices/grabber 注入，jsdom 下 fake 驱动）
      const displayDevices: DisplayMediaDevicesLike =
        optionsRef.current.transport?.getDisplayMedia !== undefined
          ? { getDisplayMedia: optionsRef.current.transport.getDisplayMedia }
          : (navigator.mediaDevices as unknown as DisplayMediaDevicesLike);
      const visualController = new VisualShareController({
        client,
        devices: displayDevices,
        identity: { sessionId: activeSessionId, mediaSessionId: body.media_session_id },
        createGrabber: optionsRef.current.transport?.createGrabber,
        intervalMs: optionsRef.current.visual?.intervalMs,
        sink: {
          onNotice: (message) => optionsRef.current.onNotice?.(message),
        },
      });
      visualController.onChange(() => setVisualVersion((version) => version + 1));
      visualRef.current = visualController;
      const controller = new RealtimeSessionController({
        client,
        capture,
        playback: playbackOutput,
        identity: { sessionId: activeSessionId, mediaSessionId: body.media_session_id },
        visual: visualController,
        sink: {
          onCommittedTranscript: (text, turnId) => {
            const wasStreaming = conversationStore.getState().streaming;
            optionsRef.current.onCommittedTranscript?.(text, turnId);
            // 会话空闲时提交的终稿 → 期待本轮回复合成播报；若上层因 streaming 延迟提交则不期待
            voiceReplyPendingRef.current = !wasStreaming;
          },
          onVisualTurnCommitted: (info) => {
            // 带视觉的 turn 由服务端提交任务：客户端不回投终稿，仅可见状态
            setClarifyQuestion(null);
            optionsRef.current.onNotice?.(
              `带画面的语音已提交（turn ${info.turnId}${info.taskRef !== null ? `，任务 ${info.taskRef}` : ""}）`,
            );
          },
          onVisualClarify: (question) => {
            setClarifyQuestion(question); // 只展示；用户改选后重新提问，不自动重发
          },
          onNotice: (message) => optionsRef.current.onNotice?.(message),
          onPlaybackUnavailable: () => setPlaybackState("failed"), // 87aa41fd2：合成失败可重试
        },
      });
      controllerRefForCapture = controller;
      controllerRef.current = controller;
      client.connect();
      setConnectionState(client.connectionState);
      setEnabled(true);
      return true;
    } catch {
      // P3：POST 成功但响应体解析/后续装配抛错时，已创建的媒体会话不得泄漏——
      // 尽力 fire-and-forget DELETE（失败静默，服务端 reaper 兜底）并清空 ref，
      // 防止下次 enable 覆盖后旧会话漏删；不得因清理失败改变既有错误提示。
      if (mediaSessionIdRef.current !== null) {
        releaseServerSession();
      }
      // 已构造的播放输出（AudioContext）同样释放，失败路径不留泄漏
      playbackRef.current?.dispose();
      playbackRef.current = null;
      setConnectionState("failed");
      optionsRef.current.onNotice?.("实时语音初始化失败，可继续使用文字输入");
      return false;
    }
  }, [releaseServerSession, sessionId]);

  const disable = useCallback((): void => {
    // 先停共享（可能发 share.stop），再关会话控制通道，释放播放输出（关闭
    // AudioContext），最后尽力回收服务端会话
    visualRef.current?.close();
    visualRef.current = null;
    controllerRef.current?.close();
    controllerRef.current = null;
    playbackRef.current?.dispose();
    playbackRef.current = null;
    releaseServerSession();
    activeSessionIdRef.current = null; // P2-9c：媒体会话 identity 随 teardown 清空（重新 enable 前共享不可用）
    voiceReplyPendingRef.current = false;
    setClarifyQuestion(null);
    setPlaybackState("idle");
    setError("");
    setEnabled(false);
    setMicEnabled(false);
    setConnectionState("closed");
  }, [releaseServerSession]);

  // 组件卸载：立即本地停播并释放（不等服务端确认）；共享同样停止并 close；
  // 服务端会话 fire-and-forget DELETE 回收（keepalive，失败由服务端 reaper 兜底）
  useEffect(() => {
    return () => {
      visualRef.current?.close();
      visualRef.current = null;
      controllerRef.current?.close();
      controllerRef.current = null;
      playbackRef.current?.dispose();
      playbackRef.current = null;
      releaseServerSession();
      activeSessionIdRef.current = null; // P2-9c：随 teardown 一并清空
    };
  }, [releaseServerSession]);

  // P2-9c：会话切换时**正在共享**则立即停止（丢弃，不跨会话续传）并提示一次。
  // 媒体会话 identity 冻结于 enable 时的会话 id；切到别的会话后续传，帧与视觉提交
  // 会静默错投到旧会话（服务端 probe 对仍存在的旧会话照样放行，比 409 更隐蔽）。
  // 仅作用于视觉链路：纯语音/未共享不做任何动作，也**不 disable 语音**。
  // sessionId 取自当前渲染值（deps 触发即最新事实），动作读 ref 避免闭包旧值。
  useEffect(() => {
    const visual = visualRef.current;
    const phase = visual?.snapshot.phase;
    if (visual === null || (phase !== "starting" && phase !== "sharing")) {
      return; // 未共享（含尚未 enable）：会话切换与共享无关
    }
    if (sessionId === activeSessionIdRef.current) {
      return; // 同一会话：identity 一致，正常续用
    }
    visual.stopShare();
    optionsRef.current.onNotice?.("会话已切换，已停止画面共享");
  }, [sessionId]);

  // 语音回合的回复完成后请求本地 TTS（仅 voiceReplyPending 的回合；同一回复只请求一次）。
  useEffect(() => {
    if (!enabled) {
      return; // 实时语音关闭：不订阅、零交互变化
    }
    let prevStreaming = conversationStore.getState().streaming;
    const unsubscribe = conversationStore.subscribe(() => {
      const state = conversationStore.getState();
      const wasStreaming = prevStreaming;
      prevStreaming = state.streaming;
      if (wasStreaming !== true || state.streaming !== false) {
        return;
      }
      if (!voiceReplyPendingRef.current) {
        return; // 非语音来源的回合（纯文本路径）：不播报
      }
      voiceReplyPendingRef.current = false;
      const controller = controllerRef.current;
      if (controller === null) {
        return;
      }
      // 最后一条 assistant 消息（streaming 占位已收敛为完成消息）；按消息键去重
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        const message = state.messages[i];
        if (message.role !== "assistant") continue;
        if (message.content.trim() === "") continue;
        const responseKey = `${String(message.ts ?? 0)}:${String(message.content.length)}`;
        if (controller.requestTts(message.content, responseKey)) {
          setPlaybackState("synthesizing"); // 87aa41fd2：合成中可见状态
        }
        return;
      }
    });
    return () => {
      unsubscribe();
    };
  }, [enabled]);

  const press = useCallback((): void => {
    const controller = controllerRef.current;
    if (controller === null) {
      return;
    }
    void controller.press().then((started) => {
      setMicEnabled(started);
      if (!started) {
        // 采集失败不得静默（此前只有 micEnabled=false，用户零反馈"按了没反应"）
        setError((previous) => (previous ? previous : micPressErrorMessage(controller.lastPressError)));
      }
    });
  }, []);

  const release = useCallback((): void => {
    setClarifyQuestion(null); // 新一轮提问：清除旧澄清（不自动重发）
    controllerRef.current?.release();
    setMicEnabled(false);
  }, []);

  const interrupt = useCallback((): void => {
    controllerRef.current?.interrupt();
  }, []);

  // 87aa41fd2 语义移植：重试语音回复——原样重发最近一次 TTS 请求。
  const retryPlayback = useCallback((): void => {
    if (controllerRef.current?.retryTts()) {
      setPlaybackState("synthesizing");
    }
  }, []);

  const startShare = useCallback(async (): Promise<boolean> => {
    // P2-9：无当前会话禁止启动视觉共享（不伪造会话 id；帧/任务无处归属）。
    // 读 optionsRef 拿到最新渲染值（会话切换后此处即为新事实）。
    // P2-9c：仅有会话还不够——当前会话必须等于 enable 时固定的媒体会话 identity
    // （adhoc 临时 id / 已切换会话时启动，帧与视觉提交会错投旧会话或被服务端拒收）。
    const currentSessionId = optionsRef.current.sessionId;
    if (!currentSessionId) {
      optionsRef.current.onNotice?.("还没有打开的会话：先发送一条消息或选择会话，再共享画面");
      return false;
    }
    if (currentSessionId !== activeSessionIdRef.current) {
      optionsRef.current.onNotice?.("画面共享需在当前会话内重新开启实时语音");
      return false;
    }
    const visual = visualRef.current;
    if (visual === null) {
      return false;
    }
    // P2-9c 时窗：`await getDisplayMedia`（选择器弹窗）期间用户可能已切换会话——
    // 此时 phase 仍为 idle，切换 effect no-op 不会替我们中止；故在轨道获取后、
    // 上送 `visual.share.start` 之前复查会话一致性：不一致立即释放轨道、不上送
    // 任何 share.start/帧（否则会以 enable 时冻结的旧 identity 错投旧会话）。
    return visual.startShare(() => {
      if (optionsRef.current.sessionId === activeSessionIdRef.current) {
        return true;
      }
      optionsRef.current.onNotice?.("会话已切换，未开始画面共享");
      return false;
    });
  }, []);

  const stopShare = useCallback((): void => {
    visualRef.current?.stopShare();
  }, []);

  const setVisualKind = useCallback((kind: VisualRefKind): void => {
    visualRef.current?.setKind(kind);
  }, []);

  const visualSnapshot = visualRef.current?.snapshot ?? IDLE_VISUAL_SNAPSHOT;

  return {
    enabled,
    connectionState,
    micEnabled,
    modality,
    chainLabel: chain.label,
    playbackState,
    retryPlayback,
    error,
    visual: {
      supported: shareSupported,
      // P2-9c：sessionId 非空 且 === enable 时固定的 identity（否则禁用共享入口，
      // UI 沿用既有 canShare=false 机制提示）。
      canShare: Boolean(optionsRef.current.sessionId) && optionsRef.current.sessionId === activeSessionIdRef.current,
      ...visualSnapshot,
      clarifyQuestion,
    },
    enable,
    disable,
    press,
    release,
    interrupt,
    startShare,
    stopShare,
    setVisualKind,
  };
}