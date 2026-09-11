import type {
  ChatMessage,
  ToolActivity,
  ToolActivityStatus,
  ToolCallInfo,
  ToolResultEvent,
  ToolRoundEvent,
} from "./types";

const TERMINAL_STATUSES = new Set<ToolActivityStatus>([
  "completed",
  "success",
  "failure",
  "error",
  "blocked",
  "unauthorized",
  "timeout",
  "cancelled",
  "interrupted",
  "unknown",
]);

export function normalizeToolStatus(raw: unknown, fallback: ToolActivityStatus = "unknown"): ToolActivityStatus {
  const value = String(raw ?? "").trim().toLowerCase() as ToolActivityStatus;
  return TERMINAL_STATUSES.has(value) ? value : fallback;
}

export function parseToolReceiptStatus(content: string): ToolActivityStatus {
  if (/\[执行中断\]/.test(content || "")) return "cancelled";
  const match = /\[状态:\s*([a-z_]+)\]/i.exec(content || "");
  return match ? normalizeToolStatus(match[1], "unknown") : "unknown";
}

function eventId(event: ToolRoundEvent): string {
  const id = String(event.tool_call_id || "").trim();
  if (id) return id;
  return `${String(event.tool_name || "tool")}:${event.round_index ?? 0}`;
}

function parseArgsSummary(summary: string | undefined): Record<string, unknown> | undefined {
  const text = String(summary || "").trim();
  if (!text || text.endsWith("…")) return undefined;
  try {
    const parsed = JSON.parse(text) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined;
  } catch {
    return undefined;
  }
}

export function startToolActivity(
  current: ToolActivity[] | undefined,
  event: ToolRoundEvent
): ToolActivity[] {
  const id = eventId(event);
  const next = [...(current ?? [])];
  const index = next.findIndex((item) => item.id === id);
  const started: ToolActivity = {
    id,
    name: String(event.tool_name || "tool"),
    status: "running",
    roundIndex: typeof event.round_index === "number" ? event.round_index : undefined,
    argsSummary: String(event.args_summary || ""),
    arguments: parseArgsSummary(event.args_summary),
  };
  if (index >= 0) {
    // Duplicate/replayed tool_round must not regress an already terminal fact to running.
    next[index] = next[index].status === "running"
      ? { ...next[index], ...started }
      : next[index];
  } else {
    next.push(started);
  }
  return next;
}

export function settleToolResult(
  current: ToolActivity[] | undefined,
  event: ToolResultEvent
): ToolActivity[] {
  const id = String(event.tool_call_id || "").trim();
  if (!id) return [...(current ?? [])];
  const next = [...(current ?? [])];
  const index = next.findIndex((item) => item.id === id);
  const settled: ToolActivity = {
    ...(index >= 0 ? next[index] : { id, name: String(event.tool_name || "tool") }),
    id,
    name: String(event.tool_name || (index >= 0 ? next[index].name : "tool")),
    status: normalizeToolStatus(event.status, "unknown"),
    ...(typeof event.duration_ms === "number" && Number.isFinite(event.duration_ms)
      ? { durationMs: event.duration_ms }
      : {}),
  };
  if (index >= 0) next[index] = settled;
  else next.push(settled);
  return next;
}

export function settleRunningActivities(
  current: ToolActivity[] | undefined,
  status: ToolActivityStatus = "completed"
): ToolActivity[] {
  return (current ?? []).map((item) =>
    item.status === "running" ? { ...item, status } : item
  );
}

export function mergeFinalToolCalls(
  current: ToolActivity[] | undefined,
  calls: ToolCallInfo[] | null | undefined
): ToolActivity[] {
  const next = [...(current ?? [])];
  for (const call of calls ?? []) {
    const index = next.findIndex((item) => item.id === call.id);
    const status = call.status
      ? normalizeToolStatus(call.status, "unknown")
      : (index >= 0 ? (next[index].status === "running" ? "completed" : next[index].status) : "completed");
    const item: ToolActivity = {
      id: call.id || `${call.name}:${next.length}`,
      name: call.name || "tool",
      arguments: call.arguments,
      status,
      ...(index >= 0 ? {
        roundIndex: next[index].roundIndex,
        argsSummary: next[index].argsSummary,
        resultContent: next[index].resultContent,
        durationMs: next[index].durationMs,
      } : {}),
    };
    if (index >= 0) next[index] = { ...next[index], ...item };
    else next.push(item);
  }
  return settleRunningActivities(next);
}

export interface ProjectedMessage {
  msg: ChatMessage;
  originalIndex: number;
}

/**
 * UI-only projection: pair an assistant's persisted tool declarations with exact
 * immediately-following tool receipts. The durable message sequence is never changed.
 */
export function projectToolActivityMessages(messages: ChatMessage[]): ProjectedMessage[] {
  const consumed = new Set<number>();
  const projected: ProjectedMessage[] = [];

  for (let i = 0; i < messages.length; i += 1) {
    if (consumed.has(i)) continue;
    const msg = messages[i];
    if (msg.role !== "assistant" || !Array.isArray(msg.toolCalls) || msg.toolCalls.length === 0) {
      projected.push({ msg, originalIndex: i });
      continue;
    }

    const receipts = new Map<string, { msg: ChatMessage; index: number }>();
    for (let j = i + 1; j < messages.length && messages[j].role === "tool"; j += 1) {
      const receipt = messages[j];
      const id = receipt.toolCallId || "";
      if (id && msg.toolCalls.some((call) => call.id === id)) {
        receipts.set(id, { msg: receipt, index: j });
      }
    }

    const activities: ToolActivity[] = msg.toolCalls.map((call) => {
      const pair = receipts.get(call.id);
      if (pair) consumed.add(pair.index);
      return {
        id: call.id || `${call.name}:${i}`,
        name: call.name || "tool",
        arguments: call.arguments,
        argsSummary: safeArgsSummary(call.arguments),
        status: pair?.msg.toolStatus
          ? normalizeToolStatus(pair.msg.toolStatus, "unknown")
          : call.status
            ? normalizeToolStatus(call.status, "unknown")
            : (pair ? parseToolReceiptStatus(pair.msg.content) : "unknown"),
        resultContent: pair?.msg.content,
        ...(typeof pair?.msg.toolDurationMs === "number"
          ? { durationMs: pair.msg.toolDurationMs }
          : {}),
      };
    });

    projected.push({
      msg: { ...msg, toolActivities: activities },
      originalIndex: i,
    });
  }

  return projected;
}

export function safeArgsSummary(args: Record<string, unknown> | undefined): string {
  try {
    const text = JSON.stringify(args ?? {});
    return text.length > 200 ? `${text.slice(0, 200)}…` : text;
  } catch {
    return "";
  }
}
