// 提权闭环 Web 端（EVO-20260923-c58a0bb1 accepted + 用户批准 2026-09-23）:
// EscalationWatcher = 全局挂载的弹窗（pending 出现即弹，人工批准/拒绝）
// EscalationPanel   = 侧栏"提权"页（历史 + 待决列表，与弹窗共用数据层）
// 后端契约: GET /api/v1/escalation/list, GET /api/v1/escalation/detail,
//           POST /api/v1/escalation/review
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { zh } from "../../i18n/zh";
import { isAuthRequired, reportUnauthorized } from "../../core/authSession";
import { mainViewStore, sessionStore, useCurrentSessionId, useSessions } from "../../core/stores";
import { prefillComposer } from "../../core/conversation";
import { switchWorkspace } from "../../core/api";

export interface EscalationRequest {
  id: string;
  tool_name: string;
  command: string;
  justification: string;
  session_id: string;
  origin_goal_id?: string;
  origin_run_generation?: string;
  status: string; // pending | approved | denied | consumed | expired
  created_at: string;
  decided_at: string;
  decided_by: string;
  decision_note: string;
  token_expires_at?: string;
  /** P0-5 展示-审批绑定（防 TOCTOU）：审批时须回传 expected_sha256 = command_sha256。
   * command 为超长截断展示时 command_truncated=true，但 sha256/len 仍按完整原文。 */
  command_sha256?: string;
  command_len?: number;
  command_truncated?: boolean;
  request_kind?: "command" | "host_grant" | "verify_receipt";
  /** FR-03: 跨进程签名失效标记（存储层投影保留）——失效 pending 不入待审队列，
   * 历史视图显示"已失效"。 */
  _sig_unverified?: boolean;
}

interface ListResp {
  requests: EscalationRequest[];
  /** ESC-07（FR-07）: 待审专用列表——独立于"最新 50 条"历史窗口，
   * 保证待审项不被更新的终态记录挤出可见范围。 */
  pendingRequests: EscalationRequest[];
  pending_count: number;
  /** ESC-08（FR-08）: 存储故障如实呈现——503/网络失败时设置，
   * 面板渲染错误横幅而非歧义空列表（"待审批 (0)"）。 */
  error?: string;
}

interface DetailResp {
  id: string;
  command: string; // 完整原文，不截断（ESC-05 / FR-05）
  command_sha256?: string;
  command_len?: number;
  // 注意：失败语义走联合类型另一支 { error; status }；成功响应不含 error。
}

const POLL_MS = 5000;
const READ_TIMEOUT_MS = 10000;
const REVIEW_TIMEOUT_MS = 15000;

// Keep the deadline active until the body is read, not merely until headers arrive.
async function fetchBounded(url: string, init: RequestInit = {}, timeoutMs = READ_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const body: unknown = await response.json().catch(() => null);
    return { response, body };
  } finally {
    clearTimeout(timer);
  }
}

// Watcher 与展开的审批面板可能同一时刻请求；只共享在途读取，
// 不缓存已完成结果，避免审批状态被旧快照遮蔽。
let escalationInFlight: Promise<ListResp> | null = null;

async function fetchEscalations(): Promise<ListResp> {
  if (escalationInFlight) return escalationInFlight;
  const pending = fetchEscalationsUncached();
  escalationInFlight = pending;
  try {
    return await pending;
  } finally {
    if (escalationInFlight === pending) escalationInFlight = null;
  }
}

