// M3：视觉共享链路控制器（`T-M3-1/2/3`，契约 docs/M3-KEYFRAME-WIRE-CONTRACT.md）。
//
// 职责（RTM-VIS-01..09、RET-04、SES-04、OBS-02）：
// - 用户手势 `getDisplayMedia({video:true,audio:false})`，仅采集**显式选择的源**；
// - 稳定 `source_id` + 页面生命周期内递增 `source_epoch`（同 id 重共享必须 +1）；
// - `visual.share.start → visual.frame… → input.commit{visual} → visual.share.stop` 时序；
// - 采样 0.5–1fps（可配置区间 1000–2000ms），JPEG ≤1280 长边、quality≈0.7，跳过完全相同画面；
// - `registered` 记录 content_ref→frame_id（可回读）；`rejected` 按错误码有界提示
//   （rate_limited 静默退避、cache_full 暂停采样并提示）；
// - 本地预览环形缓冲（默认 6 帧）**只淘汰未绑定预览帧**；停止/卸载停轨道、发 share.stop、
//   清预览与帧映射，之后**绝不再发帧**；
// - 日志/状态/快照**不携带 data_b64**（RET-05）；预览缩略图仅客户端展示。
//
// 依赖全部注入（devices/grabber/scheduler/clock），jsdom 下以 fake 验证接线；真实设备不在此验证。

import { PreviewBuffer } from "./keyframeSampling";
import {
  ScreenShareSession,
  type DisplayMediaDevicesLike,
  type DisplayStreamLike,
} from "./screenShare";
import {
  REALTIME_PROTOCOL_VERSION,
  type RealtimeEnvelope,
  type VisualCommitRef,
} from "./realtimeEvents";

export type VisualSharePhase = "idle" | "starting" | "sharing" | "stopped";
export type VisualRefKind = "current" | "history";

/** 控制器所需的最小客户端面（`MediaSessionClient` 子集；测试注入 fake）。 */
export interface VisualShareClient {
  connectionState: string;
  connectionEpoch: number;
  sendEvent(envelope: RealtimeEnvelope): boolean;
  onEvent(listener: (event: RealtimeEnvelope) => void): void;
}

export interface GrabbedFrame {
  dataB64: string;
  width: number;
  height: number;
  mime: "image/jpeg";
}

/** 可注入抓帧器：失败返回 null（跳过并计数，不崩溃）。 */
export interface FrameGrabber {
  grab(stream: DisplayStreamLike): Promise<GrabbedFrame | null>;
  close?(): void;
}

export interface VisualShareSink {
  onNotice?: (message: string) => void;
}

export interface VisualShareSnapshot {
  phase: VisualSharePhase;
  sourceId: string | null;
  sourceEpoch: number | null;
  /** 最新预览缩略图（data URL，仅客户端展示；无帧为 null）。 */
  previewDataUrl: string | null;
  /** 最近一次上送帧的客户端单调时钟（仅帧龄计算）。 */
  lastFrameAtMs: number | null;
  /** 最近一帧是否已绑定（registered；false=仅预览）。 */
  lastFrameBound: boolean;
  boundCount: number;
  sentFrames: number;
  skippedFrames: number;
  skippedIdentical: number;
  samplingPaused: boolean;
  lastRejectedReason: string | null;
  kind: VisualRefKind;
}

export interface VisualShareDeps {
  client: VisualShareClient;
  devices: DisplayMediaDevicesLike;
  identity: { sessionId: string; mediaSessionId: string };
  createGrabber?: () => FrameGrabber;
  nowMs?: () => number;
  schedule?: (fn: () => void, ms: number) => () => void;
  /** 采样间隔（契约 0.5–1fps → 1000–2000ms；默认 1000）。 */
  intervalMs?: number;
  maxPreviews?: number;
  sink?: VisualShareSink;
  label?: string;
}

const MIN_INTERVAL_MS = 1000; // 1fps 上限节奏
const MAX_INTERVAL_MS = 2000; // 0.5fps 下限节奏（退避不超过此值）
const DEFAULT_INTERVAL_MS = 1000;
const DEFAULT_MAX_PREVIEWS = 6;
const MAX_JPEG_LONG_EDGE = 1280;
const JPEG_QUALITY = 0.7;
/** P2-10：同一拒绝码的重复提示节流窗口（如 duplicate_frame_id 每跳都拒）。 */
const REJECT_NOTICE_THROTTLE_MS = 5000;

