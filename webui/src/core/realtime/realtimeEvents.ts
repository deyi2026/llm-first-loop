// M1：控制通道事件 envelope 编解码（RTM-IDN-01/03、SES-07、CAP-05）。
//
// envelope 必填：`version` / `type` / `event_id` / `seq` / `connection_epoch` / `session_id` /
// `media_session_id`；按事件类型另加必填（`turn_id` / `response_id` / `run_generation` / `tool_call_id`）。
// **禁止为凑字段造假任务**：缺失按事件类型要求的字段 → 解码失败（显式报错，不静默补零）。

export const REALTIME_PROTOCOL_VERSION = 1;

export interface VisualCommitRef {
  source_id: string;
  kind: "current" | "history";
}

export interface FrameSelection {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RealtimeEnvelope {
  version: number;
  type: string;
  event_id: string;
  seq: number;
  connection_epoch: number;
  session_id: string;
  media_session_id: string;
  turn_id?: string;
  response_id?: string;
  run_generation?: string;
  tool_call_id?: string;
  /** `input.final` / `turn.committed` / `tts.request` 的正文；服务端按**顶层字段**读取（不嵌套）。 */
  text?: string;
  payload?: Record<string, unknown>;
  // ---- M3 视觉链（docs/M3-KEYFRAME-WIRE-CONTRACT.md）----
  /** `visual.share.start` / `visual.share.stop` / `visual.frame` 的来源标识（稳定，≤128）。 */
  source_id?: string;
  /** 来源代次（同 id 重共享 +1；stop 须等于当前登记 epoch）。 */
  source_epoch?: number;
  /** `visual.share.start` 可选人类可读名（≤128）。 */
  label?: string;
  /** `visual.frame` 帧标识（会话内唯一；同帧重发幂等）。 */
  frame_id?: string;
  /** 客户端单调时钟毫秒（仅帧龄计算；服务端不做墙钟换算）。 */
  captured_at_ms?: number;
  width?: number;
  height?: number;
  /** `image/jpeg|image/png|image/webp`。 */
  mime?: string;
  /** base64 帧字节（解码后 ≤512KB；日志/UI 禁止记录，RET-05）。 */
  data_b64?: string;
  /** 可选像素选区（正宽高）。 */
  selection?: FrameSelection;
  /** `input.commit` 的视觉指代（省略或 null = 纯语音，零变化）。 */
  visual?: VisualCommitRef;
  /** 下行 `visual.share.started` / `visual.share.stopped` / `visual.frame.registered`。 */
  resumed?: boolean;
  frames_staled?: number;
  content_ref?: string;
  sha256?: string;
  path?: string;
  received_at_s?: number;
  /** 下行 `visual.frame.rejected` / `error`。 */
  reason?: string;
  code?: number;
  /** 下行 `visual.clarify` 的澄清问题。 */
  question?: string;
  /** 下行 `turn.committed`（视觉路径）：证据引用与任务回链。 */
  evidence_refs?: string[];
  task_ref?: string;
}

/** 按事件类型定义**额外**必填字段（无则不填，禁止造假）。 */
export const REQUIRED_BY_TYPE: Record<string, readonly (keyof RealtimeEnvelope)[]> = {
  "input.final": ["turn_id"],
  "turn.committed": ["turn_id"],
  // 客户端上行事件：`input.commit` 只需基础信封（终稿由服务端高精度重转写产出，客户端不猜文本）；
  // `tts.request` 必须携带待合成文本与回复归属（对齐服务端 `realtime_session_runtime.handle_text`）。
  "input.commit": [],
  "tts.request": ["text", "response_id"],
  "reply.interrupt.request": ["response_id"],
  "playback.progress": ["response_id"],
  "task.cancel.request": ["run_generation"],
  correction: ["turn_id", "run_generation"],
  // M3 上行视觉事件（契约 docs/M3-KEYFRAME-WIRE-CONTRACT.md §2）：字段齐备才允许发送；
  // `input.commit.visual` 为可选扩展（省略 = 纯语音，既有行为零变化）。
  "visual.share.start": ["source_id", "source_epoch"],
  "visual.share.stop": ["source_id", "source_epoch"],
  "visual.frame": [
    "frame_id",
    "source_id",
    "source_epoch",
    "captured_at_ms",
    "width",
    "height",
    "mime",
    "data_b64",
  ],
};

const BASE_REQUIRED: readonly (keyof RealtimeEnvelope)[] = [
  "version",
  "type",
  "event_id",
  "seq",
  "connection_epoch",
  "session_id",
  "media_session_id",
];

export function encodeEnvelope(envelope: RealtimeEnvelope): string {
  assertEnvelope(envelope);
  return JSON.stringify(envelope);
}

export function decodeEnvelope(raw: string): RealtimeEnvelope {
  const parsed = JSON.parse(raw) as RealtimeEnvelope;
  assertEnvelope(parsed);
  return parsed;
}

export function assertEnvelope(envelope: RealtimeEnvelope): void {
  if (envelope.version !== REALTIME_PROTOCOL_VERSION) {
    throw new Error(`unsupported realtime protocol version: ${String(envelope.version)}`);
  }
  for (const key of BASE_REQUIRED) {
    const value = envelope[key];
    if (value === undefined || value === null || value === "") {
      throw new Error(`missing required envelope field: ${String(key)}`);
    }
  }
  if (!Number.isInteger(envelope.seq) || envelope.seq < 0) {
    throw new Error("seq must be a non-negative integer");
  }
  if (!Number.isInteger(envelope.connection_epoch) || envelope.connection_epoch < 1) {
    throw new Error("connection_epoch must be a positive integer");
  }
  for (const key of REQUIRED_BY_TYPE[envelope.type] ?? []) {
    const value = envelope[key];
    if (value === undefined || value === null || value === "") {
      throw new Error(`type ${envelope.type} requires field ${String(key)}`);
    }
  }
}

/** 旧代次事件不得更新当前会话（RTM-IDN-02）。 */
export function acceptsEpoch(envelope: RealtimeEnvelope, currentEpoch: number): boolean {
  return envelope.connection_epoch >= currentEpoch;
}