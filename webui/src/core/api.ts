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

export interface BuildIdentityInfo {
  release_version?: string;
  expected_release_tag?: string;
  nearest_release_tag?: string;
  commits_since_release_tag?: number | null;
  git_head?: string;
  git_short?: string;
  git_dirty?: boolean;
  release_exact?: boolean;
  display?: string;
}

export interface HealthInfo {
  status?: string;
  service?: string;
  version?: string;
  build?: BuildIdentityInfo;
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
  model?: string | null;
}

export interface SessionListResponse {
  sessions: SessionMeta[];
  count: number;
}

export interface SessionListFetchResult {
  ok: boolean;
  sessions: SessionMeta[];
  status: number;
}

export interface LearningJobInfo {
  job_id: string;
  source_episode_ref: string;
  source_session_id: string;
  source_model: string;
  state: string;
  attempt: number;
  candidate_ref?: string | null;
  reason?: string | null;
  created_at: number;
  updated_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  trigger_facts?: Record<string, unknown>;
}

export interface LearningOldestQueued {
  job_id: string;
  kind: string;
  session_id: string;
  source_model: string;
  created_at: number;
  wait_seconds: number;
}

export interface LearningAdmission {
  present: boolean;
  state?: string;
  reason?: string | null;
  since?: number | null;
  ts?: number | null;
  queued?: number;
  age_seconds?: number | null;
  stale?: boolean;
}

export interface LearningRequeueStats {
  total: Record<string, number>;
  recent: Record<string, number>;
  recent_window_s: number;
  last_event_ts: number;
}

export interface LearningStatusInfo {
  enabled: boolean;
  producer_only: boolean;
  worker: {
    running?: boolean;
    pid?: number | null;
    started_at?: string | null;
    git_head?: string | null;
    model_ref?: string | null;
    provider_id?: string | null;
    build?: BuildIdentityInfo;
    manifest_present?: boolean;
  };
  counts: Record<string, number>;
  jobs: LearningJobInfo[];
  oldest_queued?: LearningOldestQueued | null;
  admission?: LearningAdmission;
  requeue_stats?: LearningRequeueStats;
  observability_errors?: string[]; // EVO-20261013-2: journal 读取失败降级信号（缺省/空=正常）
}

export async function fetchLearningStatus(limit = 50): Promise<LearningStatusInfo | null> {
  const { status, data } = await api<LearningStatusInfo>(
    `/api/v1/learning/status?limit=${Math.max(1, Math.min(limit, 200))}`
  );
  return status === 200 && Array.isArray(data.jobs) ? data : null;
}

// ── EVO-20261013 知识管理视图（经验/方法全生命周期） ───────────────────────

export interface ExperienceRecordInfo {
  experience_ref?: string;
  experience_id?: string;
  summary: string;
  scenario: string;
  solution: string;
  root_cause?: string;
  status: string;
  record_kind?: string;
  verification_state?: string;
  tags?: string[];
  evidence?: string;
  created_at?: string;
  updated_at?: string;
  body?: string;
  use_count?: number; // EVO-20261013 知识页：使用账本聚合（catalog 投影）
  last_used_at?: string | null; // 同上；null=账本缺失/无使用记录
}

export interface ExperienceCatalog {
  counts: Record<string, number>;
  records: ExperienceRecordInfo[];
  diagnostics?: Record<string, unknown>;
}

export interface MethodCardInfo {
  id: string; // 方法 raw stem（card() 投影）
  key: string; // method:<id> —— 打分索引 ref；后端 card() 实际字段（无 method_ref/name）
  summary?: string; // 方法名（card() 投影字段；此前误声明为 name）
  description?: string;
  status: string;
  source_model?: string;
  ts?: string;
  last_signal_age_days?: number | null;
}

export interface MethodInventory {
  counts: Record<string, number>;
  records: MethodCardInfo[];
}

// EVO-20261013-2: 目录读取失败改抛错（此前返回 null，KnowledgePanel 会把
// 503/500/网络失败伪装成"无匹配"空库）；错误与空库由此可区分。
export async function fetchExperienceCatalog(
  query = "",
  status = "",
  limit = 100
): Promise<ExperienceCatalog> {
  const params = new URLSearchParams({ limit: String(Math.min(limit, 500)) });
  if (query) params.set("query", query);
  if (status) params.set("status", status);
  const { status: code, data } = await api<ExperienceCatalog>(
    `/api/v1/knowledge/experiences?${params.toString()}`
  );
  if (code === 200 && data && Array.isArray(data.records)) return data;
  throw new Error(code === 0 ? "网络请求失败" : `HTTP ${code}`);
}

