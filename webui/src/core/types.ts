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

export interface AttachmentFact {
  ref: string;
  filename: string;
  content_type?: string;
  media_type?: string;
  size_bytes?: number;
  sha256?: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool" | "system";
  /** 持久化会话中的绝对消息索引；仅历史 API 返回，乐观/流式消息为空 */
  sourceIndex?: number;
  content: string;
  attachments?: AttachmentFact[];
  reasoningContent?: string | null;
  toolCalls?: ToolCallInfo[] | null;
  toolCallId?: string | null;
  toolName?: string | null;
  note?: string | null;
  /** 服务端消息时间戳（epoch 秒）；展示时按浏览器/操作系统本地时区转换 */
  ts?: number;
  /** 流式进行中标记（展示用，不落库） */
  streaming?: boolean;
  /** 流式开始时刻（等待时长展示；仅流式占位符使用） */
  streamStartedAt?: number | null;
  /** M51: 实际生成模型标签（provider/model，页脚显示） */
  model_used?: string;
  /** M52: 本轮 run 累计 prompt tokens */
  tokens_in?: number;
  /** M52: 本轮 run 累计 completion tokens */
  tokens_out?: number;
  /** M58: 本轮 run 前缀缓存命中 token（页脚命中率显示） */
  tokens_cache_hit?: number;
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
  tokens_cache_hit?: number;
  fallback_receipt?: Record<string, string> | null;
  reasoning_mode?: string;
  reasoning_capable?: boolean;
  reasoning_control?: string;
  reasoning_supported?: boolean;
  reasoning_effective?: boolean;
  reasoning_tokens?: number | null;
}

export interface HistoryMessage {
  index?: number;
  role: string;
  content: string;
  attachments?: AttachmentFact[];
  reasoning_content?: string | null;
  tool_call_id?: string | null;
  tool_name?: string | null;
  status?: string;
  tool_calls?: ToolCallInfo[];
  model_used?: string;
  tokens_in?: number;
  tokens_out?: number;
  ts?: number;
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
  attachment_ref?: string;
  size_bytes?: number;
  sha256?: string;
  excerpt?: string;
}

export interface StreamOutcome {
  ok: boolean;
  errorType: "network" | "http" | "engine" | null;
  error: { detail?: string } | null;
  data: ChatDoneData | null;
}
