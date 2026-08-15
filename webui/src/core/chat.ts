// Web V2：流式对话客户端（协议对齐后端 /api/v1/chat/stream：
// data: 帧类型 answer_delta / reasoning_delta / tool_round / done(终态) / error(终态)；
// 读流异常 = 连接中断（保留已生成内容，不 throw 穿透）；支持 AbortController 停止）

import type {
  ChatDoneData,
  ChatMessage,
  HistoryMessage,
  HistoryResponse,
  ModelEntry,
  StreamOutcome,
  ToolCallDelta,
  ToolCallInfo,
  UploadResult,
} from "./types";

export interface StreamHandlers {
  onAnswerDelta?: (text: string) => void;
  onReasoningDelta?: (text: string) => void;
  onToolRound?: (data: unknown) => void;
  onToolCallDeltas?: (deltas: ToolCallDelta[]) => void;
}

export async function streamChatRequest(
  body: { message: string; session_id?: string | null; model?: string | null },
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
  let errorData: { detail?: string } | null = null;
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
      else if (evt.type === "tool_round") handlers.onToolRound?.(d);
      else if (evt.type === "tool_call_deltas" && Array.isArray(d?.deltas)) {
        toolAccum = toolAccum.concat(d.deltas as ToolCallDelta[]);
        handlers.onToolCallDeltas?.(toolAccum);
      } else if (evt.type === "done") {
        doneData = (d as ChatDoneData) ?? {};
        finished = true;
        break;
      } else if (evt.type === "error") {
        errorData = (d as { detail?: string }) ?? {};
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
  const resp = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}&offset=${offset}`
  );
  if (!resp.ok) return { messages: [], has_more: false };
  return (await resp.json()) as HistoryResponse;
}

export async function fetchModels(): Promise<ModelEntry[]> {
  const resp = await fetch("/api/v1/models");
  if (!resp.ok) return [];
  const data = (await resp.json()) as { models?: ModelEntry[] } | ModelEntry[];
  return Array.isArray(data) ? data : (data.models ?? []);
}

export async function uploadFileBase64(
  filename: string,
  b64: string
): Promise<{ status: number; data: UploadResult }> {
  const resp = await fetch("/api/v1/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, data: b64 }),
  });
  const data = (await resp.json().catch(() => ({}))) as UploadResult;
  return { status: resp.status, data };
}

/** 历史消息 → 渲染消息（tool 回执按角色呈现；tool_calls 透传） */
export function toChatMessage(m: HistoryMessage): ChatMessage {
  return {
    role: m.role as ChatMessage["role"],
    content: m.content ?? "",
    reasoningContent: m.reasoning_content ?? null,
    toolCalls: (m.tool_calls as ToolCallInfo[]) ?? null,
    toolCallId: m.tool_call_id ?? null,
    toolName: m.tool_name ?? null,
    note: null,
  };
}

/** done 终态 → 助手消息（对齐 D4：纯工具轮占位、空回答清理由调用方决策） */
export function buildAssistantNote(data: ChatDoneData): string | null {
  const note: string[] = [];
  if (data.truncated) note.push("（回答被截断，已有输出保留在对话中。发送“继续”可让模型接着输出。）");
  if (data.verification_note) note.push(data.verification_note);
  if (data.model_used) {
    let footer = `—— ${data.model_used}`;
    if (data.tokens_in || data.tokens_out) {
      footer += ` · ${data.tokens_in ?? 0}入/${data.tokens_out ?? 0}出`;
    }
    note.push(footer);
  }
  return note.length > 0 ? note.join("\n") : null;
}
