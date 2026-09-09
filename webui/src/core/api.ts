// Web V2 核心：API 客户端（对齐后端 /api/v1/* 契约，POST/GET/流式分离）

export interface ApiResult<T = unknown> {
  status: number;
  data: T;
}

export async function api<T = unknown>(
  url: string,
  options?: RequestInit
): Promise<ApiResult<T>> {
  try {
    const resp = await fetch(url, options);
    const data = (await resp.json().catch(() => ({}))) as T;
    return { status: resp.status, data };
  } catch {
    // 读路径统一 fail-open：离线/卸载后的迟到请求不产生 unhandled rejection。
    return { status: 0, data: {} as T };
  }
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

export interface AuthStatus {
  status?: string;
  authenticated?: boolean;
  browser_login?: boolean;
}

export async function fetchAuthStatus(): Promise<AuthStatus | null> {
  const { status, data } = await api<AuthStatus>("/auth/status");
  return status === 200 ? data : null;
}

export async function logoutBrowserSession(): Promise<boolean> {
  const { status } = await api("/auth/logout", { method: "POST" });
  return status === 200;
}

export async function fetchSessions(includeArchived = false): Promise<SessionMeta[]> {
  const { status, data } = await api<SessionListResponse>(
    `/api/v1/sessions${includeArchived ? "?include_archived=true" : ""}`
  );
  return status === 200 && Array.isArray(data.sessions) ? data.sessions : [];
}

export async function archiveSession(sessionId: string, archived: boolean): Promise<boolean> {
  const { status } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/archive?archived=${archived}`,
    { method: "POST" }
  );
  return status === 200;
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
  const { status } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/pin?pinned=${pinned}`,
    { method: "POST" }
  );
  return status === 200;
}

export async function deleteSession(sessionId: string): Promise<boolean> {
  const { status } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}?confirm=true`,
    { method: "DELETE" }
  );
  return status === 200;
}

/** 消息反馈（对齐 DSH ui-message-feedback；后端追加 feedback.jsonl 审计） */
export async function submitFeedback(
  sessionId: string,
  messageIndex: number,
  feedback: "up" | "down",
  note = ""
): Promise<boolean> {
  const { status } = await api(`/api/v1/sessions/${encodeURIComponent(sessionId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_index: messageIndex, feedback, note }),
  });
  return status === 200;
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
  summary = "",
  forkPoint?: number
): Promise<ForkResult | null> {
  const query = new URLSearchParams({ summary });
  if (typeof forkPoint === "number") query.set("fork_point", String(forkPoint));
  const { status, data } = await api<ForkResult>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/fork?${query.toString()}`,
    { method: "POST" }
  );
  return status === 200 ? data : null;
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


export interface AttachmentLibraryItem {
  ref: string;
  filename: string;
  content_type?: string;
  media_type?: string;
  size_bytes?: number;
  sha256?: string;
  created_at?: number;
  source_text_complete?: boolean;
}

export async function fetchRecentAttachments(limit = 20): Promise<AttachmentLibraryItem[]> {
  const { status, data } = await api<{ attachments?: AttachmentLibraryItem[] }>(
    `/api/v1/attachments/recent?limit=${Math.max(1, Math.min(limit, 100))}`
  );
  return status === 200 && Array.isArray(data.attachments) ? data.attachments : [];
}

export async function importWorkspaceAttachment(path: string): Promise<{ status: number; data: Record<string, unknown> }> {
  return api<Record<string, unknown>>("/api/v1/attachments/import-workspace", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}

export interface JobFact {
  job_id: string;
  session_id?: string;
  executor?: string;
  state: string;
  exit_code?: number | null;
  killed?: boolean;
  cancel_requested?: boolean;
  local_handle?: boolean;
  durable?: boolean;
  state_durable?: boolean;
  auto_reclaim?: boolean;
  output?: string[];
  command?: string;
}

export async function fetchSessionJobs(sessionId: string): Promise<JobFact[]> {
  if (!sessionId) return [];
  const { status, data } = await api<{ jobs?: JobFact[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/jobs`
  );
  return status === 200 && Array.isArray(data.jobs) ? data.jobs : [];
}

