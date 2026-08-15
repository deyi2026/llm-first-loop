// Web V2 核心：API 客户端（对齐后端 /api/v1/* 契约，POST/GET/流式分离）

export interface ApiResult<T = unknown> {
  status: number;
  data: T;
}

export async function api<T = unknown>(
  url: string,
  options?: RequestInit
): Promise<ApiResult<T>> {
  const resp = await fetch(url, options);
  const data = (await resp.json().catch(() => ({}))) as T;
  return { status: resp.status, data };
}

export interface HealthInfo {
  status?: string;
  service?: string;
  version?: string;
}

export interface SessionMeta {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  status: string;
  last_message_preview: string;
  pinned: boolean;
  channel: string;
}

export interface SessionListResponse {
  sessions: SessionMeta[];
  count: number;
}

export async function fetchHealth(): Promise<HealthInfo | null> {
  const { status, data } = await api<HealthInfo>("/health");
  return status === 200 ? data : null;
}

export async function fetchSessions(): Promise<SessionMeta[]> {
  const { status, data } = await api<SessionListResponse>("/api/v1/sessions");
  return status === 200 && Array.isArray(data.sessions) ? data.sessions : [];
}

export async function fetchSharedCurrent(): Promise<string | null> {
  const { status, data } = await api<{ current: string | null }>("/api/v1/session/current");
  return status === 200 ? data.current ?? null : null;
}

export interface ForkResult {
  status?: string;
  new_session_id?: string;
  source_session_id?: string;
  fork_point?: number | null;
  inherited_event_count?: number;
  elapsed_ms?: number;
}

export async function setSessionPin(sessionId: string, pinned: boolean): Promise<boolean> {
  const resp = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/pin?pinned=${pinned}`,
    { method: "POST" }
  );
  return resp.ok;
}

export async function deleteSession(sessionId: string): Promise<boolean> {
  const resp = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}?confirm=true`,
    { method: "DELETE" }
  );
  return resp.ok;
}

export async function forkSession(
  sessionId: string,
  summary = ""
): Promise<ForkResult | null> {
  const resp = await fetch(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/fork?summary=${encodeURIComponent(summary)}`,
    { method: "POST" }
  );
  if (!resp.ok) return null;
  return (await resp.json().catch(() => ({}))) as ForkResult;
}

/** 通道标签（对齐 M56 来源通道语义：feishu:p2p:xxx / feishu:group:xxx / web） */
export function channelLabel(channel: string | undefined): string {
  if (!channel || channel === "web") return "Web";
  if (channel.startsWith("feishu:p2p:")) return "飞书私聊";
  if (channel.startsWith("feishu:group:")) return "飞书群聊";
  return channel;
}
