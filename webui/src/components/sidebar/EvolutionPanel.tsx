// 演进建议审批面板（Approval UX v2 批 1，2026-08-21 镜像）
// 数据源：GET /api/v1/evolution/list（摘要+impact_hint）/ detail（全文懒加载）
// 决策：review（单条，二次确认+拒绝理由必填+CAS）/ review-batch（批量，服务端跳过 requires_human）
// 交互：分类 Tab / 详情懒加载 / 二次确认 / 拒绝理由必填 / 批量 / 409 冲突提示 / 涉边界禁用批量

import { useEffect, useMemo, useRef, useState } from "react";
import { switchWorkspace } from "../../core/api";
import { writeClipboardText } from "../../core/clipboard";
import { prefillComposer } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { zh } from "../../i18n/zh";

interface EvoItem {
  id: string;
  ts: string;
  status: string;
  priority: string;
  requires_human: boolean;
  content: string;
  impact_hint?: string;
  rejected_reason?: string;
  reviewed_at?: string | null;
  executed_at?: string | null;
  verified_at?: string | null;
  session_id?: string;
}

interface SessionOrigin {
  sessionId: string;
  evoIds: string[];
}

interface ReviewReceipt {
  text: string;
  hint: string;
  origins: SessionOrigin[];
}

interface OriginLocation {
  loading: boolean;
  available?: boolean;
  current?: boolean;
  workspaceId?: string;
  workspacePath?: string;
  reason?: string;
}

interface EvoDetail extends EvoItem {
  scope?: string;
  evidence?: string;
  impact_scope?: string;
  impact_files?: string[];
  reason_history?: { reason: string; at: string }[];
}

interface EvoDiff {
  id: string;
  impact_files?: string[];
  actions?: Record<string, unknown>[];
  note?: string;
}

const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审批",
  accepted: "已接受",
  executing: "执行中",
  executed: "已执行",
  rolled_back: "已回滚",
  failed: "执行失败",
  rejected: "已拒绝",
};

const STATUS_COLOR: Record<string, string> = {
  pending_review: "var(--dsw-alias-state-warning, #d97706)",
  accepted: "var(--dsw-alias-state-success, #16a34a)",
  executing: "var(--dsw-alias-state-info, #2563eb)",
  executed: "var(--dsw-alias-state-info, #2563eb)",
  rolled_back: "var(--dsw-alias-state-error, #dc2626)",
  failed: "var(--dsw-alias-state-error, #dc2626)",
  rejected: "var(--dsw-alias-label-tertiary, #888)",
};

// 状态→阶段文案：区分「审批结果」与「执行结果」。权威枚举为七态状态机
// （src/llm_loop/introspection/evolution.py EvolutionStatus）：pending_review → accepted →
// executing → executed / rolled_back / failed，旁路 rejected。EVO-20261125 修复②。
function statusStageText(status: string): string {
  switch (status) {
    case "pending_review":
      return "待审批";
    case "accepted":
      return "已接受（待执行）";
    case "executing":
      return "已接受，正在执行";
    case "executed":
      return "已接受且执行完成";
    case "rolled_back":
      return "已接受，但已回滚";
    case "failed":
      return "已接受，但执行失败";
    case "rejected":
      return "已拒绝";
    default:
      return `未知状态(${status || "空"})`;
  }
}

const TABS: { key: string; label: string }[] = [
  { key: "pending_review", label: "🔔 待审批" },
  { key: "accepted", label: "✅ 已接受" },
  { key: "rejected", label: "❌ 已拒绝" },
  { key: "executed", label: "⚙ 已执行" },
  { key: "", label: "全部" },
];

function fmtTs(ts: string | undefined | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// EVO-20261125 热修复：审批请求有界等待（覆盖连接建立与响应体读取全过程）。
// 高负载（web 进程 CPU 饱和）时无界 fetch 会让"处理中…"永久悬挂——用户感知"点了没反应"。
const REVIEW_TIMEOUT_MS = 15000;
const VERIFY_TIMEOUT_MS = 10000;
// 已处理状态集合：超时后只读查询到这些状态 = 此前请求已生效（含执行中与执行终态）。
// 权威枚举为七态（src/llm_loop/introspection/evolution.py EvolutionStatus）：
// pending_review → accepted → executing → executed / rolled_back / failed，旁路 rejected。
//（真实案例 EVO-20261125-bb60b1d4：audit 已 accepted 且进入 executing 而前端仍无反馈。）EVO-20261125 修复②。
const HANDLED_STATUS = new Set(["accepted", "rejected", "executing", "executed", "rolled_back", "failed"]);

interface BoundedJson {
  ok: boolean;
  status: number;
  /** 解析成功的 JSON 响应体；体读取超时/中断/非 JSON 时为 null（=结果不明） */
  body: unknown;
}

// 有界请求 helper：deadline 必须覆盖「响应头 + 响应体读取/解析」全程（EVO-20261125 修复①）。
// 旧实现 finally 在收到响应头后即 clearTimeout，r.json() 无界——头到了但体悬挂时调用方仍会永久挂起。
// body 解析失败/中断统一折叠为 body=null，由调用方按「结果不明」处理，绝不伪装成功。
async function fetchBounded(url: string, init: RequestInit, timeoutMs: number): Promise<BoundedJson> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...init, signal: ac.signal });
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      body = null; // 响应体读取被 abort（超时）或非 JSON：一律视为结果不明
    }
    return { ok: r.ok, status: r.status, body };
  } finally {
    clearTimeout(timer);
  }
}

// 「结果不明」锁定（EVO-20261125 修复③）：模块级保存，跨确认弹窗关闭/重开、跨面板重挂载保留，
// 直到获得权威核实（已处理 / 服务端 409 明确拒绝 + 核实仍待审批）才解除。防止重开弹窗静默解锁重发。
const indeterminateLocks = new Set<string>();

