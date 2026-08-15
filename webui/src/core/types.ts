// Web V2：对话相关类型（与后端 /api/v1 契约对齐）

export interface ToolCallInfo {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolCallDelta {
  id?: string;
  name?: string;
  arguments_delta?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  reasoningContent?: string | null;
  toolCalls?: ToolCallInfo[] | null;
  toolCallId?: string | null;
  toolName?: string | null;
  note?: string | null;
  /** 流式进行中标记（展示用，不落库） */
  streaming?: boolean;
  /** 流式开始时刻（等待时长展示；仅流式占位符使用） */
  streamStartedAt?: number | null;
}

export interface ChatDoneData {
  session_id?: string;
  final_answer?: string;
  tool_calls?: ToolCallInfo[];
  reasoning_content?: string | null;
  truncated?: boolean;
  verification_note?: string | null;
  model_used?: string;
  tokens_in?: number;
  tokens_out?: number;
}

export interface HistoryMessage {
  role: string;
  content: string;
  reasoning_content?: string | null;
  tool_call_id?: string | null;
  tool_name?: string | null;
  status?: string;
  tool_calls?: ToolCallInfo[];
  [key: string]: unknown;
}

export interface HistoryResponse {
  messages: HistoryMessage[];
  has_more: boolean;
}

export interface ModelEntry {
  id: string;
  [key: string]: unknown;
}

export interface UploadResult {
  status: string;
  content_type?: string;
  result_text?: string;
  detail?: string;
}

export interface StreamOutcome {
  ok: boolean;
  errorType: "network" | "http" | "engine" | null;
  error: { detail?: string } | null;
  data: ChatDoneData | null;
}
