// Web V2：流式对话客户端（协议对齐后端 /api/v1/chat/stream：
// data: 帧类型 answer_delta / reasoning_delta / tool_round / tool_result / done(终态) / error(终态)；
// 读流异常 = 连接中断（保留已生成内容，不 throw 穿透）；支持 AbortController 停止）

import type {
  ChatDoneData,
  ChatMessage,
  HistoryMessage,
  HistoryResponse,
  QueueItem,
  StreamOutcome,
  ToolCallDelta,
  ToolCallInfo,
  ToolResultEvent,
  ToolRoundEvent,
  UploadResult,
} from "./types";

export interface StreamHandlers {
  onAnswerDelta?: (text: string) => void;
  onReasoningDelta?: (text: string) => void;
  onToolRound?: (data: ToolRoundEvent) => void;
  onToolResult?: (data: ToolResultEvent) => void;
  onToolCallDeltas?: (deltas: ToolCallDelta[]) => void;
}

export async function streamChatRequest(
  body: { message: string; session_id?: string | null; model?: string | null; resume?: boolean; reasoning_mode?: string },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<StreamOutcome> {
  let resp: Response;
  try {
    resp = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err)) return { ok: false, errorType: "network", error: { detail: "已停止" }, data: null };
    return { ok: false, errorType: "network", error: { detail: "连接中断，已保留已生成内容" }, data: null };
  }
  if (!resp.ok || !resp.body || typeof resp.body.getReader !== "function") {
    let data: { detail?: string } | null = null;
    try {
      data = (await resp.json()) as { detail?: string };
    } catch {
      /* ignore */
    }
    return { ok: false, errorType: "http", error: data, data: null };
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneData: ChatDoneData | null = null;
  let errorData: { detail?: string; error?: string } | null = null;
  let toolAccum: ToolCallDelta[] = [];
  let finished = false;
  while (!finished) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (err) {
      if (isAbort(err)) return { ok: false, errorType: "network", error: { detail: "已停止" }, data: null };
      return { ok: false, errorType: "network", error: { detail: "连接中断，已保留已生成内容" }, data: null };
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      let evt: { type?: string; data?: unknown };
      try {
        evt = JSON.parse(dataLine.slice(6)) as { type?: string; data?: unknown };
      } catch {
        continue;
      }
      const d = evt.data as Record<string, unknown> | undefined;
      if (evt.type === "answer_delta") handlers.onAnswerDelta?.(String(d?.data ?? ""));
      else if (evt.type === "reasoning_delta") handlers.onReasoningDelta?.(String(d?.data ?? ""));
      else if (evt.type === "tool_round") handlers.onToolRound?.((d ?? {}) as ToolRoundEvent);
      else if (evt.type === "tool_result") handlers.onToolResult?.((d ?? {}) as ToolResultEvent);
      else if (evt.type === "tool_call_deltas" && Array.isArray(d?.deltas)) {
        toolAccum = toolAccum.concat(d.deltas as ToolCallDelta[]);
        handlers.onToolCallDeltas?.(toolAccum);
      } else if (evt.type === "done") {
        doneData = (d as ChatDoneData) ?? {};
        finished = true;
        break;
      } else if (evt.type === "error") {
        errorData = (d as { detail?: string; error?: string }) ?? {};
        finished = true;
        break;
      }
    }
  }
  if (doneData) return { ok: true, errorType: null, error: null, data: doneData };
  if (errorData) return { ok: false, errorType: "engine", error: errorData, data: null };
  return { ok: false, errorType: "network", error: { detail: "连接中断，已保留已生成内容" }, data: null };
}

export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