/** 契约 §5 拒绝码 → 有界中文提示（rate_limited 静默退避、cache_full 暂停采样，均不在此表）。 */
const REJECT_NOTICES: Record<string, string> = {
  unknown_source: "画面来源未登记，请重新开始共享",
  source_not_active: "共享已停止，画面来源不再活动",
  source_epoch_mismatch: "画面来源代次不匹配，请重新开始共享",
  mime_unsupported: "画面格式不受支持，该帧已跳过",
  frame_too_large: "画面过大，该帧已跳过",
  duplicate_frame_id: "重复帧已跳过",
  malformed: "帧数据无效，该帧已跳过",
  session_closed: "实时会话已关闭，画面链路不可用",
};

// ---- 模块级来源台账（页面生命周期内持久；刷新后从 1 重新开始，契约允许）----
let pageSourceId: string | null = null;
const sourceEpochLedger = new Map<string, number>();

/** 稳定来源标识：同一页面生命周期内所有重共享复用同一 id。 */
export function stableShareSourceId(): string {
  if (pageSourceId === null) {
    const random =
      globalThis.crypto?.randomUUID?.() ??
      `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    pageSourceId = `share-${random}`;
  }
  return pageSourceId;
}

/** 同一来源的下一次代次（从 1 起严格递增；重共享必须 +1，契约 §2.1）。 */
export function nextSourceEpoch(sourceId: string): number {
  const next = (sourceEpochLedger.get(sourceId) ?? 0) + 1;
  sourceEpochLedger.set(sourceId, next);
  return next;
}

/** 测试隔离：重置模块级来源台账。 */
export function resetShareSourceLedgerForTests(): void {
  pageSourceId = null;
  sourceEpochLedger.clear();
}

interface FrameRecord {
  frameId: string;
  capturedAtMs: number;
  dataUrl: string;
  bound: boolean;
  contentRef: string | null;
}

export class VisualShareController {
  private phase: VisualSharePhase = "idle";
  private kind: VisualRefKind = "current";
  private readonly session: ScreenShareSession;
  private readonly grabber: FrameGrabber;
  private readonly nowMs: () => number;
  private readonly schedule: (fn: () => void, ms: number) => () => void;
  private readonly baseIntervalMs: number;
  private readonly previews: PreviewBuffer;
  private readonly records = new Map<string, FrameRecord>();
  /** content_ref → frame_id（registered；绑定帧可回读）。 */
  private readonly contentRefs = new Map<string, string>();

  private shareSourceId: string | null = null;
  private registeredEpoch: number | null = null;
  private label: string | null;
  private lastSentB64: string | null = null;
  private lastCapturedMs = 0;
  private frameSeq = 0;
  private seq = 0;
  private eventIdCounter = 0;
  private cancelNext: (() => void) | null = null;
  private tickInFlight = false;
  private rateBackoffFactor = 1;
  private paused = false;
  private sentFrames = 0;
  private skippedFrames = 0;
  private skippedIdentical = 0;
  private boundCount = 0;
  private lastFrameAtMs: number | null = null;
  private lastFrameBound = false;
  private lastRejectedReason: string | null = null;
  /** P2-10：拒绝码 → 最近一次提示的时刻（节流窗口内同类只提示一次）。 */
  private readonly lastRejectedNoticeAtMs = new Map<string, number>();
  private endedHandler: (() => void) | null = null;
  private readonly listeners: (() => void)[] = [];

  constructor(private readonly deps: VisualShareDeps) {
    this.session = new ScreenShareSession(deps.devices, { video: true, audio: false });
    this.grabber = deps.createGrabber?.() ?? new CanvasFrameGrabber();
    this.nowMs = deps.nowMs ?? (() => performance.now());
    this.schedule =
      deps.schedule ?? ((fn, ms) => {
        const timer = setTimeout(fn, ms);
        return () => clearTimeout(timer);
      });
    const interval = deps.intervalMs ?? DEFAULT_INTERVAL_MS;
    if (!Number.isInteger(interval) || interval < MIN_INTERVAL_MS || interval > MAX_INTERVAL_MS) {
      throw new Error(`intervalMs must be within ${MIN_INTERVAL_MS}-${MAX_INTERVAL_MS} (contract 0.5-1fps)`);
    }
    this.baseIntervalMs = interval;
    this.previews = new PreviewBuffer(deps.maxPreviews ?? DEFAULT_MAX_PREVIEWS);
    this.label = deps.label ?? null;
    deps.client.onEvent((event) => this.handleEvent(event));
  }

  get snapshot(): VisualShareSnapshot {
    const latestId = this.previews.takeLatest();
    const latest = latestId !== null ? this.records.get(latestId) ?? null : null;
    return {
      phase: this.phase,
      sourceId: this.shareSourceId,
      sourceEpoch: this.registeredEpoch,
      previewDataUrl: latest?.dataUrl ?? null,
      lastFrameAtMs: this.lastFrameAtMs,
      lastFrameBound: this.lastFrameBound,
      boundCount: this.boundCount,
      sentFrames: this.sentFrames,
      skippedFrames: this.skippedFrames,
      skippedIdentical: this.skippedIdentical,
      samplingPaused: this.paused,
      lastRejectedReason: this.lastRejectedReason,
      kind: this.kind,
    };
  }

  onChange(listener: () => void): () => void {
    this.listeners.push(listener);
    return () => {
      const index = this.listeners.indexOf(listener);
      if (index !== -1) {
        this.listeners.splice(index, 1);
      }
    };
  }

  setKind(kind: VisualRefKind): void {
    if (this.kind === kind) {
      return;
    }
    this.kind = kind;
    this.emit();
  }

  /**
   * 提交时的视觉指代（供 `input.commit.visual`）：
   * - 共享中（started ack）→ 按 UI 选择 current/history；
   * - 已停止且选 history → 仍可绑定（契约 §3：history 指代可在 stop 后使用）；
   * - 已停止仍选 current → 不附带（提示），其余 → null。
   */
  commitVisual(): VisualCommitRef | null {
    if (this.phase === "sharing" && this.shareSourceId !== null) {
      return { source_id: this.shareSourceId, kind: this.kind };
    }
    if (this.phase === "stopped" && this.shareSourceId !== null) {
      if (this.kind === "history") {
        return { source_id: this.shareSourceId, kind: "history" };
      }
      this.notify("共享已停止，“问当前画面”不可用；本轮未附带画面（可改选“问刚才那页”或重新共享）");
      return null;
    }
    return null;
  }

  /**
   * 用户手势开始共享（`getDisplayMedia` → share.start；等待 started ack）。
   *
   * @param shouldContinue 可选「继续判定」：在 `getDisplayMedia` resolve 之后、发送
   *   `visual.share.start` **之前**调用一次。返回 false（如等待选择器弹窗期间外部
   *   条件已失效：会话切换/disable）时立即停轨道释放资源并返回 false——**不上送
   *   任何 share.start/帧**，避免以过期 identity 错投旧会话。
   */
  async startShare(shouldContinue?: () => boolean): Promise<boolean> {
    if (this.phase !== "idle" && this.phase !== "stopped") {
      return false;
    }
    const sourceId = stableShareSourceId();
    const started = await this.session.start(sourceId);
    if (!started) {
      this.notify("未获得共享画面（用户取消或浏览器不支持），可继续用文字或截图提问");
      return false;
    }
    if (shouldContinue !== undefined && !shouldContinue()) {
      // 等待选择器期间外部条件已失效：立即停轨道释放资源，不上送任何事件
      //（share.start/帧会以 enable 时冻结的旧 identity 错投旧会话，且此后切换
      // 守卫对已进入 starting/sharing 的阶段才有动作——迟到的停止不如不开始）。
      this.session.stop();
      return false;
    }
    const epoch = nextSourceEpoch(sourceId);
    this.shareSourceId = sourceId;
    this.registeredEpoch = epoch;
    this.lastSentB64 = null;
    this.lastCapturedMs = 0;
    this.lastFrameAtMs = null;
    this.lastFrameBound = false;
    this.paused = false;
    this.lastRejectedReason = null;
    this.lastRejectedNoticeAtMs.clear(); // 新源：拒绝提示节流窗口重置
    this.rateBackoffFactor = 1;
    this.phase = "starting";
    this.attachEndedListener();
    this.emit();
    if (
      !this.sendShareEvent(
        "visual.share.start",
        {
          source_id: sourceId,
          source_epoch: epoch,
          ...(this.label !== null ? { label: this.label } : {}),
        },
      )
    ) {
      // 发送失败：如实回到 idle（本地已停轨道），不伪装“共享中”
      this.stopLocal("共享开始请求发送失败，请重试");
      return false;
    }
    return true;
  }

  /** 停止共享：停轨道 → 发 share.stop → 清本地预览与帧映射；之后绝不再发帧。 */
  stopShare(): void {
    if (this.phase === "idle" || this.phase === "stopped") {
      return;
    }
    const sourceId = this.shareSourceId;
    const epoch = this.registeredEpoch;
    this.cancelLoop();
    this.detachEndedListener();
    this.session.stop();
    this.clearLocalFrames();
    this.lastRejectedReason = null; // 拒绝提示随源停用清空（start/stop/源变更三处一致，rate_limited 静默语义不变）
    this.phase = "stopped";
    this.emit();
    if (sourceId !== null && epoch !== null) {
      if (!this.sendShareEvent("visual.share.stop", { source_id: sourceId, source_epoch: epoch })) {
        this.notify("停止共享请求未送达（连接不可用）；服务端将在断连时按契约隐式 stop");
      }
    }
  }

  /** 组件卸载/会话关闭：停止并释放（不发帧、不留轨道）。 */
  close(): void {
    this.stopShare();
    this.grabber.close?.();
    this.phase = "idle";
    this.shareSourceId = null;
    this.registeredEpoch = null;
    this.listeners.length = 0;
  }

  private handleEvent(envelope: RealtimeEnvelope): void {
    if (envelope.type === "visual.share.started") {
      if (
        this.phase === "starting" &&
        envelope.source_id === this.shareSourceId &&
        envelope.source_epoch === this.registeredEpoch
      ) {
        this.phase = "sharing";
        this.emit();
        this.scheduleNext();
      }
      return;
    }
    if (envelope.type === "visual.share.stopped") {
      if (this.phase === "starting" || this.phase === "sharing") {
        // 服务端确认/对端停止：本地同步停止（幂等）
        this.cancelLoop();
        this.detachEndedListener();
        this.session.stop();
        this.clearLocalFrames();
        this.lastRejectedReason = null; // 源已停用：清空拒绝提示
        this.phase = "stopped";
        this.emit();
      }
      return;
    }
    if (envelope.type === "visual.frame.registered") {
      this.handleRegistered(envelope);
      return;
    }
    if (envelope.type === "visual.frame.rejected") {
      this.handleRejected(envelope);
      return;
    }
    if (envelope.type === "error" && this.phase === "starting") {
      // share.start 被严格拒绝（信封/epoch/装配失败）：如实回到 idle
      this.stopLocal(`共享开始被拒绝（${String(envelope.code ?? "?")} ${String(envelope.reason ?? "")}）`);
    }
  }

  private handleRegistered(envelope: RealtimeEnvelope): void {
    const frameId = envelope.frame_id;
    const contentRef = envelope.content_ref;
    if (typeof frameId !== "string" || typeof contentRef !== "string") {
      return;
    }
    this.contentRefs.set(contentRef, frameId);
    const record = this.records.get(frameId);
    if (record !== undefined && !record.bound) {
      record.bound = true;
      record.contentRef = contentRef;
      this.boundCount += 1;
    }
    this.lastFrameBound = true;
    this.rateBackoffFactor = 1; // 注册成功：恢复正常采样节奏
    this.emit();
  }

  private handleRejected(envelope: RealtimeEnvelope): void {
    // 仅共享中的拒绝有效：停止/未开始阶段的迟到拒绝不得复活过期提示
    if (this.phase !== "sharing") {
      return;
    }
    const reason = typeof envelope.reason === "string" ? envelope.reason : "malformed";
    this.lastRejectedReason = reason;
    // P2-7：被拒帧未注册成功 → 不留“已发送”标记；静止画面（与上一帧相同
    // 字节）在下一跳也会重发，不会因 lastSentB64 永久跳过。
    this.lastSentB64 = null;
    if (reason === "rate_limited") {
      // 静默退避：间隔翻倍（封顶 0.5fps 节奏），不提示不打断；立即重排下一跳使退避即时生效
      this.rateBackoffFactor = Math.min(this.rateBackoffFactor * 2, MAX_INTERVAL_MS / this.baseIntervalMs);
      if (this.phase === "sharing" && !this.paused) {
        this.scheduleNext();
      }
      this.emit();
      return;
    }
    if (reason === "cache_full") {
      this.paused = true;
      this.notifyThrottled(reason, "服务端帧缓存已满，已暂停画面采样（已绑定画面不受影响）");
      this.emit();
      return;
    }
    this.notifyThrottled(reason, REJECT_NOTICES[reason] ?? `画面帧被拒绝（${reason}），已跳过`);
    this.emit();
  }

  /** P2-10：同一拒绝码 5s 内只提示一次（duplicate_frame_id 等每跳都拒的场景不轰炸）。 */
  private notifyThrottled(reason: string, message: string): void {
    const now = this.nowMs();
    const last = this.lastRejectedNoticeAtMs.get(reason);
    if (last !== undefined && now - last < REJECT_NOTICE_THROTTLE_MS) {
      return;
    }
    this.lastRejectedNoticeAtMs.set(reason, now);
    this.notify(message);
  }

  private scheduleNext(): void {
    this.cancelLoop();
    const interval = Math.min(this.baseIntervalMs * this.rateBackoffFactor, MAX_INTERVAL_MS);
    this.cancelNext = this.schedule(() => {
      void this.tick();
    }, interval);
  }

  private cancelLoop(): void {
    if (this.cancelNext !== null) {
      this.cancelNext();
      this.cancelNext = null;
    }
  }

  private async tick(): Promise<void> {
    if (this.phase !== "sharing" || this.paused || this.tickInFlight) {
      if (this.phase === "sharing") {
        this.scheduleNext();
      }
      return;
    }
    this.tickInFlight = true;
    try {
      const stream = this.session.currentStream;
      if (stream !== null) {
        let frame: GrabbedFrame | null = null;
        try {
          frame = await this.grabber.grab(stream);
        } catch {
          frame = null; // 抓帧失败：跳过并计数，不崩溃
        }
        if (frame === null) {
          this.skippedFrames += 1;
          this.emit();
        } else if (frame.dataB64 === this.lastSentB64) {
          this.skippedIdentical += 1; // 完全相同画面：稳定跳过
          this.emit();
        } else if (this.sendFrame(frame)) {
          this.lastSentB64 = frame.dataB64;
          this.rememberPreview(frame);
        } else {
          this.skippedFrames += 1; // 连接未就绪：跳过本帧（不伪装上送）
          this.emit();
        }
      }
    } finally {
      this.tickInFlight = false;
      if (this.phase === "sharing" && !this.paused) {
        this.scheduleNext();
      }
    }
  }

  private sendFrame(frame: GrabbedFrame): boolean {
    this.frameSeq += 1;
    const captured = Math.max(this.lastCapturedMs + 1, Math.round(this.nowMs()));
    this.lastCapturedMs = captured;
    return this.sendShareEvent("visual.frame", {
      frame_id: `frame-${this.frameSeq}`,
      source_id: this.shareSourceId ?? "",
      source_epoch: this.registeredEpoch ?? 0,
      captured_at_ms: captured,
      width: frame.width,
      height: frame.height,
      mime: frame.mime,
      data_b64: frame.dataB64,
    });
  }

  private rememberPreview(frame: GrabbedFrame): void {
    const frameId = `frame-${this.frameSeq}`;
    const record: FrameRecord = {
      frameId,
      capturedAtMs: this.lastCapturedMs,
      dataUrl: `data:${frame.mime};base64,${frame.dataB64}`,
      bound: false,
      contentRef: null,
    };
    const result = this.previews.add(frameId, (id) => this.records.get(id)?.bound === true);
    if (result.replaced !== null) {
      this.records.delete(result.replaced); // 只淘汰未绑定预览：记录一并清理
    }
    if (!result.dropped) {
      this.records.set(frameId, record);
      this.lastFrameAtMs = this.lastCapturedMs;
      this.lastFrameBound = false; // 新帧发出：回到“仅预览”，待 registered
    }
    this.emit();
  }

  private clearLocalFrames(): void {
    this.previews.clear();
    this.records.clear();
    this.contentRefs.clear();
    this.lastSentB64 = null;
    this.lastFrameAtMs = null;
    this.lastFrameBound = false;
    this.paused = false;
  }

  private attachEndedListener(): void {
    const stream = this.session.currentStream;
    if (stream === null) {
      return;
    }
    const handler = (): void => {
      // 浏览器「停止共享」按钮：与本地停止同路径（幂等，不重复发帧）
      if (this.phase === "starting" || this.phase === "sharing") {
        this.stopShare();
      }
    };
    this.endedHandler = handler;
    for (const track of stream.getTracks()) {
      const target = track as unknown as {
        addEventListener?: (type: string, listener: () => void) => void;
      };
      target.addEventListener?.("ended", handler);
    }
  }

  private detachEndedListener(): void {
    const handler = this.endedHandler;
    const stream = this.session.currentStream;
    this.endedHandler = null;
    if (handler === null || stream === null) {
      return;
    }
    for (const track of stream.getTracks()) {
      const target = track as unknown as {
        removeEventListener?: (type: string, listener: () => void) => void;
      };
      target.removeEventListener?.("ended", handler);
    }
  }

  private stopLocal(notice: string): void {
    this.cancelLoop();
    this.detachEndedListener();
    this.session.stop();
    this.clearLocalFrames();
    this.phase = "idle";
    this.emit();
    this.notify(notice);
  }

  private sendShareEvent(
    type: "visual.share.start" | "visual.share.stop" | "visual.frame",
    extra: Partial<RealtimeEnvelope>,
  ): boolean {
    this.eventIdCounter += 1;
    const uuid = globalThis.crypto?.randomUUID?.();
    const envelope: RealtimeEnvelope = {
      version: REALTIME_PROTOCOL_VERSION,
      type,
      event_id: uuid ?? `evt-${Date.now()}-${this.eventIdCounter}`,
      seq: (this.seq += 1),
      connection_epoch: this.deps.client.connectionEpoch,
      session_id: this.deps.identity.sessionId,
      media_session_id: this.deps.identity.mediaSessionId,
      ...extra,
    };
    return this.deps.client.sendEvent(envelope);
  }

  private emit(): void {
    for (const listener of [...this.listeners]) {
      listener();
    }
  }

  private notify(message: string): void {
    this.deps.sink?.onNotice?.(message);
  }
}

/** base64 编码（分块，避免大帧栈溢出）。 */
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunk) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
  }
  return btoa(binary);
}

/**
 * 默认抓帧器：HTMLVideoElement + Canvas/OffscreenCanvas → JPEG（≤1280 长边，quality≈0.7）。
 * jsdom 无 canvas 实现时抓帧失败 → 返回 null（由上层跳过并计数，不崩溃）。
 */
export class CanvasFrameGrabber implements FrameGrabber {
  private video: (HTMLVideoElement & { srcObject: unknown }) | null = null;

  async grab(stream: DisplayStreamLike): Promise<GrabbedFrame | null> {
    try {
      let video = this.video;
      if (video === null) {
        video = document.createElement("video") as HTMLVideoElement & { srcObject: unknown };
        video.muted = true;
        video.srcObject = stream as unknown as MediaStream;
        await video.play();
        this.video = video;
      }
      const sourceWidth = video.videoWidth;
      const sourceHeight = video.videoHeight;
      if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0) {
        return null;
      }
      const scale = Math.min(1, MAX_JPEG_LONG_EDGE / Math.max(sourceWidth, sourceHeight));
      const width = Math.max(1, Math.round(sourceWidth * scale));
      const height = Math.max(1, Math.round(sourceHeight * scale));
      let dataB64: string | null = null;
      if (typeof OffscreenCanvas === "function") {
        const canvas = new OffscreenCanvas(width, height);
        const context = canvas.getContext("2d");
        if (context === null) {
          return null;
        }
        context.drawImage(video, 0, 0, width, height);
        const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: JPEG_QUALITY });
        dataB64 = arrayBufferToBase64(await blob.arrayBuffer());
      } else {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (context === null) {
          return null;
        }
        context.drawImage(video, 0, 0, width, height);
        const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
        const marker = "data:image/jpeg;base64,";
        if (!dataUrl.startsWith(marker)) {
          return null;
        }
        dataB64 = dataUrl.slice(marker.length);
      }
      if (dataB64 === null || dataB64 === "") {
        return null;
      }
      return { dataB64, width, height, mime: "image/jpeg" };
    } catch {
      return null;
    }
  }

  close(): void {
    const video = this.video;
    this.video = null;
    if (video !== null) {
      try {
        video.pause();
        video.srcObject = null;
      } catch {
        /* 释放失败：不崩溃 */
      }
    }
  }
}