export async function killSessionJob(
  sessionId: string, jobId: string
): Promise<{ ok: boolean; detail: string }> {
  const { status, data } = await api<{ detail?: string }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/jobs/${encodeURIComponent(jobId)}/kill`,
    { method: "POST" }
  );
  return { ok: status === 200, detail: String(data.detail ?? "") };
}

export interface ContinuityFact {
  available: boolean;
  open: boolean;
  reason?: string;
  source?: string;
  provider?: string;
  model?: string;
  text_chars?: number;
  reasoning_chars?: number;
  checkpoint_seq?: number;
  mechanical_execution?: {
    tool_executions?: Array<Record<string, unknown>>;
    external_executions?: Array<Record<string, unknown>>;
  };
}

export async function fetchContinuityStatus(sessionId: string): Promise<ContinuityFact | null> {
  if (!sessionId) return null;
  const { status, data } = await api<ContinuityFact>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/continuity`
  );
  return status === 200 ? data : null;
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
  const { status, data } = await api<WorkspaceInfo>("/api/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  return status === 200 ? data : null;
}

export async function switchWorkspace(id: string): Promise<boolean> {
  const { status } = await api("/api/v1/workspaces/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  return status === 200;
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

/** 会话/子代理树（对齐 DSH agents 树：按 parent_id 组层级） */
export interface AgentTreeNode {
  id: string;
  parent_id: string | null;
  is_subagent: boolean;
  model?: string;
  created_at?: string | null;
}

export async function fetchAgentsTree(): Promise<Map<string, string | null>> {
  try {
    const { status, data } = await api<{ nodes: AgentTreeNode[] }>("/api/v1/agents/tree");
    if (status !== 200 || !data?.nodes) return new Map();
    return new Map(data.nodes.map((n) => [n.id, n.parent_id]));
  } catch {
    return new Map();
  }
}

export async function fetchDirs(path = ""): Promise<DirList | null> {
  const q = path ? `?path=${encodeURIComponent(path)}` : "";
  const { status, data } = await api<DirList>(`/api/v1/fs/dirs${q}`);
  return status === 200 && typeof data.path === "string" && Array.isArray(data.dirs) ? data : null;
}

/** Human-AI Continuity P3: explicit physical observation + version-protected human save. */
export interface HumanFileObservation {
  path: string;
  snapshot_ref: string;
  sha256: string;
  size_bytes: number;
  observed_at: number;
  content_range: { start: number; end_exclusive: number };
  content: string;
  total_lines: number;
  workspace_path_state: string;
  file_contract_version: 1;
}

export interface FileEffectReceipt {
  operation_id: string;
  origin: "model_tool" | "authenticated_user" | string;
  path: string;
  before_sha256: string;
  expected_after_sha256: string;
  observed_after_sha256: string | null;
  artifact_ref: string;
  effect_state: string;
  receipt_state: string;
  precondition_checked: boolean | null;
  task_applicability: "not_evaluated" | string;
  causation_proven: boolean;
}

export async function observeHumanFile(sessionId: string, path: string): Promise<ApiResult<HumanFileObservation | { error?: string; detail?: string }>> {
  return api(`/api/v1/sessions/${encodeURIComponent(sessionId)}/files/observe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, offset: 0 }),
  });
}

export async function saveHumanFile(
  sessionId: string,
  requestId: string,
  path: string,
  expectedSnapshotRef: string,
  content: string
): Promise<ApiResult<FileEffectReceipt | { error?: string; detail?: string }>> {
  return api(`/api/v1/sessions/${encodeURIComponent(sessionId)}/files/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_id: requestId,
      path,
      expected_snapshot_ref: expectedSnapshotRef,
      content,
      file_contract_version: 1,
    }),
  });
}