export async function fetchExperienceDetail(id: string): Promise<ExperienceRecordInfo | null> {
  const { status, data } = await api<ExperienceRecordInfo>(
    `/api/v1/knowledge/experiences/${encodeURIComponent(id)}`
  );
  return status === 200 ? data : null;
}

export async function setExperienceLifecycle(
  id: string,
  action: "archive" | "invalidate" | "restore"
): Promise<{ ok: boolean; status?: string; error?: string; detail?: string }> {
  const { status, data } = await api<{ status?: string; error?: string; detail?: string }>(
    `/api/v1/knowledge/experiences/${encodeURIComponent(id)}/lifecycle?action=${action}`,
    { method: "POST" }
  );
  return status === 200 ? { ok: true, status: data?.status } : { ok: false, error: data?.error, detail: data?.detail };
}

export async function fetchMethodInventory(
  query = "",
  status = "",
  limit = 100
): Promise<MethodInventory> {
  const params = new URLSearchParams({ limit: String(Math.min(limit, 500)) });
  if (query) params.set("query", query);
  if (status) params.set("status", status);
  const { status: code, data } = await api<MethodInventory>(
    `/api/v1/knowledge/methods?${params.toString()}`
  );
  if (code === 200 && data && Array.isArray(data.records)) return data;
  throw new Error(code === 0 ? "网络请求失败" : `HTTP ${code}`);
}

export type MethodTransition = "qualify" | "activate" | "hold" | "invalidate" | "retire" | "reopen";

export async function setMethodTransition(
  id: string,
  transition: MethodTransition
): Promise<{ ok: boolean; status?: string; error?: string; detail?: string }> {
  const { status, data } = await api<{ status?: string; error?: string; detail?: string }>(
    `/api/v1/knowledge/methods/${encodeURIComponent(id)}/transition?transition=${transition}`,
    { method: "POST" }
  );
  return status === 200 ? { ok: true, status: data?.status } : { ok: false, error: data?.error, detail: data?.detail };
}

// ── 知识打分（阶段2）：只读聚合——ledger 明细 + sidecar 徽标索引 ─────────────
export interface KnowledgeScoreSummary {
  top_label: string;
  top_level: number;
  confidence: number;
  expected: number;
  p_evidence_sufficient: number;
  scored_slots: number;
  last_scored_at: string;
  evidence_level: string;
  scorer_model: string;
}

export interface KnowledgeScoreLedgerEntry {
  ledger_seq: number;
  ref: string;
  kind: string;
  adopted: boolean;
  top_label: string;
  top_level: number;
  confidence: number;
  expected: number;
  p_evidence_sufficient: number;
  decision_reported: string;
  error: string;
  ts: string;
  scorer_model: string;
}

export interface KnowledgeScoreRunnerState {
  schema?: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  last_exit_code?: number | null;
  last_scored?: number;
  last_failed?: number;
  last_pending_before?: number | null;
  last_pending_after?: number | null;
  skipped?: string;
  last_error?: string;
  consecutive_failures?: number;
  next_retry_at?: string | null;
}

export interface KnowledgeScoresResponse {
  count: number;
  scores: Record<string, KnowledgeScoreSummary>;
  ledger: KnowledgeScoreLedgerEntry[];
  pending?: number | null;
  pending_error?: string | null;
  runner?: KnowledgeScoreRunnerState | null;
}

export async function fetchKnowledgeScores(): Promise<KnowledgeScoresResponse> {
  const { status, data } = await api<KnowledgeScoresResponse>("/api/v1/knowledge/scores");
  if (
    status === 200 &&
    data &&
    typeof data.count === "number" &&
    data.scores &&
    Array.isArray(data.ledger)
  ) {
    return data;
  }
  throw new Error(status === 0 ? "网络请求失败" : `HTTP ${status}`);
}

// ── TASK-005: 受管服务 desired/live/stable 身份视图 ──────────────────────────
export interface ServiceLiveInfo {
  manifest_present?: boolean;
  pid?: number | null;
  pid_alive?: boolean;
  started_at?: string | null;
  git_head?: string | null;
  build?: Record<string, unknown>;
  model_ref?: string | null;
  provider_id?: string | null;
  manifest_error?: boolean;
}

