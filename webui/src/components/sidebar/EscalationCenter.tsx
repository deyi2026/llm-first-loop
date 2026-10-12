// 提权闭环 Web 端（EVO-20260923-c58a0bb1 accepted + 用户批准 2026-09-23）:
// EscalationWatcher = 全局挂载的弹窗（pending 出现即弹，人工批准/拒绝）
// EscalationPanel   = 侧栏"提权"页（历史 + 待决列表，与弹窗共用数据层）
// 后端契约: GET /api/v1/escalation/list, POST /api/v1/escalation/review
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { zh } from "../../i18n/zh";

export interface EscalationRequest {
  id: string;
  tool_name: string;
  command: string;
  justification: string;
  session_id: string;
  status: string; // pending | approved | denied | consumed | expired
  created_at: string;
  decided_at: string;
  decided_by: string;
  decision_note: string;
  token_expires_at?: string;
}

interface ListResp {
  requests: EscalationRequest[];
  pending_count: number;
}

const POLL_MS = 5000;

async function fetchEscalations(): Promise<ListResp | null> {
  try {
    const r = await fetch("/api/v1/escalation/list?limit=50");
    if (!r.ok) return null;
    return (await r.json()) as ListResp;
  } catch {
    return null;
  }
}

async function reviewEscalation(
  id: string,
  decision: "approved" | "denied",
  note: string
): Promise<{ ok: boolean; message: string }> {
  try {
    const r = await fetch("/api/v1/escalation/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, decision, note }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok) return { ok: true, message: decision === "approved" ? "已批准（AI 将收到一次性令牌）" : "已拒绝（AI 将收到拒绝理由）" };
    return { ok: false, message: `⚠️ ${String((d as { error?: string }).error || `失败(${r.status})`)}` };
  } catch (err) {
    return { ok: false, message: `请求失败: ${String(err)}` };
  }
}

function useEscalations(enabled = true) {
  const [data, setData] = useState<ListResp | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const load = useCallback(() => {
    void fetchEscalations().then((d) => {
      if (d) {
        setData(d);
        setLoadErr(false);
      } else setLoadErr(true);
    });
  }, []);
  useEffect(() => {
    if (!enabled) return;
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [enabled, load]);
  return { data, loadErr, reload: load };
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

// ── 待决卡片（弹窗与面板共用）──
function PendingCard({
  req,
  busy,
  onDecide,
}: {
  req: EscalationRequest;
  busy: boolean;
  onDecide: (id: string, decision: "approved" | "denied", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const badge = statusBadge(req.status);
  return (
    <div className="v2-evo-item pending" data-testid={`esc-item-${req.id}`}>
      <div className="v2-evo-row">
        <span className={`v2-evo-status ${badge.cls}`}>{badge.text}</span>
        <span style={{ opacity: 0.6, fontSize: 11 }}>{fmtTime(req.created_at)}</span>
      </div>
      <div className="v2-esc-cmd" data-testid={`esc-cmd-${req.id}`}>
        <code>{req.command}</code>
      </div>
      <div className="v2-esc-just">{req.justification}</div>
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
          disabled={busy}
          onClick={() => onDecide(req.id, "approved", note)}
        >
          批准
        </button>
        <button
          type="button"
          className="v2-evo-btn reject"
          disabled={busy}
          onClick={() => onDecide(req.id, "denied", note)}
        >
          拒绝
        </button>
      </div>
    </div>
  );
}

// ── 全局弹窗（用户要求: web 端弹窗，审批后 AI 闭环接收）──
export function EscalationWatcher() {
  const { data, reload } = useEscalations(true);
  const [mutedIds, setMutedIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [resultMsg, setResultMsg] = useState("");
  const prevPendingRef = useRef<Set<string>>(new Set());
  const [newArrival, setNewArrival] = useState(false);

  const pending = useMemo(() => (data?.requests || []).filter((r) => r.status === "pending"), [data]);

  // 新 pending 到达 → 重新弹窗（被"稍后处理"静音过的除外）
  useEffect(() => {
    const cur = new Set(pending.map((r) => r.id));
    let hasNew = false;
    for (const id of cur) if (!prevPendingRef.current.has(id)) hasNew = true;
    prevPendingRef.current = cur;
    if (hasNew) {
      setNewArrival(true);
      setResultMsg("");
    }
  }, [pending]);

  const visible = newArrival && pending.filter((r) => !mutedIds.has(r.id)).length > 0;
  const mutedPending = pending.filter((r) => mutedIds.has(r.id));

  const decide = (id: string, decision: "approved" | "denied", note: string) => {
    setBusy(true);
    void reviewEscalation(id, decision, note).then((res) => {
      setResultMsg(res.message);
      if (res.ok) {
        setMutedIds((prev) => new Set(prev).add(id));
        if (pending.filter((r) => r.id !== id && !mutedIds.has(r.id)).length === 0) setNewArrival(false);
        reload();
      }
      setBusy(false);
    });
  };

  if (!visible) {
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
        {resultMsg && <div className="v2-evo-action-msg">{resultMsg}</div>}
        {pending
          .filter((r) => !mutedIds.has(r.id))
          .map((r) => (
            <PendingCard key={r.id} req={r} busy={busy} onDecide={decide} />
          ))}
        <div className="v2-esc-modal-foot">
          批准后 AI 会收到一次性令牌（10 分钟内有效，绑定本命令，单次使用）；
          拒绝后 AI 会收到拒绝理由并停止重试。
        </div>
      </div>
    </div>
  );
}

// ── 侧栏面板 ──
export function EscalationPanel() {
  const { data, loadErr, reload } = useEscalations(true);
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const decide = (id: string, decision: "approved" | "denied", note: string) => {
    setBusy(true);
    void reviewEscalation(id, decision, note).then((res) => {
      setActionMsg(res.message);
      if (res.ok) reload();
      setBusy(false);
    });
  };
  const pending = (data?.requests || []).filter((r) => r.status === "pending");
  const history = (data?.requests || []).filter((r) => r.status !== "pending");
  return (
    <div className="v2-evo" data-testid="escalation-panel">
      <div className="v2-evo-head">
        <span className="v2-evo-title">🔓 {zh.escalationTitle}</span>
        {pending.length > 0 && <span className="v2-evo-pending-badge">{pending.length} 待审批</span>}
        <button type="button" className="v2-icon-btn" title={zh.refresh} onClick={() => reload()}>
          ⟳
        </button>
      </div>
      {loadErr && <div className="v2-sidebar-error">提权列表加载失败</div>}
      {actionMsg && (
        <div className="v2-evo-action-msg" data-testid="esc-panel-msg">
          {actionMsg}
        </div>
      )}
      <div className="v2-evo-body">
        <div className="v2-esc-sec">待审批 ({pending.length})</div>
        {pending.length === 0 && <div className="v2-tree-loading">（无待审批提权申请）</div>}
        {pending.map((r) => (
          <PendingCard key={r.id} req={r} busy={busy} onDecide={decide} />
        ))}
        <div className="v2-esc-sec">最近记录</div>
        {history.length === 0 && <div className="v2-tree-loading">（无历史）</div>}
        {history.map((r) => {
          const badge = statusBadge(r.status);
          return (
            <div key={r.id} className="v2-evo-item">
              <div className="v2-evo-row">
                <span className={`v2-evo-status ${badge.cls}`}>{badge.text}</span>
                <span style={{ opacity: 0.6, fontSize: 11 }}>{fmtTime(r.decided_at || r.created_at)}</span>
              </div>
              <div className="v2-esc-cmd">
                <code>{r.command}</code>
              </div>
              {r.decision_note && <div className="v2-esc-just">备注: {r.decision_note}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