export async function fetchHistory(
  sessionId: string,
  limit: number,
  offset: number
): Promise<HistoryResponse> {
  const empty: HistoryResponse = { messages: [], has_more: false };
  try {
    const resp = await fetch(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}&offset=${offset}`
    );
    if (!resp.ok) return empty;
    const data = (await resp.json().catch(() => ({}))) as Partial<HistoryResponse>;
    return {
      messages: Array.isArray(data.messages) ? data.messages : [],
      has_more: data.has_more === true,
    };
  } catch {
    return empty;
  }
}

export interface ModelCapability {
  id: string;
  provider: string;
  model: string;
  context: number;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  cost_tier?: string;
  multimodal?: boolean;
  reasoning_capable: boolean;
  reasoning_control: string;
  reasoning_control_supported: boolean;
  reasoning_can_disable: boolean;
  reasoning_efforts: string[];
}

export interface ModelCatalog {
  models: string[];
  current: string | null;
  /** false means current is a preserved session fact absent from the effective registry. */
  currentAvailable?: boolean | null;
  catalog: ModelCapability[];
}

export const MODEL_CATALOG_CHANGED_EVENT = "lfl:model-catalog-changed";

export function notifyModelCatalogChanged(): void {
  window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED_EVENT));
}

/** /api/v1/models: ids + mechanical model capability facts; never provider secrets. */
export async function fetchModels(): Promise<ModelCatalog> {
  const empty: ModelCatalog = { models: [], current: null, catalog: [] };
  try {
    const resp = await fetch("/api/v1/models");
    if (!resp.ok) return empty;
    const data = (await resp.json().catch(() => ({}))) as {
      models?: unknown; current?: unknown; current_available?: unknown; catalog?: unknown;
    };
    const catalog = Array.isArray(data.catalog)
      ? data.catalog.filter((item): item is ModelCapability =>
          Boolean(item && typeof item === "object" && typeof (item as ModelCapability).id === "string")
        )
      : [];
    return {
      models: Array.isArray(data.models) ? data.models.map(String).filter(Boolean) : [],
      current: typeof data.current === "string" ? data.current : null,
      currentAvailable: typeof data.current_available === "boolean" ? data.current_available : null,
      catalog,
    };
  } catch {
    return empty;
  }
}

export async function uploadFileBase64(
  filename: string,
  b64: string
): Promise<{ status: number; data: UploadResult }> {
  try {
    const resp = await fetch("/api/v1/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, data: b64 }),
    });
    const data = (await resp.json().catch(() => ({}))) as UploadResult;
    return { status: resp.status, data };
  } catch {
    return { status: 0, data: { status: "error", detail: "网络连接失败，附件未上传。" } };
  }
}

// ── Human Turn 排队（生成中 cmd/ctrl+Enter 插话；后端 durable 事实）──

export interface QueueListResponse {
  items: QueueItem[];
  count: number;
  queued: number;
  claimed: number;
}

/** 队列状态列表（FIFO 序；仅活跃项 queued/claimed） */
export async function fetchQueueList(sessionId: string): Promise<QueueListResponse | null> {
  try {
    const resp = await fetch(`/api/v1/chat/queue?session_id=${encodeURIComponent(sessionId)}`);
    if (!resp.ok) return null;
    const data = (await resp.json().catch(() => ({}))) as Partial<QueueListResponse>;
    return {
      items: Array.isArray(data.items) ? (data.items as QueueItem[]) : [],
      count: typeof data.count === "number" ? data.count : 0,
      queued: typeof data.queued === "number" ? data.queued : 0,
      claimed: typeof data.claimed === "number" ? data.claimed : 0,
    };
  } catch {
    return null;
  }
}

export interface QueueEnqueueResponse {
  ok: boolean;
  status: number;
  queue_id?: string;
  position?: number;
  error?: string;
  detail?: string;
}

/** 入队一条 human turn（冻结 message/attachments/model/effort） */
export async function enqueueQueueMessage(
  sessionId: string,
  message: string,
  attachments: { ref: string }[],
  model: string | null,
  reasoningEffort: string | null,
  reasoningMode: string | null
): Promise<QueueEnqueueResponse> {
  try {
    const resp = await fetch("/api/v1/chat/queue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        attachments,
        model: model || undefined,
        reasoning_effort: reasoningEffort || undefined,
        reasoning_mode: reasoningMode || "auto",
      }),
    });
    const data = (await resp.json().catch(() => ({}))) as {
      queue_id?: string;
      position?: number;
      error?: string;
      detail?: string;
    };
    return { ok: resp.ok, status: resp.status, ...data };
  } catch {
    return { ok: false, status: 0, error: "network", detail: "网络连接失败，排队未成功。" };
  }
}

/** 取消排队项（仅 queued 可取消） */
export async function cancelQueueItem(sessionId: string, queueId: string): Promise<boolean> {
  try {
    const resp = await fetch("/api/v1/chat/queue", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, queue_id: queueId }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/** 原子领取队首 queued 项（多标签并发只有一个成功）；null=队空 */
export async function claimNextQueued(sessionId: string): Promise<QueueItem | null> {
  try {
    const resp = await fetch("/api/v1/chat/queue/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!resp.ok) return null;
    const data = (await resp.json().catch(() => ({}))) as { claimed?: QueueItem | null };
    return data.claimed ?? null;
  } catch {
    return null;
  }
}

/** 领取方回滚：claimed → queued（保持 FIFO 位置；session_busy 等无法发起时用） */
export async function releaseQueueItem(sessionId: string, queueId: string): Promise<void> {
  try {
    await fetch("/api/v1/chat/queue/release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, queue_id: queueId }),
    });
  } catch {
    // fail-open：release 失败由后端 reaper 兜底（悬挂 claimed 超时回滚）
  }
}

/** 历史 tool_calls 归一化：后端存储为 OpenAI 嵌套格式 {function:{name,arguments}}，
 * 前端 ToolCallInfo 为扁平 {id,name,arguments}——统一（arguments 字符串→对象） */
function normalizeToolCalls(raw: unknown): ToolCallInfo[] | null {
  if (!Array.isArray(raw)) return null;
  const out: ToolCallInfo[] = [];
  for (const tc of raw) {
    if (!tc || typeof tc !== "object") continue;
    const r = tc as Record<string, unknown>;
    let id = typeof r.id === "string" ? r.id : "";
    let name = "";
    let args: Record<string, unknown> = {};
    if (r.function && typeof r.function === "object") {
      const fn = r.function as Record<string, unknown>;
      name = typeof fn.name === "string" ? fn.name : "";
      const rawArgs = fn.arguments;
      if (typeof rawArgs === "string") {
        try {
          const parsed = JSON.parse(rawArgs);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) args = parsed;
        } catch {
          args = { _raw: rawArgs };
        }
      } else if (rawArgs && typeof rawArgs === "object") {
        args = rawArgs as Record<string, unknown>;
      }
    } else {
      name = typeof r.name === "string" ? r.name : "";
      const a = r.arguments;
      if (typeof a === "string") {
        try {
          const parsed = JSON.parse(a);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) args = parsed;
        } catch {
          args = { _raw: a };
        }
      } else if (a && typeof a === "object") {
        args = a as Record<string, unknown>;
      }
    }
    if (!id && name) id = name;
    out.push({ id, name, arguments: args, status: typeof r.status === "string" ? r.status : undefined });
  }
  return out.length > 0 ? out : null;
}

/** 历史消息 → 渲染消息（tool 回执按角色呈现；tool_calls 透传；M51/M52 模型+token 页脚数据） */
export function toChatMessage(m: HistoryMessage): ChatMessage {
  return {
    role: m.role as ChatMessage["role"],
    sourceIndex: typeof m.index === "number" && m.index >= 0 ? m.index : undefined,
    content: m.content ?? "",
    attachments: Array.isArray(m.attachments) ? m.attachments : [],
    reasoningContent: m.reasoning_content ?? null,
    toolCalls: normalizeToolCalls(m.tool_calls),
    toolCallId: m.tool_call_id ?? null,
    toolName: m.tool_name ?? null,
    toolStatus: m.status ?? null,
    toolDurationMs: typeof m.duration_ms === "number" ? m.duration_ms : null,
    note: null,
    model_used: m.model_used ?? "",
    tokens_in: m.tokens_in ?? 0,
    tokens_out: m.tokens_out ?? 0,
    tokens_cache_hit: (m as { tokens_cache_hit?: number }).tokens_cache_hit ?? 0,
    ts: typeof m.ts === "number" ? m.ts : 0,
  };
}

/** done 终态 → 助手消息注释（模型/token 页脚由 MessageItem 结构化渲染，此处不含） */
export function buildAssistantNote(data: ChatDoneData): string | null {
  const note: string[] = [];
  if (data.truncated) note.push("（回答被截断，已有输出保留在对话中。发送“继续”可让模型接着输出。）");
  if (data.verification_note) note.push(data.verification_note);
  if (data.fallback_receipt) {
    const from = data.fallback_receipt.from ?? "";
    const to = data.fallback_receipt.to ?? "";
    const reason = data.fallback_receipt.reason ?? "";
    note.push(`模型回退：${from || "未知"} → ${to || "未知"}${reason ? `（${reason}）` : ""}`);
  }
  if (data.reasoning_mode || data.reasoning_control || data.reasoning_capable !== undefined) {
    const parts = [
      `mode=${data.reasoning_mode ?? "unknown"}`,
      `control=${data.reasoning_control ?? "unknown"}`,
      `capable=${String(data.reasoning_capable ?? false)}`,
      `supported=${String(data.reasoning_supported ?? false)}`,
      `effective=${String(data.reasoning_effective ?? false)}`,
    ];
    if (data.reasoning_tokens != null) parts.push(`tokens=${data.reasoning_tokens}`);
    note.push(`推理状态：${parts.join(" · ")}`);
  }
  return note.length > 0 ? note.join("\n") : null;
}

/** token 可读格式化（对齐 feishu 页脚 k 单位：12345 → 12.3k） */
export function formatTokens(n: number | undefined | null): string {
  const v = Number(n ?? 0);
  if (v >= 1000) {
    const k = v / 1000;
    return `${k >= 100 ? Math.round(k) : Math.round(k * 10) / 10}k`;
  }
  return String(v);
}

/** 后台 run 状态查询（EVO 后台 run）：running/done + 起止时间（前端刷新/切换后恢复可见性）. */
export interface StreamStatus {
  running: boolean;
  detail?: string;
  started_at?: string;
  finished_at?: string;
}

export async function fetchStreamStatus(sessionId: string): Promise<StreamStatus | null> {
  try {
    const resp = await fetch(`/api/v1/chat/stream/status?session_id=${encodeURIComponent(sessionId)}`);
    if (!resp.ok) return null;
    return (await resp.json()) as StreamStatus;
  } catch {
    return null; // 端点不可用 → 静默（fail-open）
  }
}
