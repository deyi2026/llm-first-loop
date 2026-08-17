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

/** 消息反馈（对齐 DSH ui-message-feedback；后端追加 feedback.jsonl 审计） */
export async function submitFeedback(
  sessionId: string,
  messageIndex: number,
  feedback: "up" | "down",
  note = ""
): Promise<boolean> {
  const resp = await fetch(`/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_index: messageIndex, feedback, note }),
  });
  return resp.ok;
}

/** 全量消息拉取（分页到底；导出用） */
export async function fetchAllMessages(sessionId: string): Promise<Array<{ role: string; content: string }>> {
  const out: Array<{ role: string; content: string }> = [];
  let offset = 0;
  const page = 100;
  for (let guard = 0; guard < 200; guard += 1) {
    const resp = await fetch(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=${page}&offset=${offset}`
    );
    if (!resp.ok) break;
    const data = (await resp.json()) as { messages?: Array<{ role: string; content: string }>; has_more?: boolean };
    const msgs = data.messages ?? [];
    out.push(...msgs);
    offset += msgs.length;
    if (!data.has_more || msgs.length === 0) break;
  }
  return out;
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
  // 复合通道（共享会话双端）：feishu:p2p:{id}+web
  if (channel.endsWith("+web")) {
    const base = channel.slice(0, -4);
    if (base.startsWith("feishu:p2p:")) return "Web · 飞书私聊";
    if (base.startsWith("feishu:group:")) return "Web · 飞书群聊";
  }
  if (channel.startsWith("feishu:p2p:")) return "飞书私聊";
  if (channel.startsWith("feishu:group:")) return "飞书群聊";
  return channel;
}

/** 出产物文件预览（对齐 DSH deliverables 点击打开；只读、项目根内） */
export interface FilePreview {
  path: string;
  size: number;
  truncated: boolean;
  content: string;
}

export async function fetchFilePreview(path: string): Promise<FilePreview | null> {
  const { status, data } = await api<FilePreview>(
    `/api/v1/files/preview?path=${encodeURIComponent(path)}`
  );
  return status === 200 && typeof data.content === "string" ? data : null;
}

/** 工作区管理（对齐 DSH Workspace：注册/切换/注销；会话按工作区分区） */
export interface WorkspaceInfo {
  id: string;
  path: string;
}

export interface WorkspaceListResponse {
  workspaces: WorkspaceInfo[];
  current: string;
}

export async function fetchWorkspaces(): Promise<WorkspaceListResponse | null> {
  const { status, data } = await api<WorkspaceListResponse>("/api/v1/workspaces");
  return status === 200 ? data : null;
}

export async function registerWorkspace(path: string): Promise<WorkspaceInfo | null> {
  const resp = await fetch("/api/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!resp.ok) return null;
  return (await resp.json().catch(() => ({}))) as WorkspaceInfo;
}

export async function switchWorkspace(id: string): Promise<boolean> {
  const resp = await fetch("/api/v1/workspaces/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  return resp.ok;
}

/** 按工作区列会话（侧栏工作区分组展示；不改当前工作区） */
export async function fetchWorkspaceSessions(workspaceId: string): Promise<SessionMeta[]> {
  const { status, data } = await api<{ sessions?: SessionMeta[] }>(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/sessions`
  );
  return status === 200 && Array.isArray(data.sessions) ? data.sessions : [];
}

/** 目录浏览（对齐 DSH directory-browser：应用内选择工作区目录） */
export interface DirList {
  path: string;
  parent: string | null;
  dirs: string[];
}

/** 文件树（目录+文件单层可展——工作区根内，安全边界后端把关） */
export interface FsTree {
  path: string;
  parent: string | null;
  dirs: string[];
  files: { name: string; size: number }[];
}

export async function fetchFsTree(path = ""): Promise<FsTree | null> {
  const q = path ? `?path=${encodeURIComponent(path)}` : "";
  const { status, data } = await api<FsTree>(`/api/v1/fs/tree${q}`);
  return status === 200 ? data : null;
}

export async function fsMkdir(path: string): Promise<boolean> {
  const { status } = await api(`/api/v1/fs/mkdir?path=${encodeURIComponent(path)}`, { method: "POST" });
  return status === 200;
}

export async function fsRename(path: string, newName: string): Promise<boolean> {
  const { status } = await api(
    `/api/v1/fs/rename?path=${encodeURIComponent(path)}&new_name=${encodeURIComponent(newName)}`,
    { method: "PUT" }
  );
  return status === 200;
}

export async function fsDelete(path: string): Promise<boolean> {
  const { status } = await api(
    `/api/v1/fs/delete?path=${encodeURIComponent(path)}&confirm=true`,
    { method: "DELETE" }
  );
  return status === 200;
}

export async function fetchDirs(path = ""): Promise<DirList | null> {
  const q = path ? `?path=${encodeURIComponent(path)}` : "";
  const { status, data } = await api<DirList>(`/api/v1/fs/dirs${q}`);
  return status === 200 && typeof data.path === "string" && Array.isArray(data.dirs) ? data : null;
}