export function EvolutionPanel() {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [, setLockVersion] = useState(0); // 仅用于锁定集合变化时触发重渲染
  const busyRef = useRef(false); // 同步双击闸：处理中重复点击不重发（修复③）
  const [items, setItems] = useState<EvoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("pending_review");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, EvoDetail>>({});
  const [viewerSummary, setViewerSummary] = useState<EvoItem | null>(null);
  const [viewerDetail, setViewerDetail] = useState<EvoDetail | null>(null);
  const [viewerDiff, setViewerDiff] = useState<EvoDiff | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerError, setViewerError] = useState("");
  const [viewerDiffMessage, setViewerDiffMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const [confirmMsg, setConfirmMsg] = useState("");
  const [confirm, setConfirm] = useState<{ id: string; decision: string; requires_human?: boolean } | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [extraConfirmChecked, setExtraConfirmChecked] = useState(false); // 涉边界单条批准额外确认勾选（批 1 #9）
  const [authorizeExecChecked, setAuthorizeExecChecked] = useState(false); // 方案A: 人工显式授权自动执行（越过边界拦截）
  // EVO-20260923-6fe23c9b: provider prompt 面硬检查勾选（所有批准必勾）
  const [promptSurfaceChecked, setPromptSurfaceChecked] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // EVO-20261125 热修复：单条审批结果不明时的状态机
  // idle=正常；verifying=正在只读查询真实状态；unknown=查询失败/状态不明（禁止再次提交）；
  // pending_unverified=后端仍待审批且无服务端明确拒绝凭证（无法证明此前请求已终止、可能仍在
  // 服务端处理，禁止再次提交，仅继续只读核实——修复③；旧文案"可安全重试"已被证伪删除）
  const [verifyState, setVerifyState] = useState<"idle" | "verifying" | "unknown" | "pending_unverified">("idle");

  const load = (keepTab = true) => {
    setLoading(true);
    const statusQ = keepTab && tab ? `&status=${encodeURIComponent(tab)}` : "";
    void fetch(`/api/v1/evolution/list?limit=200${statusQ}`)
      .then((r) => (r.ok ? r.json() : { suggestions: [] }))
      .then((d) => setItems(d.suggestions ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(), 30000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const fetchDetail = (id: string) => {
    if (detail[id]) return;
    void fetchBounded(`/api/v1/evolution/detail?id=${encodeURIComponent(id)}`, {}, VERIFY_TIMEOUT_MS)
      .then((res) => (res.ok ? (res.body as EvoDetail | null) : null))
      .then((d) => d && setDetail((prev) => ({ ...prev, [id]: d })))
      .catch(() => undefined);
  };

  const openViewer = (item: EvoItem) => {
    setViewerSummary(item);
    setViewerDetail(null);
    setViewerDiff(null);
    setViewerError("");
    setViewerDiffMessage("");
    setViewerLoading(true);

    void (async () => {
      try {
        // EVO-20261125 修复①：详情/改动摘要读取也走有界 helper（deadline 覆盖响应头+响应体）
        const detailRes = await fetchBounded(
          `/api/v1/evolution/detail?id=${encodeURIComponent(item.id)}`,
          {},
          VERIFY_TIMEOUT_MS
        );
        const detailBody = (detailRes.body ?? {}) as { detail?: string; message?: string };
        if (!detailRes.ok) {
          throw new Error(String(detailBody.detail || detailBody.message || `详情读取失败(${detailRes.status})`));
        }
        const fullDetail = detailRes.body as EvoDetail;
        setViewerDetail(fullDetail);
        setDetail((prev) => ({ ...prev, [item.id]: fullDetail }));

        try {
          const diffRes = await fetchBounded(
            `/api/v1/evolution/diff?id=${encodeURIComponent(item.id)}`,
            {},
            VERIFY_TIMEOUT_MS
          );
          const diffBody = (diffRes.body ?? {}) as { detail?: string; message?: string };
          if (diffRes.ok) {
            setViewerDiff(diffRes.body as EvoDiff);
          } else {
            setViewerDiffMessage(String(diffBody.detail || diffBody.message || "暂无关联改动摘要。"));
          }
        } catch (err) {
          setViewerDiffMessage(`改动摘要读取失败：${err instanceof Error ? err.message : String(err)}`);
        }
      } catch (err) {
        setViewerError(err instanceof Error ? err.message : String(err));
      } finally {
        setViewerLoading(false);
      }
    })();
  };

  const closeViewer = () => {
    setViewerSummary(null);
    setViewerDetail(null);
    setViewerDiff(null);
    setViewerError("");
    setViewerDiffMessage("");
    setViewerLoading(false);
  };

  // 人工审批回执（EVO-20260918-d1182270）: AI 会话无推送 → 生成可复制回执，避免"批了但没人知道"
  // 来源会话（DESIGN-20261030-v1）: 回执区可一键打开提交该建议的原会话并预填回执
  const [reviewReceipt, setReviewReceipt] = useState<ReviewReceipt | null>(null);
  const [originLocations, setOriginLocations] = useState<Record<string, OriginLocation>>({});
  const [originNote, setOriginNote] = useState("");
  const prefetchedOrigins = useRef<Set<string>>(new Set());

  const fetchLocator = async (sid: string): Promise<OriginLocation> => {
    setOriginLocations((prev) => ({ ...prev, [sid]: { ...prev[sid], loading: true } }));
    try {
      const r = await fetch(`/api/v1/evolution/session-locator?session_id=${encodeURIComponent(sid)}`);
      const d = await r.json().catch(() => ({}));
      let res: OriginLocation;
      if (r.status === 400) {
        res = { loading: false, available: false, reason: "invalid_id" };
      } else if (r.ok && d.available) {
        res = {
          loading: false,
          available: true,
          current: Boolean(d.current),
          workspaceId: String(d.workspace_id || ""),
          workspacePath: String(d.workspace_path || ""),
        };
      } else if (r.ok) {
        res = { loading: false, available: false, reason: String(d.reason || "not_found") };
      } else {
        res = { loading: false, available: false, reason: "locator_failed" };
      }
      setOriginLocations((prev) => ({ ...prev, [sid]: res }));
      return res;
    } catch {
      const res: OriginLocation = { loading: false, available: false, reason: "locator_failed" };
      setOriginLocations((prev) => ({ ...prev, [sid]: res }));
      return res;
    }
  };

  const showReceipt = (receipt: ReviewReceipt) => {
    prefetchedOrigins.current = new Set();
    setOriginLocations({});
    setOriginNote("");
    setReviewReceipt(receipt);
  };

  useEffect(() => {
    if (!reviewReceipt) return;
    reviewReceipt.origins.slice(0, 3).forEach((o) => {
      if (prefetchedOrigins.current.has(o.sessionId)) return;
      prefetchedOrigins.current.add(o.sessionId);
      void fetchLocator(o.sessionId);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewReceipt]);

  const originReasonText = (reason?: string): string => {
    switch (reason) {
      case "identity_only":
        return "属于身份会话，web 不可打开";
      case "locator_failed":
        return "定位失败，请稍后重试";
      case "invalid_id":
        return "来源会话标识无效（旧记录）";
      default:
        return "来源会话已被删除";
    }
  };

  const originDisabled = (loc?: OriginLocation): boolean =>
    Boolean(loc?.loading || (loc?.available === false && loc.reason !== "locator_failed"));

  const originLabel = (sid: string): string => {
    const loc = originLocations[sid];
    if (loc?.loading) return "定位中…";
    if (loc?.available && loc.current === false && loc.workspacePath) {
      return `打开来源会话（将切换到 ${loc.workspacePath}）`;
    }
    return "打开来源会话并粘贴";
  };

  const openOriginSession = async (sid: string, text: string) => {
    setOriginNote("");
    let loc = originLocations[sid];
    if (!loc || loc.loading || loc.available === undefined || loc.reason === "locator_failed") {
      loc = await fetchLocator(sid);
    }
    if (!loc.available) {
      setOriginNote(originReasonText(loc.reason));
      return;
    }
    try {
      if (!loc.current) {
        setOriginNote("正在切换工作区…");
        const sw = await switchWorkspace(loc.workspaceId || "");
        if (!sw.ok) {
          setOriginNote(
            sw.status === 409
              ? "当前会话运行中，暂不能切换工作区"
              : sw.status === 403
                ? "目标工作区不在允许根内，无法切换"
                : "工作区切换失败"
          );
          return;
        }
      }
      let hadDraft = false;
      try {
        hadDraft = Boolean(localStorage.getItem(`lfl-draft-${sid}`));
      } catch {
        hadDraft = false;
      }
      sessionStore.setCurrentSession(sid);
      prefillComposer(text);
      setOriginNote(hadDraft ? "该会话已有草稿，回执已追加在末尾" : "回执已填入输入框");
    } catch {
      setOriginNote("切换工作区或打开会话失败，请稍后重试");
    }
  };

  // A successful review inserts a potentially long status and copyable receipt.
  // Keep the result in the list scrollport and expose it immediately even if
  // the user had scrolled down to approve an item near the end of the list.
  useEffect(() => {
    if (reviewReceipt && bodyRef.current) {
      bodyRef.current.scrollTop = 0;
    }
  }, [reviewReceipt]);

  const buildOrigins = (pairs: { evoId: string; sessionId?: string }[]): SessionOrigin[] => {
    const map = new Map<string, string[]>();
    for (const p of pairs) {
      const sid = String(p.sessionId || "").trim();
      if (!sid) continue;
      map.set(sid, [...(map.get(sid) ?? []), p.evoId]);
    }
    return Array.from(map.entries()).map(([sessionId, evoIds]) => ({ sessionId, evoIds }));
  };

  const buildReceipt = (ids: string[], decision: string, reason: string, newStatus?: string) => {
    const time = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    const verb = decision === "accepted" ? "已批准" : "已拒绝";
    const why = decision === "rejected" && reason ? `（理由：${reason}）` : "";
    const status = newStatus ? `，新状态 ${newStatus}` : "";
    return `【人工审批回执】${verb} ${ids.join("、")}${why}（web 面板 ${time}）${status}。AI 会话不会自动收到本操作，请核实 evolution 状态后继续执行。`;
  };

  const copyReceipt = async (text: string) => {
    const { ok } = await writeClipboardText(text);
    if (ok) {
      setActionMsg("回执已复制到剪贴板");
    } else {
      setActionMsg("复制失败，请手动选中回执文本复制");
    }
  };

  // EVO-20261125 热修复：只读查询单条建议的真实状态（超时/网络不明时的唯一恢复手段，绝不自动重复 POST）。
  // 必须核对回执的精确 id 与请求一致——不把查询到的其他条目状态冒充本次核实结果（修复②）。
  const queryStatus = async (id: string): Promise<{ status: string; sessionId: string } | null> => {
    try {
      const res = await fetchBounded(`/api/v1/evolution/detail?id=${encodeURIComponent(id)}`, {}, VERIFY_TIMEOUT_MS);
      const d = res.body as { id?: unknown; status?: unknown; session_id?: unknown } | null;
      if (!res.ok || !d || d.id !== id) return null;
      return { status: String(d.status || ""), sessionId: String(d.session_id || "") };
    } catch {
      return null;
    }
  };

  // POST 结果不明（超时/网络中断/响应体读取中断）：只读查询精确 EVO 状态并按真实状态恢复。
  // 禁止自动重复 POST——查询确认已处理则按已处理展示（含执行中/执行终态，修复②）；
  // 仍待审批时无法证明此前请求已终止（可能仍在服务端处理）→ 锁定提交、仅继续只读核实（修复③）；
  // 状态不明则锁定提交。
  const handleIndeterminate = async (id: string, decision: string, reason: string): Promise<boolean> => {
    setConfirmMsg("请求超时或网络异常，正在查询后端真实状态…");
    setVerifyState("verifying");
    const st = await queryStatus(id);
    if (st && HANDLED_STATUS.has(st.status)) {
      setVerifyState("idle");
      indeterminateLocks.delete(id);
      setLockVersion((v) => v + 1);
      const label = statusStageText(st.status);
      setActionMsg(`ℹ️ 请求超时，但查询确认 ${id} 已被处理（状态：${label}）`);
      setConfirmMsg("");
      showReceipt({
        text: buildReceipt([id], decision, reason, st.status),
        hint: `请求曾超时，但查询确认后端状态已为「${label}」（查询核实，非本次响应回执）。AI 会话不会自动收到推送，请复制发给当前 AI 会话：`,
        origins: buildOrigins([{ evoId: id, sessionId: st.sessionId }]),
      });
      load();
      return true;
    }
    if (st && st.status === "pending_review") {
      setVerifyState("pending_unverified");
      indeterminateLocks.add(id);
      setLockVersion((v) => v + 1);
      const message =
        "请求超时后查询：后端仍为「待审批」。这不能证明此前请求已终止（可能仍在服务端处理），禁止重复提交；请稍后点「查询状态」继续核实。";
      setActionMsg(`⚠️ ${message}`);
      setConfirmMsg(message);
      return false;
    }
    setVerifyState("unknown");
    indeterminateLocks.add(id);
    setLockVersion((v) => v + 1);
    const message = "请求超时且无法确认后端状态：结果不明。已禁止重复提交，请点「查询状态」核实后再操作。";
    setActionMsg(`⚠️ ${message}`);
    setConfirmMsg(message);
    return false;
  };

  // 「查询状态」按钮：状态不明/待核实时的唯一入口（只读查询，按真实状态更新界面）
  const manualQuery = async (): Promise<string> => {
    if (!confirm) return "no_confirm";
    setVerifyState("verifying");
    setConfirmMsg("正在查询后端真实状态…");
    const st = await queryStatus(confirm.id);
    if (st && HANDLED_STATUS.has(st.status)) {
      setVerifyState("idle");
      indeterminateLocks.delete(confirm.id);
      setLockVersion((v) => v + 1);
      const label = statusStageText(st.status);
      setActionMsg(`ℹ️ 查询确认：${confirm.id} 当前状态「${label}」（已处理，无需重复操作）`);
      setConfirmMsg("");
      showReceipt({
        text: `【查询确认】${confirm.id} 当前状态「${label}」（web 面板 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })} 查询核实，非本次提交回执）。AI 会话不会自动收到本操作，请复制发给当前 AI 会话：`,
        hint: "状态已核实。AI 会话不会自动收到推送，请复制发给当前 AI 会话：",
        origins: buildOrigins([{ evoId: confirm.id, sessionId: st.sessionId }]),
      });
      load();
      return "handled";
    }
    if (st && st.status === "pending_review") {
      setVerifyState("pending_unverified");
      indeterminateLocks.add(confirm.id);
      setLockVersion((v) => v + 1);
      setConfirmMsg(
        "后端仍为「待审批」：不能证明此前请求已终止（可能仍在服务端处理）。禁止重复提交，请稍后再次查询核实。"
      );
      return "pending_unverified";
    }
    setVerifyState("unknown");
    indeterminateLocks.add(confirm.id);
    setLockVersion((v) => v + 1);
    setConfirmMsg("查询仍失败或状态不明：重复提交已被禁止。请稍后再点「查询状态」，或稍后刷新列表核实。");
    return "unknown";
  };

  const review = (id: string, decision: string, reason: string, extraConfirm = false, execOverride = false) => {
    if (indeterminateLocks.has(id)) return Promise.resolve(false); // 结果不明锁：绝不重发（修复③）
    if (busyRef.current) return Promise.resolve(false); // 同步双击闸：处理中重复点击不重发（修复③）
    busyRef.current = true;
    setBusy(true);
    setActionMsg("");
    setConfirmMsg("");
    return fetchBounded(
      "/api/v1/evolution/review",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id,
          decision,
          reason,
          expected_status: "pending_review", // CAS：仅待审批可操作
          extra_confirm: extraConfirm, // 涉边界项单条批准额外确认（Approval UX v2 批 1）
          exec_override: execOverride, // 方案A EVO-20260929: 人工显式授权自动执行
        }),
      },
      REVIEW_TIMEOUT_MS
    )
      .then((res) => {
        // 有界 helper 覆盖「响应头 + 响应体」（修复①）：body=null 表示体读取超时/中断/非 JSON
        if (!res.body) return handleIndeterminate(id, decision, reason);
        if (res.status >= 500) {
          // 服务端错误：后端 read-then-approve 非原子，无法证明变更未生效 → 按结果不明处理（修复③）
          return handleIndeterminate(id, decision, reason);
        }
        const d = res.body as { message?: string; detail?: string; new_status?: string; session_id?: string };
        if (res.ok || (res.status >= 400 && res.status < 500)) {
          // 明确回执（成功 / 409 门禁拒绝 / 其他 4xx 权威拒绝）都可证明本次提交结果——解除结果不明锁。
          // 409 = 服务端门禁明确拒绝本次提交（未生效）：可证明条件下允许用户显式重发（修复③）
          indeterminateLocks.delete(id);
          setLockVersion((v) => v + 1);
        }
        const message = res.ok
          ? String(d.message || "已处理")
          : `⚠️ ${String(d.detail || d.message || `失败(${res.status})`)}`;
        setActionMsg(message);
        setConfirmMsg(message);
        if (res.ok) {
          showReceipt({
            text: buildReceipt([id], decision, reason, d.new_status ? String(d.new_status) : undefined),
            hint: "审批已生效。AI 会话不会自动收到推送，请复制回执发给当前 AI 会话：",
            origins: buildOrigins([{ evoId: id, sessionId: d.session_id ? String(d.session_id) : "" }]),
          });
        }
        if (res.status === 409 || res.ok) load();
        return res.ok; // 成功才关闭；失败原因必须留在当前弹窗内可见
      })
      .catch(() => handleIndeterminate(id, decision, reason))
      .finally(() => {
        busyRef.current = false;
        setBusy(false);
      });
  };

  const batchApprove = () => {
    if (selected.size === 0) return;
    if (busyRef.current) return; // 同步双击闸：处理中重复点击不重发（修复③）
    busyRef.current = true;
    setBusy(true);
    setActionMsg("");
    const itemsReq = Array.from(selected).map((id) => ({
      id,
      decision: "accepted",
      expected_status: "pending_review",
    }));
    return fetchBounded(
      "/api/v1/evolution/review-batch",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: itemsReq, decision: "accepted" }),
      },
      REVIEW_TIMEOUT_MS
    )
      .then((res) => {
        if (!res.body || res.status >= 500) {
          // 响应体读取超时/中断/非 JSON，或服务端 5xx（修复①/③）：逐条结果不明——绝不伪装
          // 「成功 0 / 失败 0」式完成，也绝不自动重发。锁定全部所选条目，防单条弹窗静默重发。
          for (const id of Array.from(selected)) indeterminateLocks.add(id);
          setLockVersion((v) => v + 1);
          const message =
            "⚠️ 批量请求超时/网络异常/响应异常：提交结果不明。已锁定所选条目（禁止重复提交），请以「查询状态」或刷新核实真实状态后再决定后续操作。";
          setActionMsg(message);
          setSelected(new Set());
          load();
          return;
        }
        const d = res.body as {
          ok_count?: number;
          fail_count?: number;
          results?: { id?: string; ok?: boolean; session_id?: string }[];
          detail?: string;
          message?: string;
        };
        if (!res.ok) {
          // 服务端权威拒绝（如 400 参数/开关）：未生效，可安全修正后重试；保留勾选便于修正
          setActionMsg(`⚠️ 批量提交失败(${res.status})：${String(d.detail || d.message || "")}`);
          return;
        }
        const ok = d.ok_count ?? 0;
        const fail = d.fail_count ?? 0;
        setActionMsg(`批量完成：成功 ${ok} / 失败 ${fail}`);
        if (ok > 0) {
          const rows = Array.isArray(d.results) ? d.results : [];
          showReceipt({
            text: buildReceipt(Array.from(selected), "accepted", ""),
            hint: `批量批准已生效（成功 ${ok} 条）。AI 会话不会自动收到推送，请复制回执发给当前 AI 会话：`,
            origins: buildOrigins(
              rows
                .filter((row) => row.ok)
                .map((row) => ({
                  evoId: String(row.id || ""),
                  sessionId: String(row.session_id || ""),
                }))
            ),
          });
        }
        for (const id of Array.from(selected)) indeterminateLocks.delete(id); // 明确回执=可证明结果，解锁
        setLockVersion((v) => v + 1);
        setSelected(new Set());
        load();
      })
      .catch(() => {
        // 批量超时/网络中断（EVO-20261125 修复①③）：逐条结果不明——绝不自动重发 POST（防重复执行）；
        // 锁定所选条目 + 只读刷新列表呈现真实状态。仍显示「待审批」的条目可能仍在服务端处理，
        // 需查询核实确认未生效后才可人工决定重试（不得依据"仍待审批"直接断言未生效）。
        for (const id of Array.from(selected)) indeterminateLocks.add(id);
        setLockVersion((v) => v + 1);
        const message =
          "⚠️ 批量请求超时/网络异常：提交结果不明。已锁定所选条目并刷新列表——已生效条目重复提交会被服务端拒绝（不会重复执行）；仍显示「待审批」的条目可能仍在服务端处理，请先查询核实，确认未生效后再人工决定是否重试。";
        setActionMsg(message);
        setSelected(new Set());
        load();
      })
      .finally(() => {
        busyRef.current = false;
        setBusy(false);
      });
  };

  const pendingCount = items.filter((i) => i.status === "pending_review").length;
  const tabItems = useMemo(
    () => (tab ? items.filter((i) => i.status === tab) : items),
    [items, tab]
  );

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="v2-evo" data-testid="evolution-panel">
      <div className="v2-evo-head">
        <span className="v2-evo-title">📋 {zh.evolutionTitle}</span>
        {pendingCount > 0 && (
          <span className="v2-evo-pending-badge">{pendingCount} 待审批</span>
        )}
        <button type="button" className="v2-icon-btn" title={zh.refresh} onClick={() => load()}>
          ⟳
        </button>
      </div>

      {/* 分类 Tab */}
      <div className="v2-evo-tabs" data-testid="evo-tabs">
        {TABS.map((t) => (
          <button
            key={t.key || "all"}
            type="button"
            className={`v2-evo-tab ${tab === t.key ? "active" : ""}`}
            onClick={() => {
              setTab(t.key);
              setSelected(new Set());
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Batch approval remains by the filters while the result/list scrolls. */}
      {tab === "pending_review" && selected.size > 0 && (
        <div className="v2-evo-batchbar" data-testid="evo-batchbar">
          <span>已选 {selected.size} 条</span>
          <button type="button" className="v2-evo-btn approve" disabled={busy} onClick={batchApprove}>
            {busy ? "处理中…" : "批量批准"}
          </button>
          <button
            type="button"
            className="v2-evo-btn ghost"
            disabled={busy}
            onClick={() => setSelected(new Set())}
          >
            清除
          </button>
        </div>
      )}

      <div
        className="v2-evo-body"
        data-testid="evo-scroll-region"
        ref={bodyRef}
        role="region"
        aria-label="演进审批结果与建议"
        tabIndex={0}
      >
        {/* 面板级操作反馈（UX 修复: 原渲染在条目 map 内，条目刷新消失后消息跟着消失 → 用户感知"没反应"） */}
        {actionMsg && (
          <div className="v2-evo-action-msg" data-testid="evo-action-msg" role="status">{actionMsg}</div>
        )}

        {/* 审批回执（EVO-20260918-d1182270）: AI 会话无推送 → 一键复制告知话术，闭环"批完之后下一步" */}
        {reviewReceipt && (
          <div
            className="v2-evo-receipt"
            data-testid="evo-review-receipt"
            style={{ margin: "6px 0", padding: "8px 10px", border: "1px solid #2f6f4f", borderRadius: 8, background: "rgba(47,111,79,0.08)" }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 12 }}>{reviewReceipt.hint}</span>
              <button type="button" className="v2-icon-btn" title="关闭回执" onClick={() => setReviewReceipt(null)}>×</button>
            </div>
            <pre
              data-testid="evo-review-receipt-text"
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", margin: "6px 0 0", fontSize: 12, userSelect: "text" }}
            >
              {reviewReceipt.text}
            </pre>
            <button
              type="button"
              className="v2-evo-btn approve"
              data-testid="evo-review-receipt-copy"
              onClick={() => void copyReceipt(reviewReceipt.text)}
            >
              复制回执
            </button>
            <div style={{ marginTop: 8, fontSize: 12 }} data-testid="evo-origin-block">
              {reviewReceipt.origins.length === 0 ? (
                <span data-testid="evo-origin-none" style={{ color: "#888" }}>
                  来源会话未记录（旧记录）
                </span>
              ) : (
                <>
                  {reviewReceipt.origins.slice(0, 3).map((o) => {
                    const loc = originLocations[o.sessionId];
                    return (
                      <div key={o.sessionId} style={{ marginTop: 4 }}>
                        <span
                          data-testid="evo-origin-sid"
                          style={{ userSelect: "text", wordBreak: "break-all", fontFamily: "ui-monospace, monospace" }}
                        >
                          来源会话：{o.sessionId}
                        </span>
                        {o.evoIds.length > 1 && <span style={{ marginLeft: 6, color: "#888" }}>（{o.evoIds.length} 条建议）</span>}
                        <div style={{ marginTop: 4 }}>
                          <button
                            type="button"
                            className="v2-evo-btn ghost"
                            data-testid="evo-open-origin-session"
                            disabled={originDisabled(loc)}
                            title={loc?.available === false ? originReasonText(loc.reason) : "打开来源会话并粘贴回执"}
                            onClick={() => void openOriginSession(o.sessionId, reviewReceipt.text)}
                          >
                            {originLabel(o.sessionId)}
                          </button>
                          {loc?.available === false && (
                            <span data-testid="evo-origin-reason" style={{ marginLeft: 6, color: "#888" }}>
                              {originReasonText(loc.reason)}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {reviewReceipt.origins.length > 3 && (
                    <div style={{ marginTop: 4, color: "#888" }}>等 {reviewReceipt.origins.length - 3} 个</div>
                  )}
                  {originNote && (
                    <div data-testid="evo-origin-note" role="status" style={{ marginTop: 4 }}>
                      {originNote}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {loading ? (
          <div className="v2-tree-loading">加载中…</div>
        ) : tabItems.length === 0 ? (
          <div className="v2-tree-loading">（无演进建议）</div>
        ) : (
          tabItems.map((it) => (
            <div
              key={it.id}
              className={`v2-evo-item ${it.status === "pending_review" ? "pending" : ""}`}
              data-testid="evo-item"
            >
              <div className="v2-evo-row">
                {it.status === "pending_review" && (
                  <input
                    type="checkbox"
                    className="v2-evo-check"
                    disabled={it.requires_human}
                    title={it.requires_human ? "涉边界不可批量" : "勾选批量"}
                    checked={selected.has(it.id)}
                    onChange={() => toggleSelect(it.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                )}
                <span
                  className="v2-evo-id"
                  title={it.id}
                  onClick={() => {
                    setExpanded(expanded === it.id ? null : it.id);
                    if (expanded !== it.id) fetchDetail(it.id);
                  }}
                >
                  {it.id}
                </span>
                <span className="v2-evo-status" style={{ color: STATUS_COLOR[it.status] ?? "inherit" }}>
                  {STATUS_LABEL[it.status] ?? it.status}
                </span>
                {it.priority && <span className="v2-evo-priority">{it.priority}</span>}
                <span className="v2-evo-ts">{fmtTs(it.ts)}</span>
              </div>
              <div className="v2-evo-summary">{it.content}</div>
              {it.impact_hint && <div className="v2-evo-impact">📎 影响面：{it.impact_hint}</div>}
              <div className="v2-evo-card-actions">
                <button
                  type="button"
                  className="v2-evo-btn ghost"
                  data-testid={`evo-view-${it.id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    openViewer(it);
                  }}
                >
                  查看详情
                </button>
              </div>
              {expanded === it.id && (
                <div className="v2-evo-detail" data-testid="evo-detail">
                  {it.requires_human && <div className="v2-evo-note">⚠ 需人工确认（涉边界，禁止批量）</div>}
                  {detail[it.id]?.evidence && <div className="v2-evo-note">证据：{detail[it.id]?.evidence}</div>}
                  {(detail[it.id]?.impact_files?.length ?? 0) > 0 && (
                    <div className="v2-evo-note">影响文件：{(detail[it.id]?.impact_files ?? []).join(", ")}</div>
                  )}
                  {it.executed_at && <div className="v2-evo-note">执行于 {fmtTs(it.executed_at)}</div>}
                  {it.reviewed_at && <div className="v2-evo-note">审批于 {fmtTs(it.reviewed_at)}</div>}
                  {it.status === "rejected" && it.rejected_reason && (
                    <div className="v2-evo-note reject-reason">理由：{it.rejected_reason}</div>
                  )}
                  {it.status === "pending_review" && (
                    <div className="v2-evo-actions" data-testid="evo-actions">
                      <button
                        className="v2-evo-btn approve"
                        data-testid="evo-approve"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          setRejectReason("");
                          setExtraConfirmChecked(false);
                          setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                          const locked = indeterminateLocks.has(it.id);
                          setVerifyState(locked ? "unknown" : "idle"); // 结果不明锁跨弹窗关闭/重开保留（修复③）
                          setConfirmMsg(locked ? "此条此前一次提交结果不明，已锁定提交；请先点「查询状态」核实真实状态。" : "");
                          setConfirm({ id: it.id, decision: "accepted", requires_human: it.requires_human });
                        }}
                      >
                        ✅ 批准
                      </button>
                      <button
                        className="v2-evo-btn reject"
                        data-testid="evo-reject"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          setRejectReason("");
                          setExtraConfirmChecked(false);
                          setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                          const locked = indeterminateLocks.has(it.id);
                          setVerifyState(locked ? "unknown" : "idle"); // 结果不明锁跨弹窗关闭/重开保留（修复③）
                          setConfirmMsg(locked ? "此条此前一次提交结果不明，已锁定提交；请先点「查询状态」核实真实状态。" : "");
                          setConfirm({ id: it.id, decision: "rejected", requires_human: it.requires_human });
                        }}
                      >
                        ❌ 拒绝
                      </button>
                    </div>
                  )}
                  {it.status !== "pending_review" && <div className="v2-evo-hint">{zh.evoHint}</div>}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* 完整建议审阅层：只读读取既有 detail/diff API，审批仍走原 review 契约。 */}
      {viewerSummary && (
        <div
          className="v2-evo-modal"
          data-testid="evo-detail-modal"
          role="dialog"
          aria-modal="true"
          aria-label={`演进建议 ${viewerSummary.id} 详情`}
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeViewer();
          }}
        >
          <div className="v2-evo-modal-box v2-evo-detail-box">
            <div className="v2-evo-detail-head">
              <div>
                <div className="v2-evo-modal-title">演进建议 · {viewerSummary.id}</div>
                <div className="v2-evo-detail-meta">
                  <span style={{ color: STATUS_COLOR[viewerDetail?.status ?? viewerSummary.status] ?? "inherit" }}>
                    {STATUS_LABEL[viewerDetail?.status ?? viewerSummary.status] ?? (viewerDetail?.status ?? viewerSummary.status)}
                  </span>
                  {(viewerDetail?.priority ?? viewerSummary.priority) && (
                    <span>优先级：{viewerDetail?.priority ?? viewerSummary.priority}</span>
                  )}
                  <span>{fmtTs(viewerDetail?.ts ?? viewerSummary.ts)}</span>
                </div>
              </div>
              <button type="button" className="v2-icon-btn" onClick={closeViewer} aria-label="关闭演进建议详情">✕</button>
            </div>

            <div className="v2-evo-detail-scroll">
              {viewerLoading && <div className="v2-tree-loading">正在读取完整内容…</div>}
              {viewerError && (
                <div className="v2-evo-action-msg" role="alert" data-testid="evo-detail-error">
                  ⚠️ {viewerError}
                </div>
              )}
              {viewerDetail && (
                <>
                  {viewerDetail.requires_human && (
                    <div className="v2-evo-note">⚠ 需人工确认（涉边界，禁止批量）</div>
                  )}
                  <section className="v2-evo-detail-section">
                    <h4>建议内容</h4>
                    <div className="v2-evo-detail-content" data-testid="evo-detail-content">
                      {viewerDetail.content || "（无正文）"}
                    </div>
                  </section>
                  <div className="v2-evo-detail-grid">
                    <section className="v2-evo-detail-section">
                      <h4>作用域</h4>
                      <div>{viewerDetail.scope || "—"}</div>
                    </section>
                    <section className="v2-evo-detail-section">
                      <h4>影响范围</h4>
                      <div>{viewerDetail.impact_scope || viewerSummary.impact_hint || "—"}</div>
                    </section>
                  </div>
                  <section className="v2-evo-detail-section">
                    <h4>证据 / 依据</h4>
                    <div className="v2-evo-detail-content">{viewerDetail.evidence || "（未附证据文本）"}</div>
                  </section>
                  <section className="v2-evo-detail-section">
                    <h4>影响文件</h4>
                    {(viewerDetail.impact_files?.length ?? 0) > 0 ? (
                      <ul className="v2-evo-detail-list">
                        {(viewerDetail.impact_files ?? []).map((path) => <li key={path}>{path}</li>)}
                      </ul>
                    ) : <div>（无文件清单）</div>}
                  </section>
                  <section className="v2-evo-detail-section">
                    <h4>关联改动摘要</h4>
                    {viewerDiff ? (
                      <>
                        {viewerDiff.note && <div className="v2-evo-hint">{viewerDiff.note}</div>}
                        {(viewerDiff.actions?.length ?? 0) > 0 ? (
                          <div className="v2-evo-diff-actions" data-testid="evo-diff-actions">
                            {(viewerDiff.actions ?? []).map((action, index) => (
                              <pre key={index} className="v2-evo-diff-action">{JSON.stringify(action, null, 2)}</pre>
                            ))}
                          </div>
                        ) : <div>（无 action 摘要）</div>}
                      </>
                    ) : <div className="v2-evo-hint">{viewerDiffMessage || "正在读取改动摘要…"}</div>}
                  </section>
                  {(viewerDetail.reason_history?.length ?? 0) > 0 && (
                    <section className="v2-evo-detail-section">
                      <h4>理由历史</h4>
                      <ul className="v2-evo-detail-list">
                        {(viewerDetail.reason_history ?? []).map((entry, index) => (
                          <li key={`${entry.at}-${index}`}>{fmtTs(entry.at)} · {entry.reason}</li>
                        ))}
                      </ul>
                    </section>
                  )}
                  <section className="v2-evo-detail-section">
                    <h4>状态时间</h4>
                    <div className="v2-evo-detail-meta v2-evo-detail-meta-wrap">
                      {viewerDetail.reviewed_at && <span>审批：{fmtTs(viewerDetail.reviewed_at)}</span>}
                      {viewerDetail.executed_at && <span>执行：{fmtTs(viewerDetail.executed_at)}</span>}
                      {viewerDetail.verified_at && <span>验证：{fmtTs(viewerDetail.verified_at)}</span>}
                      {!viewerDetail.reviewed_at && !viewerDetail.executed_at && !viewerDetail.verified_at && <span>尚无后续状态时间</span>}
                    </div>
                    {viewerDetail.status === "rejected" && viewerDetail.rejected_reason && (
                      <div className="v2-evo-note reject-reason">拒绝理由：{viewerDetail.rejected_reason}</div>
                    )}
                  </section>
                </>
              )}
            </div>
            <div className="v2-evo-modal-actions v2-evo-detail-actions">
              {viewerDetail?.status === "pending_review" && (
                <>
                  <button
                    type="button"
                    className="v2-evo-btn approve"
                    data-testid="evo-detail-approve"
                    disabled={busy}
                    onClick={() => {
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                      const locked = indeterminateLocks.has(viewerDetail.id);
                      setVerifyState(locked ? "unknown" : "idle"); // 结果不明锁跨弹窗关闭/重开保留（修复③）
                      setConfirmMsg(locked ? "此条此前一次提交结果不明，已锁定提交；请先点「查询状态」核实真实状态。" : "");
                      setConfirm({ id: viewerDetail.id, decision: "accepted", requires_human: viewerDetail.requires_human });
                    }}
                  >
                    ✅ 批准
                  </button>
                  <button
                    type="button"
                    className="v2-evo-btn reject"
                    data-testid="evo-detail-reject"
                    disabled={busy}
                    onClick={() => {
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                      const locked = indeterminateLocks.has(viewerDetail.id);
                      setVerifyState(locked ? "unknown" : "idle"); // 结果不明锁跨弹窗关闭/重开保留（修复③）
                      setConfirmMsg(locked ? "此条此前一次提交结果不明，已锁定提交；请先点「查询状态」核实真实状态。" : "");
                      setConfirm({ id: viewerDetail.id, decision: "rejected", requires_human: viewerDetail.requires_human });
                    }}
                  >
                    ❌ 拒绝
                  </button>
                </>
              )}
              <button type="button" className="v2-evo-btn ghost" onClick={closeViewer}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* 二次确认弹层 */}
      {confirm && (
        <div className="v2-evo-modal" data-testid="evo-confirm-modal">
          <div className="v2-evo-modal-box">
            <div className="v2-evo-modal-title">
              {confirm.decision === "accepted" ? "确认批准" : "确认拒绝"} {confirm.id}？
            </div>
            {confirm.decision === "accepted" ? (
              <div className="v2-evo-modal-note">
                批准后按权限自动执行（EVOLVE_LOCAL_EXEC 分级）。
                <label className="v2-evo-modal-check">
                  <input
                    type="checkbox"
                    data-testid="evo-prompt-surface-check"
                    checked={promptSurfaceChecked}
                    onChange={(e) => setPromptSurfaceChecked(e.target.checked)}
                  />
                  已核对：本变更不新增/修改进入 provider prompt 的程序性内容（开场附录/常驻提醒/工具
                  schema 策略文字）；若是，已附 L2-2/L2-6 准入理由与弱模型行为对照（EVO-20260923-6fe23c9b）
                </label>
                {confirm.requires_human && (
                  <label className="v2-evo-modal-check">
                    <input
                      type="checkbox"
                      data-testid="evo-extra-confirm"
                      checked={extraConfirmChecked}
                      onChange={(e) => setExtraConfirmChecked(e.target.checked)}
                    />
                    我已知悉此建议涉及安全边界，确认单条批准
                  </label>
                )}
                <label className="v2-evo-modal-check">
                  <input
                    type="checkbox"
                    data-testid="evo-authorize-exec"
                    checked={authorizeExecChecked}
                    onChange={(e) => setAuthorizeExecChecked(e.target.checked)}
                  />
                  {confirm.requires_human
                    ? "批准并显式授权 AI 自动执行（方案A：人工逐条授权越过边界拦截与执行档位；勾选即视为安全边界确认）"
                    : "批准并显式授权 AI 自动执行（人工逐条授权越过 EVOLVE_LOCAL_EXEC 档位；AI 仍不得自授该字段）"}
                </label>
              </div>
            ) : (
              <div className="v2-evo-modal-note">
                拒绝理由（必填，留痕）：
                <input
                  className="v2-evo-reason-input"
                  data-testid="evo-reason-input"
                  value={rejectReason}
                  maxLength={500}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="请输入拒绝理由…"
                />
              </div>
            )}
            {confirmMsg ? (
              <div className="v2-evo-action-msg" role="status" data-testid="evo-confirm-message">
                {confirmMsg}
              </div>
            ) : null}
            {confirm.decision === "accepted" && !promptSurfaceChecked ? (
              <div className="v2-evo-action-msg">请先勾选 Provider Prompt 影响核对，再执行批准。</div>
            ) : null}
            {confirm.decision === "accepted" && confirm.requires_human && !extraConfirmChecked && !authorizeExecChecked ? (
              <div className="v2-evo-action-msg">请先勾选安全边界确认或显式授权执行，再执行批准。</div>
            ) : null}
            <div className="v2-evo-modal-actions">
              <button
                className="v2-evo-btn approve"
                disabled={
                  busy ||
                  indeterminateLocks.has(confirm.id) || // 结果不明锁：跨弹窗关闭/重开保留（修复③）
                  verifyState === "unknown" ||
                  verifyState === "pending_unverified" ||
                  verifyState === "verifying" ||
                  (confirm.decision === "rejected" && !rejectReason.trim()) ||
                  (confirm.decision === "accepted" && !promptSurfaceChecked) ||
                  (confirm.decision === "accepted" && confirm.requires_human && !extraConfirmChecked && !authorizeExecChecked)
                }
                data-testid="evo-confirm-ok"
                onClick={() => {
                  void review(
                    confirm.id,
                    confirm.decision,
                    confirm.decision === "rejected" ? rejectReason.trim() : "",
                    confirm.requires_human ? extraConfirmChecked : false,
                    authorizeExecChecked
                  ).then((ok) => {
                    if (ok) {
                      setConfirm(null); // UX 修复: 成功才关弹窗；失败保持弹窗可重试（消息面板级显示）
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                      setConfirmMsg("");
                      if (viewerSummary?.id === confirm.id) closeViewer();
                    }
                  });
                }}
              >
                {busy
                  ? "处理中…"
                  : verifyState === "verifying"
                    ? "查询中…"
                    : verifyState === "unknown" || verifyState === "pending_unverified"
                      ? "禁止重复提交"
                      : "确定"}
              </button>
              {verifyState !== "idle" ? (
                <button
                  type="button"
                  className="v2-evo-btn ghost"
                  data-testid="evo-query-status"
                  disabled={verifyState === "verifying"}
                  onClick={() => void manualQuery()}
                >
                  {verifyState === "verifying" ? "查询中…" : "查询状态"}
                </button>
              ) : null}
              <button
                className="v2-evo-btn ghost"
                disabled={busy}
                onClick={() => {
                  setConfirm(null);
                  setRejectReason("");
                  setExtraConfirmChecked(false);
                  setAuthorizeExecChecked(false);
                  setPromptSurfaceChecked(false);
                  setConfirmMsg("");
                  setVerifyState("idle");
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
