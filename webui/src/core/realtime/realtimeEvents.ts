// M1：控制通道事件 envelope 编解码（RTM-IDN-01/03、SES-07、CAP-05）。
//
// envelope 必填：`version` / `type` / `event_id` / `seq` / `connection_epoch` / `session_id` /
// `media_session_id`；按事件类型另加必填（`turn_id` / `response_id` / `run_generation` / `tool_call_id`）。
// **禁止为凑字段造假任务**：缺失按事件类型要求的字段 → 解码失败（显式报错，不静默补零）。

export const REALTIME_PROTOCOL_VERSION = 1;

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
  payload?: Record<string, unknown>;
  text?: string;
}

/** 按事件类型定义**额外**必填字段（无则不填，禁止造假）。 */
export const REQUIRED_BY_TYPE: Record<string, readonly (keyof RealtimeEnvelope)[]> = {
  "input.final": ["turn_id"],
  "turn.committed": ["turn_id"],
  "reply.interrupt.request": ["response_id"],
  "playback.progress": ["response_id"],
  "task.cancel.request": ["run_generation"],
  correction: ["turn_id", "run_generation"],
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