export interface ServiceStableInfo {
  action_id: string;
  target: string;
  generation: number;
  succeeded_at: string;
  git_head: string | null;
  matches_desired_generation: boolean;
}

export interface ServiceIdentityInfo {
  live: ServiceLiveInfo;
  stable: ServiceStableInfo | null;
  restart_required: boolean;
  reasons: string[];
}

export interface DesiredDeploymentInfo {
  generation: number;
  git_head: string;
  code_root: string;
  runtime_root: string;
  deployment_id: string;
  webui_artifact_sha256: string;
}

export interface ServicesStatusInfo {
  deployment: DesiredDeploymentInfo | null;
  services: Record<string, ServiceIdentityInfo>;
  /** 服务器本地时区 UTC 偏移（分钟）；前端据此渲染"服务器挂钟"时间 */
  server_tz_offset_minutes?: number;
}

export async function fetchServicesStatus(): Promise<ServicesStatusInfo | null> {
  const { status, data } = await api<ServicesStatusInfo>("/api/v1/services/status");
  return status === 200 && data.services ? data : null;
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

export async function fetchSessionsResult(includeArchived = false): Promise<SessionListFetchResult> {
  const key = includeArchived ? "archived" : "active";
  const existing = sessionListRequests.get(key);
  if (existing) return existing;
  const pending = (async () => {
    const controller = new AbortController();
    // A stuck list request must not pin every coalesced consumer forever.
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const { status, data } = await api<SessionListResponse>(
        `/api/v1/sessions${includeArchived ? "?include_archived=true" : ""}`,
        { signal: controller.signal }
      );
      const ok = status === 200 && Array.isArray(data.sessions);
      return { ok, sessions: ok ? data.sessions : [], status };
    } finally {
      clearTimeout(timeout);
    }
  })();
  sessionListRequests.set(key, pending);
  try {
    return await pending;
  } finally {
    if (sessionListRequests.get(key) === pending) sessionListRequests.delete(key);
  }
}

const sessionListRequests = new Map<string, Promise<SessionListFetchResult>>();

export async function fetchSessions(includeArchived = false): Promise<SessionMeta[]> {
  return (await fetchSessionsResult(includeArchived)).sessions;
}

export interface ChatGPTBindingSegment {
  segment_seq?: number;
  conversation_id?: string | null;
  conversation_url?: string | null;
  request_count?: number;
  request_chars?: number;
  closed_at?: string;
  reason?: string;
}