async function fetchEscalationsUncached(): Promise<ListResp> {
  if (isAuthRequired()) {
    return { requests: [], pendingRequests: [], pending_count: 0, error: "登录已失效，请重新登录。" };
  }
  try {
    // ESC-07（FR-07）: 待审队列用 pending 专用查询穿透历史窗口；
    // 历史视图保持"最新 50 条"。两请求并行，任一失败按整次加载失败处理。
    const [allResult, pendingResult] = await Promise.all([
      fetchBounded("/api/v1/escalation/list?limit=50"),
      fetchBounded("/api/v1/escalation/list?status=pending&limit=50"),
    ]);
    const allR = allResult.response;
    const pendingR = pendingResult.response;
    reportUnauthorized(allR.status);
    reportUnauthorized(pendingR.status);
    if (!allR.ok || !pendingR.ok || !allResult.body || !pendingResult.body) {
      // ESC-08: 503 等失败态不得折叠成"空列表"——否则审批者会误读为
      // "没有待审"，恰是后端 503 改造要消除的歧义。读出 error 字段如实上抛。
      const body = (pendingResult.body || {}) as { error?: string };
      return {
        requests: [],
        pendingRequests: [],
        pending_count: 0,
        error: body.error || `审批面板读取失败（${allR.status}/${pendingR.status}），请检查服务端`,
      };
    }
    const all = allResult.body as { requests?: EscalationRequest[]; pending_count?: number };
    const pend = pendingResult.body as { requests?: EscalationRequest[]; pending_count?: number };
    if (!Array.isArray(all.requests) || !Array.isArray(pend.requests)) {
      return { requests: [], pendingRequests: [], pending_count: 0, error: "审批列表响应不可读" };
    }
    return {
      requests: all.requests || [],
      pendingRequests: pend.requests || [],
      pending_count: pend.pending_count ?? all.pending_count ?? 0,
    };
  } catch (err) {
    return { requests: [], pendingRequests: [], pending_count: 0, error: `网络错误: ${String(err)}` };
  }
}

async function fetchEscalationDetail(id: string): Promise<DetailResp | { error: string; status: number }> {
  try {
    const { response: r, body } = await fetchBounded(`/api/v1/escalation/detail?id=${encodeURIComponent(id)}`);
    const d = (body || {}) as Partial<DetailResp> & { error?: string };
    // 注意：后端 detail 成功响应含 escalation 的 status 字段（approved/pending/…），
    // 失败判别只能用 error 字段/HTTP 码，不得用 "status" in d（否则成功永远被判失败）。
    if (!r.ok || typeof d.error === "string") {
      return { error: d?.error || `失败(${r.status})`, status: r.status };
    }
    if (typeof d.command !== "string") {
      // 畸形 200（缺 command）不得解锁批准门——显式按失败处理。
      return { error: "响应缺少完整命令字段", status: r.status };
    }
    return { id: d.id || id, command: d.command, command_sha256: d.command_sha256, command_len: d.command_len };
  } catch (err) {
    return { error: `请求失败: ${String(err)}`, status: 0 };
  }
}

interface ReviewResult {
  ok: boolean;
  message: string;
  stale: boolean;
  loginRequired: boolean;
  uncertain?: boolean;
  settled?: boolean;
  materialChanged?: boolean;
}

async function verifyEscalation(id: string, decision: "approved" | "denied", sha: string): Promise<ReviewResult> {
  const unknown = (message: string): ReviewResult => ({ ok: false, message, stale: false, loginRequired: false, uncertain: true });
  try {
    const { response, body } = await fetchBounded(`/api/v1/escalation/detail?id=${encodeURIComponent(id)}`);
    const row = body as Partial<EscalationRequest> | null;
    if (!response.ok || !row || row.id !== id || !sha || !row.command_sha256 || row._sig_unverified) {
      return unknown("审批结果尚无法核实，请查询状态，不要重复提交。");
    }
    // IDs bind immutable command material. A different verified fingerprint is
    // not evidence that the original POST failed. Never unlock or resend it.
    if (row.command_sha256 !== sha) {
      return { ...unknown("审批材料指纹已变化，原审批结果无法核实。请返回来源会话核对，必要时重新发起审批；不要重复提交旧请求。"), stale: true, materialChanged: true };
    }
    if (row.status === "pending") return unknown("仍显示待审批，但原请求可能仍在处理；请查询状态，不要重复提交。");
    if (row.status === "approved" || row.status === "denied" || row.status === "consumed" || row.status === "expired") {
      const approved = row.status !== "denied";
      const actual = statusBadge(row.status).text;
      return { ok: approved === (decision === "approved"), message: `已核实实际状态：${actual}`, stale: true, loginRequired: false, settled: true };
    }
  } catch { /* a read failure is not evidence that the decision failed */ }
  return unknown("审批结果尚无法核实，请查询状态，不要重复提交。");
}

