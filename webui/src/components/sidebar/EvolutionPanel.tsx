// 演进建议审批面板（Approval UX v2 批 1，2026-08-21 镜像）
// 数据源：GET /api/v1/evolution/list（摘要+impact_hint）/ detail（全文懒加载）
// 决策：review（单条，二次确认+拒绝理由必填+CAS）/ review-batch（批量，服务端跳过 requires_human）
// 交互：分类 Tab / 详情懒加载 / 二次确认 / 拒绝理由必填 / 批量 / 409 冲突提示 / 涉边界禁用批量

import { useEffect, useMemo, useState } from "react";
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
}

interface EvoDetail extends EvoItem {
  scope?: string;
  evidence?: string;
  impact_scope?: string;
  impact_files?: string[];
  reason_history?: { reason: string; at: string }[];
}

const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审批",
  accepted: "已接受",
  executed: "已执行",
  rejected: "已拒绝",
};

const STATUS_COLOR: Record<string, string> = {
  pending_review: "var(--dsw-alias-state-warning, #d97706)",
  accepted: "var(--dsw-alias-state-success, #16a34a)",
  executed: "var(--dsw-alias-state-info, #2563eb)",
  rejected: "var(--dsw-alias-label-tertiary, #888)",
};

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

export function EvolutionPanel() {
  const [items, setItems] = useState<EvoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("pending_review");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, EvoDetail>>({});
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const [confirm, setConfirm] = useState<{ id: string; decision: string; requires_human?: boolean } | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [extraConfirmChecked, setExtraConfirmChecked] = useState(false); // 涉边界单条批准额外确认勾选（批 1 #9）
  const [selected, setSelected] = useState<Set<string>>(new Set());

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
    void fetch(`/api/v1/evolution/detail?id=${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setDetail((prev) => ({ ...prev, [id]: d })))
      .catch(() => undefined);
  };

  const review = (id: string, decision: string, reason: string, extraConfirm = false) => {
    setBusy(true);
    setActionMsg("");
    return fetch("/api/v1/evolution/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id,
        decision,
        reason,
        expected_status: "pending_review", // CAS：仅待审批可操作
        extra_confirm: extraConfirm, // 涉边界项单条批准额外确认（Approval UX v2 批 1）
      }),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({ message: r.statusText }));
        if (r.status === 409) {
          setActionMsg("⚠️ " + (d.detail || "状态已变化，已刷新"));
          load();
        } else {
          setActionMsg(d.message || (r.ok ? "已处理" : `失败(${r.status})`));
          if (r.ok) load();
        }
      })
      .catch((err) => setActionMsg(`请求失败: ${String(err)}`))
      .finally(() => setBusy(false));
  };

  const batchApprove = () => {
    if (selected.size === 0) return;
    setBusy(true);
    setActionMsg("");
    const itemsReq = Array.from(selected).map((id) => ({
      id,
      decision: "accepted",
      expected_status: "pending_review",
    }));
    return fetch("/api/v1/evolution/review-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: itemsReq, decision: "accepted" }),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({ results: [] }));
        const ok = d.ok_count ?? 0;
        const fail = d.fail_count ?? 0;
        setActionMsg(`批量完成：成功 ${ok} / 失败 ${fail}`);
        setSelected(new Set());
        load();
      })
      .catch((err) => setActionMsg(`批量请求失败: ${String(err)}`))
      .finally(() => setBusy(false));
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

      {/* 批量栏（仅待审批 Tab + 有可选） */}
      {tab === "pending_review" && selected.size > 0 && (
        <div className="v2-evo-batchbar" data-testid="evo-batchbar">
          <span>已选 {selected.size} 条</span>
          <button type="button" className="v2-evo-btn approve" disabled={busy} onClick={batchApprove}>
            批量批准
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

      <div className="v2-evo-body">
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
                          setConfirm({ id: it.id, decision: "rejected", requires_human: it.requires_human });
                        }}
                      >
                        ❌ 拒绝
                      </button>
                    </div>
                  )}
                  {actionMsg && <div className="v2-evo-action-msg" data-testid="evo-action-msg">{actionMsg}</div>}
                  {it.status !== "pending_review" && <div className="v2-evo-hint">{zh.evoHint}</div>}
                </div>
              )}
            </div>
          ))
        )}
      </div>

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
            <div className="v2-evo-modal-actions">
              <button
                className="v2-evo-btn approve"
                disabled={
                  busy ||
                  (confirm.decision === "rejected" && !rejectReason.trim()) ||
                  (confirm.decision === "accepted" && confirm.requires_human && !extraConfirmChecked)
                }
                data-testid="evo-confirm-ok"
                onClick={() => {
                  void review(
                    confirm.id,
                    confirm.decision,
                    confirm.decision === "rejected" ? rejectReason.trim() : "",
                    confirm.requires_human ? extraConfirmChecked : false
                  );
                  setConfirm(null);
                  setRejectReason("");
                }}
              >
                确定
              </button>
              <button
                className="v2-evo-btn ghost"
                onClick={() => {
                  setConfirm(null);
                  setRejectReason("");
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