export interface ChatGPTBindingRecord {
  lfl_session_id?: string;
  project_ref?: string;
  conversation_id?: string | null;
  conversation_url?: string | null;
  segment_seq?: number;
  segment_request_count?: number;
  segment_request_chars?: number;
  total_request_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ChatGPTBindingInfo {
  provider?: string;
  bound?: boolean;
  session_id?: string;
  session_status?: string;
  binding?: ChatGPTBindingRecord;
  history?: ChatGPTBindingSegment[];
  lifecycle?: {
    session_exists?: boolean;
    session_status?: string;
    gc_eligible?: boolean;
    gc_reason?: string;
    age_seconds?: number;
  };
  gc_policy?: {
    automatic_gc?: boolean;
    eligible_only_when_session_missing?: boolean;
    default_min_age_days?: number;
    requires_confirm?: boolean;
    requires_expected_updated_at?: boolean;
  };
}

export async function fetchSessionProviderBinding(
  sessionId: string
): Promise<ChatGPTBindingInfo | null> {
  const { status, data } = await api<ChatGPTBindingInfo>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/provider-binding`
  );
  return status === 200 ? data : null;
}

export interface ChatGPTBindingAlert {
  code?: string;
  severity?: "warning" | "critical" | string;
  message?: string;
  count?: number;
  session_ids?: string[];
  max_ratio?: number;
  error_type?: string;
}

export interface ChatGPTBindingHealth {
  schema?: string;
  status?: "healthy" | "warning" | "critical" | string;
  observed_at?: string;
  metrics?: Record<string, unknown>;
  alerts?: ChatGPTBindingAlert[];
  telemetry?: {
    coverage?: string;
    event_count?: number;
    event_types?: Record<string, number>;
    first_event_at?: string | null;
    last_event_at?: string | null;
  };
  thresholds?: Record<string, number>;
  notification_outlet?: {
    delivery?: string;
    status?: string;
    push_severities?: string[];
    repeat_seconds?: number;
    retry_seconds?: number;
    state?: {
      health_status?: string;
      updated_at?: string;
      active?: Record<string, {
        code?: string;
        severity?: string;
        last_seen_at?: string;
        last_attempt_at?: string;
        last_success_at?: string;
        count?: number;
        session_ids?: string[];
      }>;
    };
    last_event?: {
      event?: string;
      ts?: string;
      code?: string;
      severity?: string;
      delivery?: string;
    } | null;
  };
}

export async function fetchChatGPTBindingHealth(): Promise<ChatGPTBindingHealth | null> {
  const { status, data } = await api<ChatGPTBindingHealth>(
    "/api/v1/chatgpt-web/bindings/health"
  );
  return status === 200 ? data : null;
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
    if (!resp.ok) throw new Error(`会话导出读取失败（HTTP ${resp.status}）`);
    let data: { messages?: Array<{ role: string; content: string }>; has_more?: boolean };
    try {
      data = (await resp.json()) as { messages?: Array<{ role: string; content: string }>; has_more?: boolean };
    } catch {
      throw new Error("会话导出响应无效");
    }
    if (!Array.isArray(data.messages)) throw new Error("会话导出响应无效");
    const msgs = data.messages;
    out.push(...msgs);
    offset += msgs.length;
    if (!data.has_more) return out;
    if (msgs.length === 0) throw new Error("会话导出分页响应无进展");
  }
  throw new Error("会话导出分页超过安全上限");
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

/** 出产物文件预览（对齐 DSH workspace-files read/documentpreview；只读、工作区根内）。
 *  后端按扩展名机械分流：text=分页文本（offset 1-based 行），image/pdf/html=
 *  完整字节 base64，dir=单层目录，unsupported_binary=已知无渲染器二进制（不读内容）。 */
export interface FilePreviewText {
  type: "text";
  path: string;
  size: number;
  /** 读前 stat 的版本指纹成分（与 size 共同构成消费方可比较的版本） */
  mtime_ns: number;
  offset: number;
  lines: number;
  content: string;
  eof: boolean;
  truncated: boolean;
}
export interface FilePreviewBytes {
  type: "image" | "pdf" | "html";
  path: string;
  size: number;
  mtime_ns: number;
  mime: string;
  content_base64: string;
}
export interface FilePreviewDir {
  type: "dir";
  path: string;
  parent: string;
  dirs: string[];
  files: Array<{ name: string; size: number }>;
}
export interface FilePreviewUnsupported {
  type: "unsupported_binary";
  path: string;
  ext: string;
}
export type FilePreview = FilePreviewText | FilePreviewBytes | FilePreviewDir | FilePreviewUnsupported;
export type FilePreviewFailure = { error: string; detail?: string };

export async function fetchFilePreview(
  path: string,
  offset = 1,
  limit = 2000
): Promise<{ status: number; data: FilePreview | FilePreviewFailure }> {
  const query = new URLSearchParams({ path, offset: String(offset), limit: String(limit) });
  return api<FilePreview | FilePreviewFailure>(
    `/api/v1/files/preview?${query.toString()}`
  );
}

/** readRelated（对齐 DSH workspace-files.readRelated）：解析 base 文件目录下
 *  的相对依赖，仅 .js/.css，单资产 4MiB 上限，内容须合法 UTF-8。 */
export interface FileRelated {
  type: "related";
  path: string;
  size: number;
  mime: string;
  content_base64: string;
}

export async function fetchFileRelated(
  base: string,
  path: string
): Promise<{ status: number; data: FileRelated | FilePreviewFailure }> {
  const query = new URLSearchParams({ base, path });
  return api<FileRelated | FilePreviewFailure>(
    `/api/v1/files/related?${query.toString()}`
  );
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
  started_at?: number | null;
  finished_at?: number | null;
}

export interface ReadListResult<T> {
  ok: boolean;
  items: T[];
  status: number;
}

export async function fetchSessionJobsResult(sessionId: string): Promise<ReadListResult<JobFact>> {
  if (!sessionId) return { ok: true, items: [], status: 200 };
  const { status, data } = await api<{ jobs?: JobFact[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/jobs`
  );
  const items = Array.isArray(data.jobs) ? data.jobs : [];
  const ok = status === 200 && Array.isArray(data.jobs);
  return { ok, items: ok ? items : [], status };
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

export interface ScheduleItem {
  sid: string;
  session_id?: string;
  message: string;
  trigger_at: number;
  kind: "once" | "every";
  every_seconds?: number | null;
  repeat_interval?: number;
  max_count?: number;
  count?: number;
  wake?: boolean;
  created_at?: number;
  scheduled_trigger_at?: number;
  delivery_state?: "scheduled" | "waiting_human" | "retrying" | "queued" | "started" | "inactive";
  wait_reason?: string;
  // 任务语义（设计 20261019）：常驻授权的额度/到期，机械投影，仅用于展示
  task_mode?: "remind" | "task_once" | "task_recurring";
  wake_fires_total?: number;
  wake_fires_used?: number;
  wake_expires_at?: number;
  wake_child_session_id?: string;
}

export async function fetchSessionScheduleResult(
  sessionId: string
): Promise<ReadListResult<ScheduleItem>> {
  if (!sessionId) return { ok: true, items: [], status: 200 };
  const { status, data } = await api<{ schedule?: ScheduleItem[] }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/schedule`
  );
  const items = Array.isArray(data.schedule) ? data.schedule : [];
  const ok = status === 200 && Array.isArray(data.schedule);
  return { ok, items: ok ? items : [], status };
}

export async function cancelSessionScheduleItem(
  sessionId: string, sid: string
): Promise<{ ok: boolean; detail: string }> {
  const { status, data } = await api<{ detail?: string }>(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/schedule/${encodeURIComponent(sid)}/cancel`,
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

export interface WorkspaceSwitchResult {
  ok: boolean;
  status: number;
  error?: string;
  detail?: string;
}

export async function switchWorkspace(id: string): Promise<WorkspaceSwitchResult> {
  const { status, data } = await api<{ error?: string; detail?: string }>("/api/v1/workspaces/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  return {
    ok: status === 200,
    status,
    error: data.error,
    detail: data.detail,
  };
}

/** 按工作区列会话（侧栏工作区分组展示；不改当前工作区） */
export async function fetchWorkspaceSessionsResult(workspaceId: string): Promise<{ ok: boolean; sessions: SessionMeta[] }> {
  const { status, data } = await api<{ sessions?: SessionMeta[] }>(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/sessions`
  );
  const ok = status === 200 && Array.isArray(data.sessions);
  return { ok, sessions: ok ? data.sessions! : [] };
}

export async function fetchWorkspaceSessions(workspaceId: string): Promise<SessionMeta[]> {
  return (await fetchWorkspaceSessionsResult(workspaceId)).sessions;
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

/** P0-2 第一步：领取一次性删除令牌（TTL 300s，绑定 realpath+调用者身份；同身份+路径重复领取使旧令牌失效）。 */
async function fetchFsDeleteToken(path: string): Promise<{ token: string | null; error?: string }> {
  const { status, data } = await api<{ token?: string; expires_in?: number; path?: string; error?: string; detail?: string }>(
    `/api/v1/fs/delete-token?path=${encodeURIComponent(path)}`
  );
  if (status === 200 && typeof data.token === "string" && data.token) return { token: data.token };
  const reason =
    status === 0
      ? "网络错误或服务不可用"
      : `${data.error || `HTTP ${status}`}${typeof data.detail === "string" && data.detail ? `：${data.detail}` : ""}`;
  return { token: null, error: `删除失败（无法领取删除令牌：${reason}）` };
}

/** P2-4 删除结果：默认进回收站（trashed，撤销窗口内可还原）；hard=true 为不可逆删除（deleted）。 */
export interface FsDeleteResult {
  ok: boolean;
  status?: "trashed" | "deleted";
  /** 仅 trashed 时存在：撤销令牌（POST /api/v1/fs/restore?token=...，单次使用）。 */
  undoToken?: string;
  /** 撤销窗口秒数（后端契约 600）。 */
  expiresIn?: number;
  /** ok=false 时的可读错误（含后端 error 码；绝不包含 token 原文）。 */
  error?: string;
}

/** 删除文件/目录（P2-4：默认进回收站可撤销；hard=true 不可逆）：两步令牌——
 * 先 GET delete-token，再 DELETE confirm=true+token（hard=true 时附 &hard=true）。
 * 成功：{ok:true, status:"trashed", undoToken, expiresIn}（回收站）或 {ok:true, status:"deleted"}；
 * 409 confirm_token_required / token_invalid → 重取令牌再试一次（仅一次，防死循环）；
 * 其余失败（网络/409/500/越界/受保护/不存在等）一律 {ok:false, error}，不抛异常。 */
export async function fsDelete(path: string, opts: { hard?: boolean } = {}): Promise<FsDeleteResult> {
  const hard = opts.hard === true;
  const fail = (status: number, data: { error?: string; detail?: string }): FsDeleteResult => ({
    ok: false,
    error: `删除失败（${data.error || `HTTP ${status}`}）${
      typeof data.detail === "string" && data.detail ? `：${data.detail}` : ""
    }`,
  });
  const seenTokens: string[] = [];
  // 防御性脱敏：错误消息绝不包含任何已领取 token 的原文。
  const sanitize = (result: FsDeleteResult): FsDeleteResult => {
    let error = result.error ?? "";
    for (const t of seenTokens) if (t) error = error.split(t).join("[token已隐藏]");
    return { ...result, error };
  };
  const first = await fetchFsDeleteToken(path);
  if (first.token === null) return { ok: false, error: first.error ?? "删除失败（无法领取删除令牌）" };
  let token = first.token;
  seenTokens.push(token);
  for (let attempt = 0; ; attempt++) {
    const { status, data } = await api<{
      error?: string;
      detail?: string;
      status?: string;
      undo_token?: string;
      expires_in?: number;
    }>(
      `/api/v1/fs/delete?path=${encodeURIComponent(path)}&confirm=true&token=${encodeURIComponent(token)}${
        hard ? "&hard=true" : ""
      }`,
      { method: "DELETE" }
    );
    if (status === 200) {
      if (data.status === "trashed" && typeof data.undo_token === "string" && data.undo_token) {
        return {
          ok: true,
          status: "trashed",
          undoToken: data.undo_token,
          expiresIn: typeof data.expires_in === "number" && data.expires_in > 0 ? data.expires_in : 600,
        };
      }
      // hard=true 不可逆删除完成；旧版 {status:"ok"} 契约同样视为已删除。
      return { ok: true, status: "deleted" };
    }
    const error = typeof data.error === "string" ? data.error : "";
    const retryable = status === 409 && (error === "confirm_token_required" || error === "token_invalid");
    // 非令牌类失败直接返回；令牌类重试已用尽（attempt>0）同样返回 ok=false，不再抛错。
    if (!retryable || attempt > 0) return sanitize(fail(status, data));
    const reissue = await fetchFsDeleteToken(path);
    if (reissue.token === null) {
      return { ok: false, error: reissue.error ?? "删除失败（delete_token_unavailable）：无法重新领取删除令牌，请重试。" };
    }
    token = reissue.token;
    seenTokens.push(token);
  }
}

/** P2-4 撤销删除结果：成功 {ok:true}；失败 {ok:false, error}（中文文案，按后端错误码区分失效/冲突/丢失）。 */
export interface FsRestoreResult {
  ok: boolean;
  error?: string;
}

/** 撤销删除（P2-4）：POST /api/v1/fs/restore?token=undo_token（10 分钟窗口，单次使用）。
 * 成功 {ok:true}（已还原到原路径）；失败不抛异常——按后端错误码给出中文文案并透出 detail：
 * undo_token_invalid（过期/失效）、restore_conflict（原路径被占）、trash_missing（回收站条目丢失）。 */
export async function fsRestore(token: string): Promise<FsRestoreResult> {
  const { status, data } = await api<{ status?: string; error?: string; detail?: string }>(
    `/api/v1/fs/restore?token=${encodeURIComponent(token)}`,
    { method: "POST" }
  );
  if (status === 200) return { ok: true };
  if (status === 0) {
    return { ok: false, error: "恢复失败（网络错误或服务不可用）；结果未知，文件仍在回收站，请稍后重试。" };
  }
  const detail = typeof data.detail === "string" && data.detail ? `：${data.detail}` : "";
  switch (data.error) {
    case "undo_token_invalid":
      return { ok: false, error: `撤销窗口已过期或令牌失效，无法自动恢复${detail}。` };
    case "restore_conflict":
      return { ok: false, error: `原路径已被占用，拒绝覆盖${detail}；文件仍保留在回收站。` };
    case "trash_missing":
      return { ok: false, error: `回收站条目不存在（可能已被清理），无法恢复${detail}。` };
    default:
      return { ok: false, error: `恢复失败（${data.error || `HTTP ${status}`}）${detail}。` };
  }
}

/** 会话/子代理树（对齐 DSH agents 树：按 parent_id 组层级） */
export interface AgentTreeNode {
  id: string;
  parent_id: string | null;
  is_subagent: boolean;
  model?: string;
  created_at?: string | null;
  /** 机械拓扑事实（runner topology；未知时缺省，不伪造 inactive） */
  activity?: "running" | "inactive";
  outcome?: string;
  settlement?: string;
}

/** 原始节点列表（谱系面板用）；端点缺失/失败返回 null（调用方隐藏，不重试）。 */
export async function fetchAgentsTreeNodes(): Promise<AgentTreeNode[] | null> {
  try {
    const { status, data } = await api<{ nodes: AgentTreeNode[] }>("/api/v1/agents/tree");
    if (status !== 200 || !Array.isArray(data.nodes)) return null;
    return data.nodes;
  } catch {
    return null;
  }
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

// ── Provider / model settings control plane ────────────────────────────────
export interface ProviderModelAdminFact {
  id: string;
  enabled: boolean;
  effective?: boolean;
  context?: number;
  max_input_tokens?: number | null;
  max_tokens?: number | null;
  cost_tier?: string;
  thinking?: boolean;
  reasoning_capable?: boolean;
  reasoning_control?: string;
  reasoning?: boolean;
  long_context?: boolean;
  multimodal?: boolean;
  wire_protocol?: string;
  capability_tier?: string;
  send_tool_choice?: boolean;
  reasoning_split?: boolean;
  reasoning_replay?: string;
  reasoning_effort_map?: Record<string, string>;
  reasoning_efforts?: string[];
  reasoning_default_effort?: string | null;
  runtime_identity?: string;
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  min_p?: number | null;
}

export interface ProviderAdminFact {
  id: string;
  enabled: boolean;
  effective?: boolean;
  base_url: string;
  api_key_env?: string;
  credential_configured?: boolean;
  credential_source?: string;
  default_model?: string;
  timeout_s?: number | null;
  history_budget_chars?: number | null;
  max_input_tokens?: number | null;
  max_tokens?: number | null;
  chars_per_token?: number | null;
  models: ProviderModelAdminFact[];
}

export interface ProviderAdminSnapshot {
  source: "env" | "local" | "base" | "missing" | string;
  mutable: boolean;
  config_version: string;
  configured_default_model?: string;
  runtime_default_model?: string;
  default_source?: string;
  restart_required?: boolean;
  effective_provider_count?: number;
  effective_model_count?: number;
  providers: ProviderAdminFact[];
}

export interface ProviderModelAdminInput extends ProviderModelAdminFact {
  enabled: boolean;
}

export interface ProviderAdminInput {
  id: string;
  enabled: boolean;
  base_url: string;
  api_key_env?: string;
  default_model?: string;
  timeout_s?: number | null;
  history_budget_chars?: number | null;
  max_input_tokens?: number | null;
  max_tokens?: number | null;
  chars_per_token?: number | null;
  models: ProviderModelAdminInput[];
}

export interface ProviderMutationResult {
  ok: boolean;
  status: number;
  detail: string;
  snapshot: ProviderAdminSnapshot | null;
}

function providerResult(status: number, data: unknown): ProviderMutationResult {
  const body = (data && typeof data === "object") ? data as Record<string, unknown> : {};
  const ok = status >= 200 && status < 300;
  return {
    ok,
    status,
    detail: String(body.detail ?? body.error ?? ""),
    snapshot: ok && Array.isArray(body.providers) ? body as unknown as ProviderAdminSnapshot : null,
  };
}

export async function fetchProviderAdmin(): Promise<ProviderAdminSnapshot | null> {
  const { status, data } = await api<ProviderAdminSnapshot>("/api/v1/providers", { cache: "no-store" });
  return status === 200 && Array.isArray(data.providers) ? data : null;
}

export async function createProvider(
  expectedVersion: string,
  provider: ProviderAdminInput,
  apiKey?: string
): Promise<ProviderMutationResult> {
  const body: Record<string, unknown> = { expected_version: expectedVersion, provider };
  if (apiKey !== undefined && apiKey !== "") body.api_key = apiKey;
  const { status, data } = await api("/api/v1/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return providerResult(status, data);
}

export async function replaceProvider(
  expectedVersion: string,
  provider: ProviderAdminInput
): Promise<ProviderMutationResult> {
  const { status, data } = await api(`/api/v1/providers/${encodeURIComponent(provider.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_version: expectedVersion, provider }),
  });
  return providerResult(status, data);
}

export async function updateProviderCredential(
  providerId: string,
  apiKey: string
): Promise<ProviderMutationResult> {
  const { status, data } = await api(`/api/v1/providers/${encodeURIComponent(providerId)}/credential`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  return providerResult(status, data);
}

export async function deleteProviderConfig(
  providerId: string,
  expectedVersion: string
): Promise<ProviderMutationResult> {
  const qs = new URLSearchParams({ expected_version: expectedVersion, confirm: "true" });
  const { status, data } = await api(
    `/api/v1/providers/${encodeURIComponent(providerId)}?${qs.toString()}`,
    { method: "DELETE" }
  );
  return providerResult(status, data);
}

export async function setConfiguredDefaultModel(model: string): Promise<ProviderMutationResult> {
  const { status, data } = await api("/api/v1/providers/default-model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  return providerResult(status, data);
}

export async function reloadProviderRegistry(): Promise<ProviderMutationResult> {
  const { status, data } = await api("/api/v1/providers/reload", { method: "POST" });
  return providerResult(status, data);
}

export async function testProviderConnection(
  providerId: string,
  model = ""
): Promise<{ ok: boolean; detail: string; latencyMs?: number }> {
  const { status, data } = await api<Record<string, unknown>>(
    `/api/v1/providers/${encodeURIComponent(providerId)}/test`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }
  );
  return {
    ok: status === 200 && data.ok === true,
    detail: status === 200 ? `连接成功 · ${Number(data.latency_ms ?? 0)} ms` : String(data.detail ?? data.error ?? "连接失败"),
    latencyMs: status === 200 ? Number(data.latency_ms ?? 0) : undefined,
  };
}

export interface LocalRuntimeModel {
  name: string;
  size_gb: number | null;
  kind: "gguf" | "mlx" | string;
  shards: string | null;
  shards_ok: boolean | null;
  mmproj: boolean | null;
  active: boolean;
}

export interface LocalRuntimeJob {
  id: string;
  action: string;
  label: string;
  status: "running" | "done" | "failed" | string;
  started_at: number;
  duration_s: number;
  rc: number | null;
  output_tail: string[];
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface LocalRuntimeStatus {
  backend: string;
  port: number;
  alias: string | null;
  ctx: number | null;
  model_path: string | null;
  state: {
    launchd: string | null;
    pid: number | null;
    rss_gb: number | null;
    port_listening: boolean | null;
    health: boolean | null;
  };
  free_gb: number | null;
  wire_model_ids: string[];
  provider: { id: string; base_url: string } | null;
  suggested_model_ref: string | null;
  stashed_backends: string[];
  models: LocalRuntimeModel[];
  job: LocalRuntimeJob | null;
}

export async function fetchLocalRuntime(): Promise<LocalRuntimeStatus | null> {
  const { status, data } = await api<LocalRuntimeStatus>("/api/v1/local-runtime", { cache: "no-store" });
  return status === 200 && Array.isArray((data as { models?: unknown[] } | null)?.models) ? data : null;
}

export async function startLocalRuntimeJob(
  action: "switch_model" | "switch_backend" | "restart" | "stop" | "start",
  options: { model?: string; backend?: string; confirm?: boolean } = {}
): Promise<{ ok: boolean; status: number; detail: string; job: LocalRuntimeJob | null }> {
  const { status, data } = await api<Record<string, unknown>>("/api/v1/local-runtime/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...options }),
  });
  const body = data ?? {};
  return {
    ok: status === 202,
    status,
    detail: String(body.detail ?? body.error ?? ""),
    job: status === 202 ? (body.job as LocalRuntimeJob) ?? null : null,
  };
}

export async function fetchLocalRuntimeJob(jobId: string): Promise<LocalRuntimeJob | null> {
  const { status, data } = await api<LocalRuntimeJob>(
    `/api/v1/local-runtime/jobs/${encodeURIComponent(jobId)}`,
    { cache: "no-store" }
  );
  return status === 200 ? data : null;
}