async function reviewEscalation(
  id: string,
  decision: "approved" | "denied",
  note: string,
  expectedSha256: string
): Promise<ReviewResult> {
  try {
    const { response: r, body } = await fetchBounded("/api/v1/escalation/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // P0-5 展示-审批绑定：expected_sha256 必须等于列表返回的 command_sha256，
      // 确保批准的就是展示给审批者的那条命令（缺字段时后端 400 兜底提示）。
      body: JSON.stringify({ id, decision, note, expected_sha256: expectedSha256 }),
    }, REVIEW_TIMEOUT_MS);
    const d = (body || {}) as { ok?: boolean; error?: string; request?: Partial<EscalationRequest> };
    if (r.ok && d.ok === true && d.request?.id === id && d.request.command_sha256 === expectedSha256 && d.request.status === decision) {
      return { ok: true, message: decision === "approved" ? "已批准（AI 将收到受管审批结果）" : "已拒绝（AI 将收到拒绝理由）", stale: false, loginRequired: false, settled: true };
    }
    if (r.ok || !body || r.status >= 500) return await verifyEscalation(id, decision, expectedSha256);
    const error = String((d as { error?: string }).error || "");
    if (r.status === 403 && (error === "human_auth_required" || error === "human_channel_required")) {
      return {
        ok: false,
        message: "审批未生效：当前浏览器没有有效登录会话。请先登录 LFL，再返回本页重新确认。",
        stale: false,
        loginRequired: true,
      };
    }
    if (r.status === 409 && error.includes("stale_review")) {
      return { ok: false, message: "⚠️ 待审内容已变化，请重新打开", stale: true, loginRequired: false };
    }
    if (r.status === 400 && error.includes("missing_expected_sha256")) {
      return { ok: false, message: "⚠️ 审批缺少命令哈希绑定，请重新打开详情后再试", stale: false, loginRequired: false };
    }
    if (r.status === 409) return await verifyEscalation(id, decision, expectedSha256);
    return { ok: false, message: `⚠️ ${error || `失败(${r.status})`}`, stale: false, loginRequired: false };
  } catch {
    return await verifyEscalation(id, decision, expectedSha256);
  }
}

// Both entry points share per-request state. A synchronous reservation prevents
// double clicks and simultaneous submissions from the watcher and the sidebar.
type ReviewState = { phase: "busy" | "unknown" | "settled"; decision: "approved" | "denied"; sha: string; message: string; materialChanged?: boolean };
let reviewStates = new Map<string, ReviewState>();
const reviewListeners = new Set<() => void>();
function subscribeReviews(listener: () => void) {
  reviewListeners.add(listener);
  return () => {
    reviewListeners.delete(listener);
    // Settled rows need not outlive all views; unknown and in-flight rows must.
    if (!reviewListeners.size) reviewStates = new Map([...reviewStates].filter(([, s]) => s.phase !== "settled"));
  };
}
function setReviewState(id: string, state?: ReviewState) {
  reviewStates = new Map(reviewStates);
  if (state) reviewStates.set(id, state);
  else reviewStates.delete(id);
  reviewListeners.forEach((listener) => listener());
}
function useReviewState(id: string) {
  return useSyncExternalStore(subscribeReviews, () => reviewStates.get(id));
}
function finishReview(id: string, state: ReviewState, result: ReviewResult) {
  setReviewState(id, result.uncertain || result.settled ? { ...state, phase: result.uncertain ? "unknown" : "settled", message: result.message, materialChanged: result.materialChanged } : undefined);
  return result;
}
function submitReview(id: string, decision: "approved" | "denied", note: string, sha: string) {
  if (reviewStates.has(id)) return null;
  const state: ReviewState = { phase: "busy", decision, sha, message: "正在提交审批，请稍候…" };
  setReviewState(id, state);
  return reviewEscalation(id, decision, note, sha).then((result) => finishReview(id, state, result));
}
function checkReview(id: string) {
  const state = reviewStates.get(id);
  if (state?.phase !== "unknown") return;
  setReviewState(id, { ...state, phase: "busy", message: "正在核实审批状态…" });
  return verifyEscalation(id, state.decision, state.sha).then((result) => finishReview(id, state, result));
}

function EscalationLoginPrompt() {
  // 登录跳转仅使用本站路径；保留当前会话 query，登录后返回原审批位置。
  const next = window.location.pathname + window.location.search;
  return (
    <div className="v2-esc-hash warn v2-esc-login-required" role="alert" data-testid="esc-login-required">
      此次审批没有生效。<a href={`/login?next=${encodeURIComponent(next)}`} data-testid="esc-login-link">登录 LFL 后重试审批</a>
    </div>
  );
}

function useEscalations(enabled = true) {
  const [data, setData] = useState<ListResp | null>(null);
  const load = useCallback(() => {
    // ESC-08: fetchEscalations 永不返回 null（失败态内联 error 字段），
    // 503/网络错误以横幅呈现而非静默空列表。
    void fetchEscalations().then((d) => {
      setData((prev) =>
        d.error && prev
          ? // R2（M1.1 复审）: 未知 ≠ 空——读取失败保留最后一次成功快照
            // （待审卡片与审批备注态不丢，横幅标注"可能已过期"）；首屏即
            // 失败（prev=null）仍如实呈现错误横幅 + 空态不冒充"无待审"。
            {
              ...d,
              requests: prev.requests,
              pendingRequests: prev.pendingRequests,
              pending_count: prev.pending_count,
            }
          : d
      );
    });
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const poll = () => {
      // 隐藏标签页不消耗双端点轮询；恢复可见时立即补读审批事实。
      if (!document.hidden && !isAuthRequired()) load();
    };
    poll();
    const t = window.setInterval(poll, POLL_MS);
    document.addEventListener("visibilitychange", poll);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [enabled, load]);
  return { data, reload: load };
}

function fmtTime(iso: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function statusBadge(status: string): { text: string; cls: string } {
  const map: Record<string, { text: string; cls: string }> = {
    pending: { text: "待审批", cls: "pending" },
    approved: { text: "已批准（待使用）", cls: "ok" },
    denied: { text: "已拒绝", cls: "reject" },
    consumed: { text: "令牌已使用", cls: "ok" },
    expired: { text: "已过期", cls: "" },
  };
  return map[status] || { text: status, cls: "" };
}

/** Navigation is not approval or execution. Recovery drafts contain only a
 * request reference, never a command or authority copied from an old record. */
function EscalationOrigin({ req, onNavigate, materialChanged }: {
  req: EscalationRequest;
  onNavigate?: () => void;
  materialChanged?: boolean;
}) {
  const sessions = useSessions();
  const currentId = useCurrentSessionId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sid = req.session_id;
  const title = sessions.find((s) => s.session_id === sid)?.title;
  const recoverable = /^[A-Za-z0-9-]{6,80}$/.test(req.id) && ["pending", "approved", "expired"].includes(req.status);
  const needsNew = req.status === "expired" || !!req._sig_unverified || !!materialChanged;
  const open = async (recover: boolean) => {
    if (!sid || busy) return;
    setBusy(true);
    setError("");
    try {
      if (!sessions.some((s) => s.session_id === sid)) {
        const response = await fetch("/api/v1/evolution/session-locator?session_id=" + encodeURIComponent(sid));
        reportUnauthorized(response.status);
        const location = await response.json();
        if (!response.ok || !location.available || location.session_id !== sid) {
          setError("无法定位来源会话，请检查会话是否仍存在。");
          return;
        }
        if (!location.current) {
          if (!location.workspace_id) {
            setError("来源工作区不可用。");
            return;
          }
          const switched = await switchWorkspace(String(location.workspace_id));
          if (!switched.ok) {
            setError("暂不能切换来源工作区，请稍后重试。");
            return;
          }
        }
      }
      mainViewStore.setView("chat");
      sessionStore.setNewSessionPending(false);
      sessionStore.setCurrentSession(sid);
      if (recover) {
        prefillComposer(
          "请核对本会话中提权申请 " + req.id +
          " 的原始任务和当前状态。" + (materialChanged
            ? "审批材料指纹已变化，原提交结果不确定。先核对原请求及执行事实，不得复用旧审批；仅在确认操作尚未完成且仍有必要时，使用核实后的材料重新发起人工审批。"
            : "若仍待审批则继续等待；若凭证有效则按原范围处理；") +
          "若审批或签发材料已失效、签发失败，且操作尚未完成、仍有必要，请重新核验并用原申请类型发起人工审批。" +
          "不要复用过期凭证、重复已完成操作或执行未获批准的命令。"
        );
      }
      onNavigate?.();
    } catch {
      setError("打开来源会话失败，请重试。");
    } finally {
      setBusy(false);
    }
  };
  if (!sid) return <div className="v2-esc-hash">来源会话未记录</div>;
  return (
    <div className="v2-esc-just" data-testid={"esc-origin-" + req.id}>
      <div style={{ overflowWrap: "anywhere" }}>来源会话：{title ? title + " · " : ""}{sid}{currentId === sid ? "（当前会话）" : ""}</div>
      {req.origin_goal_id && <div style={{ overflowWrap: "anywhere" }}>Goal：{req.origin_goal_id}</div>}
      {req.origin_run_generation && <div style={{ overflowWrap: "anywhere" }}>Run：{req.origin_run_generation}</div>}
      {req._sig_unverified && <div className="v2-esc-hash warn">历史来源未能验签；请在原会话核对，不得直接复用。</div>}
      <div className="v2-evo-row" style={{ flexWrap: "wrap" }}>
        <button type="button" className="v2-evo-btn" disabled={busy} onClick={() => void open(false)}>打开来源会话</button>
        {recoverable && (
          <button type="button" className="v2-evo-btn" disabled={busy} onClick={() => void open(true)}>
            {needsNew ? "重新发起审批" : "返回会话继续处理"}
          </button>
        )}
      </div>
      {recoverable && <div className="v2-esc-hash">继续处理将填入原会话输入框，确认发送后由该会话核对并处理。</div>}
      {error && <div className="v2-esc-hash warn" role="alert">{error}</div>}
    </div>
  );
}

// ── 待决卡片（弹窗与面板共用）──
function PendingCard({
  req,
  onDecide,
  onNavigate,
  onRefresh,
}: {
  req: EscalationRequest;
  onDecide: (id: string, decision: "approved" | "denied", note: string, expectedSha256: string) => void;
  onNavigate?: () => void;
  onRefresh: () => void;
}) {
  const review = useReviewState(req.id);
  const busy = review?.phase === "busy";
  const locked = !!review;
  const [note, setNote] = useState("");
  // ESC-05（FR-05）: 截断命令必须先看完整原文才能批准——
  // "看到多少"决定"能否负责任地点批准"。
  const [fullCmd, setFullCmd] = useState<string | null>(null);
  // R5（M1.1 复审）: 查看资格绑定 (request_id, command_sha256)——只有详情
  // 响应携带非空指纹且与当前待审命令指纹一致时才解锁批准；缺指纹（畸形/
  // 降级/旧回包）不解锁也不展示原文（fail-closed，防钓鱼展示）。材料变化
  // （新一轮轮询指纹更新）即重新锁定。
  const [viewedSha, setViewedSha] = useState("");
  const [viewErr, setViewErr] = useState("");
  const mustReadFull = !!req.command_truncated;
  const viewedFull = !mustReadFull || (viewedSha !== "" && viewedSha === req.command_sha256);
  const badge = req.request_kind === "verify_receipt" && req.status === "approved"
    ? { text: "Host 已签发", cls: "ok" }
    : statusBadge(req.status);
  useEffect(() => {
    // 待审命令指纹变化（新一轮列表）→ 查看资格失效，原文与解锁一并重置
    if (viewedSha !== "" && viewedSha !== req.command_sha256) {
      setViewedSha("");
      setFullCmd(null);
    }
  }, [req.command_sha256, viewedSha]);
  const loadFull = () => {
    setViewErr("");
    void fetchEscalationDetail(req.id).then((d) => {
      if ("error" in d) {
        setViewErr(`完整命令加载失败: ${d.error}`);
        return;
      }
      // TOCTOU 防线（R5 强化）: 详情原文指纹必须非空且与列表展示时绑定的
      // 指纹一致——不一致说明列表数据已过期，缺失说明响应降级/畸形；两种
      // 情况都禁止用该原文解锁批准（fail-closed）。
      if (!d.command_sha256 || !req.command_sha256 || d.command_sha256 !== req.command_sha256) {
        setViewErr("命令指纹缺失或不一致（待审内容可能已变化），请刷新列表后重试");
        return;
      }
      setFullCmd(d.command);
      setViewedSha(d.command_sha256);
    });
  };
  return (
    <div className="v2-evo-item pending" data-testid={`esc-item-${req.id}`}>
      <div className="v2-evo-row">
        <span className={`v2-evo-status ${badge.cls}`}>{badge.text}</span>
        <span style={{ opacity: 0.6, fontSize: 11 }}>{fmtTime(req.created_at)}</span>
      </div>
      <EscalationOrigin req={req} onNavigate={onNavigate} materialChanged={review?.materialChanged} />
      <div className="v2-esc-cmd" data-testid={`esc-cmd-${req.id}`}>
        <code>{req.command}</code>
      </div>
      {(req.command_sha256 || typeof req.command_len === "number") && (
        <div className="v2-esc-hash" data-testid={`esc-hash-${req.id}`}>
          🔗 命令指纹 sha256:{req.command_sha256 ? req.command_sha256.slice(0, 16) : "—"} · 长度 {req.command_len ?? "？"}
        </div>
      )}
      {mustReadFull && (
        <div className="v2-esc-hash warn" data-testid={`esc-truncated-${req.id}`}>
          ⚠️ 命令过长，列表中已截断显示——批准前必须先查看完整命令
        </div>
      )}
      {mustReadFull && fullCmd === null && (
        <button
          type="button"
          className="v2-evo-btn"
          data-testid={`esc-view-full-${req.id}`}
          onClick={loadFull}
        >
          查看完整命令（批准前必读）
        </button>
      )}
      {fullCmd !== null && (
        <div className="v2-esc-cmd" data-testid={`esc-fullcmd-${req.id}`} style={{ maxHeight: 260, overflow: "auto" }}>
          <code>{fullCmd}</code>
        </div>
      )}
      {viewErr && <div className="v2-esc-hash warn">{viewErr}</div>}
      <div className="v2-esc-just">{req.justification}</div>
      {req.request_kind === "verify_receipt" && (
        <div className="v2-esc-hash warn">此操作由已登录浏览器人工批准后由 Host 专用入口签发，不会授予 AI 审计账本写权限。</div>
      )}
      <textarea
        className="v2-esc-note"
        placeholder="审批备注（拒绝时建议写理由，AI 侧可见）"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
      />
      <div className="v2-evo-row">
        <button
          type="button"
          className="v2-evo-btn approve"
          disabled={locked || !viewedFull}
          title={mustReadFull && !viewedFull ? "请先查看完整命令再批准（列表展示为截断内容）" : undefined}
          data-testid={`esc-approve-${req.id}`}
          onClick={() => onDecide(req.id, "approved", note, req.command_sha256 || "")}
        >
          {busy ? "处理中…" : "批准"}
        </button>
        <button
          type="button"
          className="v2-evo-btn reject"
          disabled={locked}
          onClick={() => onDecide(req.id, "denied", note, req.command_sha256 || "")}
        >
          {busy ? "处理中…" : "拒绝"}
        </button>
      </div>
      {review && <div className="v2-esc-hash" role="status" data-testid={`esc-review-state-${req.id}`}>{review.message}</div>}
      {review?.phase === "unknown" && (
        <button type="button" className="v2-evo-btn" data-testid={`esc-check-${req.id}`} onClick={() => {
          void checkReview(req.id)?.then((result) => { if (result.settled || result.stale) onRefresh(); });
        }}>查询审批状态</button>
      )}
    </div>
  );
}

// ── 全局弹窗（用户要求: web 端弹窗，审批后 AI 闭环接收）──
export function EscalationWatcher({ onNavigate }: { onNavigate?: () => void } = {}) {
  const { data, reload } = useEscalations(true);
  const [mutedIds, setMutedIds] = useState<Set<string>>(new Set());
  const [resultMsg, setResultMsg] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const prevPendingRef = useRef<Set<string>>(new Set());
  const [newArrival, setNewArrival] = useState(false);

  // ESC-07（FR-07）: 待审列表来自专用 pending 查询，不受历史窗口挤出影响。
  const pending = useMemo(() => data?.pendingRequests || [], [data]);

  // 新 pending 到达 → 重新弹窗（被"稍后处理"静音过的除外）
  useEffect(() => {
    const cur = new Set(pending.map((r) => r.id));
    let hasNew = false;
    for (const id of cur) if (!prevPendingRef.current.has(id)) hasNew = true;
    prevPendingRef.current = cur;
    if (hasNew) {
      setNewArrival(true);
      setResultMsg("");
      setLoginRequired(false);
    }
  }, [pending]);

  const visible = newArrival && pending.filter((r) => !mutedIds.has(r.id)).length > 0;
  const mutedPending = pending.filter((r) => mutedIds.has(r.id));

  const decide = (id: string, decision: "approved" | "denied", note: string, expectedSha256: string) => {
    const submission = submitReview(id, decision, note, expectedSha256);
    if (!submission) return;
    setResultMsg("正在提交审批，请稍候…");
    setLoginRequired(false);
    void submission.then((res) => {
      setResultMsg(res.message);
      setLoginRequired(res.loginRequired);
      if (res.ok) {
        setMutedIds((prev) => new Set(prev).add(id));
        if (pending.filter((r) => r.id !== id && !mutedIds.has(r.id)).length === 0) setNewArrival(false);
      }
      // stale_review：待审内容已变化 → 刷新列表让用户基于最新命令重新决定。
      if (res.ok || res.stale) reload();
    });
  };

  if (!visible) {
    // R2（M1.1 复审）: 通道读取失败时弹窗不可见 → 必须以全局 chip 告警，
    // 否则审批者会把"读取失败"误读为"无待审"（503 ≠ 空队列）。
    if (data?.error) {
      return (
        <div className="v2-esc-watcher-chip" data-testid="esc-watch-error">
          ⚠️ 提权审批通道不可用（{data.error}）——请勿据此判断"无待审"
        </div>
      );
    }
    return mutedPending.length > 0 ? (
      <div className="v2-esc-watcher-chip" data-testid="esc-watcher-muted">
        🔕 有 {mutedPending.length} 条提权申请被稍后处理（侧栏"提权"页可查看）
      </div>
    ) : null;
  }

  return (
    <div className="v2-esc-modal-overlay" data-testid="esc-modal">
      <div className="v2-esc-modal">
        <div className="v2-esc-modal-head">
          <span>🔓 提权审批（AI 请求人工放行被硬阻断的操作）</span>
          <button
            type="button"
            className="v2-icon-btn"
            title="稍后处理（不决定，侧栏可再看）"
            onClick={() => {
              setMutedIds((prev) => {
                const s = new Set(prev);
                for (const r of pending) s.add(r.id);
                return s;
              });
              setNewArrival(false);
            }}
          >
            ×
          </button>
        </div>
        {resultMsg && <div className="v2-evo-action-msg" role="status" data-testid="esc-modal-feedback">{resultMsg}</div>}
        {loginRequired && <EscalationLoginPrompt />}
        {data?.error && (
          <div className="v2-esc-hash warn" data-testid="esc-store-error">
            ⚠️ {data.error}——待审列表当前不可用，请勿据此判断"无待审"
          </div>
        )}
        <div className="v2-esc-modal-body">
          {pending
            .filter((r) => !mutedIds.has(r.id))
            .map((r) => (
              <PendingCard key={r.id} req={r} onDecide={decide} onRefresh={reload} onNavigate={() => {
                setMutedIds((prev) => new Set([...prev, ...pending.map((item) => item.id)]));
                setNewArrival(false);
                onNavigate?.();
              }} />
            ))}
        </div>
        <div className="v2-esc-modal-foot">
          普通提权批准后 AI 收到一次性令牌；验证凭证类由 Host 专用签发，
          不提供通用文件写权限。拒绝后 AI 会收到拒绝理由。
          稍后处理或等待超时不会取消待审申请；过期后可从历史返回来源会话重新申请。
        </div>
      </div>
    </div>
  );
}

// ── 侧栏面板 ──
export function EscalationPanel({ onNavigate }: { onNavigate?: () => void } = {}) {
  const { data, reload } = useEscalations(true);
  const [actionMsg, setActionMsg] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const decide = (id: string, decision: "approved" | "denied", note: string, expectedSha256: string) => {
    const submission = submitReview(id, decision, note, expectedSha256);
    if (!submission) return;
    setActionMsg("正在提交审批，请稍候…");
    setLoginRequired(false);
    void submission.then((res) => {
      setActionMsg(res.message);
      setLoginRequired(res.loginRequired);
      if (res.ok || res.stale) reload();
    });
  };
  // ESC-07（FR-07）: 待审走专用 pending 查询；历史保持"最新 50 条"窗口。
  const basePending = data?.pendingRequests || [];
  // R4（M1.1 复审）: 权威计数用 pending_count——待审超过窗口（50）时不再被
  // 截断显示为 50；配合 before_id 稳定游标"加载更多"可单调读完整个队列。
  const pendingCount = data?.pending_count ?? basePending.length;
  const [extraPages, setExtraPages] = useState<EscalationRequest[]>([]);
  const pending = useMemo(() => {
    const seen = new Set(basePending.map((r) => r.id));
    return [...basePending, ...extraPages.filter((r) => !seen.has(r.id))];
  }, [basePending, extraPages]);
  // 待审总数缩水（记录已决/失效离开队列）→ 丢弃续读页防已决残留；用户可重新加载。
  useEffect(() => {
    if (pendingCount < pending.length) setExtraPages([]);
  }, [pendingCount, pending.length]);
  const hasMore = pendingCount > pending.length;
  const loadMore = () => {
    const oldest = pending[pending.length - 1];
    if (!oldest) return;
    void fetchBounded(`/api/v1/escalation/list?status=pending&limit=50&before_id=${encodeURIComponent(oldest.id)}`)
      .then(({ response, body }) => response.ok ? body as { requests?: EscalationRequest[] } | null : null)
      .then((d) => {
        if (Array.isArray(d?.requests)) setExtraPages((prev) => [...prev, ...d.requests!]);
      })
      .catch(() => {
        /* 网络异常：保持现状，下一轮轮询恢复 */
      });
  };
  // R3（M1.1 复审）: 跨进程失效 pending 被待审专用查询排除，但历史区必须
  // 如实呈现（标记"已失效"）——不能因投影状态是 pending 就让它整体消失。
  const history = (data?.requests || []).filter((r) => r.status !== "pending" || r._sig_unverified);
  return (
    <div className="v2-evo" data-testid="escalation-panel">
      <div className="v2-evo-head">
        <span className="v2-evo-title">🔓 {zh.escalationTitle}</span>
        {pendingCount > 0 && <span className="v2-evo-pending-badge">{pendingCount} 待审批</span>}
        <button type="button" className="v2-icon-btn" title={zh.refresh} onClick={() => reload()}>
          ⟳
        </button>
      </div>
      {data?.error && (
        <div className="v2-esc-hash warn" data-testid="esc-store-error">
          ⚠️ {data.error}——待审列表当前不可用；下方列表为最后一次成功读取，可能已过期，请勿据此判断"无待审"
        </div>
      )}
      {actionMsg && (
        <div className="v2-evo-action-msg" data-testid="esc-panel-msg">
          {actionMsg}
        </div>
      )}
      {loginRequired && <EscalationLoginPrompt />}
      <div className="v2-evo-body">
        <div className="v2-esc-sec">待审批 ({pendingCount})</div>
        {/* R2: 只有确认无待审（非错误态且权威计数为 0）才显示空态提示 */}
        {!data?.error && pendingCount === 0 && <div className="v2-tree-loading">（无待审批提权申请）</div>}
        {pending.map((r) => (
          <PendingCard key={r.id} req={r} onDecide={decide} onRefresh={reload} onNavigate={onNavigate} />
        ))}
        {hasMore && (
          <button type="button" className="v2-evo-btn" data-testid="esc-load-more" onClick={loadMore}>
            加载更多（还有 {pendingCount - pending.length} 条待审）
          </button>
        )}
        <div className="v2-esc-sec">最近记录</div>
        {history.length === 0 && <div className="v2-tree-loading">（无历史）</div>}
        {history.map((r) => {
          // FR-03: 跨进程失效的 pending 已被待审专用查询排除，历史视图里
          // 仍如实呈现但标记"已失效"——面板永远无法审批它们（签名校验拒绝）。
          const badge =
            r._sig_unverified && (r.status === "pending" || (r.status === "approved" && r.request_kind !== "verify_receipt"))
              ? { cls: "denied", text: "已失效" }
              : r.request_kind === "verify_receipt" && r.status === "approved"
                ? { cls: "ok", text: "Host 已签发" }
                : statusBadge(r.status);
          return (
            <div key={r.id} className="v2-evo-item">
              <div className="v2-evo-row">
                <span className={`v2-evo-status ${badge.cls}`}>{badge.text}</span>
                <span style={{ opacity: 0.6, fontSize: 11 }}>{fmtTime(r.decided_at || r.created_at)}</span>
              </div>
              <div className="v2-esc-cmd">
                <code>{r.command}</code>
              </div>
              <EscalationOrigin req={r} onNavigate={onNavigate} />
              {r.decision_note && <div className="v2-esc-just">备注: {r.decision_note}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
