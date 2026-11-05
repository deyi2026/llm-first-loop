// 总协调通道栏（常驻条，非 tab）：一眼看到多少 lane 在跑、多少协作请求待处理、多少需人工决策。
// 后端契约: GET /api/v1/coordination/board 在 LaneBoard 契约之上新增可选 channel 段（主会话实现中）:
//   channel?: { active_lanes, pending_help, blocking_help, needs_decision, sessions[] }
// 三态纪律（对齐 LaneBoard）：channel 缺失 → 灰色「协调数据不可用」（不得当 0）；
//   请求失败 → 错误态 + 重试（已有旧数据时保留展示并叠加提示）；正常 → 计数主行 + 可展开 sessions。
// 文案说明：i18n/zh.ts 不在本次允许改动文件清单内（只写 2 文件），故用字面量中文，后续可集中迁移。
// 复用约定：POLL_MS=10000 轮询 / fetchBoard 形态 / 内联 style / formatRelative（WorkspaceGroups 已导出）。
// 注：本文件不使用模板字面量（写作通道限制），统一字符串拼接。

import { useCallback, useEffect, useState } from "react";
import { sidebarViewStore, useSidebarView } from "../../core/stores";
import { formatRelative } from "./WorkspaceGroups";

interface ChannelSession {
  session_id: string;
  lane_id: string;
  goal_id: string;
  branch: string;
  status: string;
  last_activity: string;
}

interface ChannelBlock {
  active_lanes: number;
  pending_help: number;
  blocking_help: number;
  needs_decision: number;
  /** 卡在合并队列等串行位的 lane 数（该看队列，不是自己的活） */
  merging_pending?: number;
  /** 基线已落后 main、合并前必须重验的在途 lane 数（该自己 rebase） */
  baseline_stale?: number;
  sessions: ChannelSession[];
  /** 未决协助条目（后端 channel.help_items）：只给计数等于有数无门 */
  help_items?: Array<{
    id: string;
    need: string;
    topic: string;
    from_session: string;
    to_session: string;
    lane_id: string;
    since: string;
  }>;
}

/** board 响应只声明本组件关心的部分（其余字段归 LaneBoard 契约） */
interface BoardResp {
  channel?: ChannelBlock | null;
}

const POLL_MS = 10000;

/** channel 三态状态：undefined = 首次加载中；null = 请求成功但 channel 段缺失；对象 = 正常 */
type ChannelState = ChannelBlock | null | undefined;

/** fetch 结果显式区分三态：请求失败 ≠ channel 段缺失（后者是后端未提供，不得当 0） */
type FetchResult =
  | { kind: "ok"; channel: ChannelBlock | null }
  | { kind: "error" };

async function fetchChannel(): Promise<FetchResult> {
  try {
    const r = await fetch("/api/v1/coordination/board");
    if (!r.ok) return { kind: "error" };
    const body = (await r.json()) as BoardResp | null;
    if (!body || typeof body !== "object" || body.channel == null) {
      return { kind: "ok", channel: null };
    }
    return { kind: "ok", channel: body.channel };
  } catch {
    return { kind: "error" };
  }
}

export function CoordinationChannel({ collapsed }: { collapsed: boolean }) {
  const [channel, setChannel] = useState(undefined as ChannelState);
  const [loadErr, setLoadErr] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const view = useSidebarView();

  const load = useCallback(() => {
    void fetchChannel().then((res) => {
      if (res.kind === "error") {
        setLoadErr(true); // 保留旧数据（若有）叠加提示——LaneBoard 同款纪律
      } else {
        setLoadErr(false);
        setChannel(res.channel);
      }
    });
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  // 点击主行：不在 lanes 视图 → 先切过去；已在 → 切换本条展开/折叠
  const onMainRowClick = () => {
    if (view !== "lanes") {
      sidebarViewStore.setView("lanes");
      return;
    }
    setExpanded((v) => !v);
  };

  // 侧栏收起态：仅 🛤 图标 + 计数徽标，不渲染文字行（三态仍如实呈现，不伪造 0）
  if (collapsed) {
    let badge: string;
    let badgeColor: string | undefined;
    let title: string;
    if (channel === undefined && !loadErr) {
      badge = "…";
      title = "协调数据加载中…";
    } else if (channel === undefined && loadErr) {
      badge = "!";
      badgeColor = "#e53e3e";
      title = "协调数据取数失败；展开侧栏后可重试";
    } else if (channel == null) {
      badge = "—";
      title = "协调数据不可用";
    } else {
      badge = String(channel.active_lanes);
      badgeColor =
        channel.blocking_help > 0
          ? "#e53e3e"
          : channel.needs_decision > 0
            ? "#d69e2e"
            : undefined;
      title =
        "协调 " + channel.active_lanes + " 活跃 · " + channel.pending_help + " 待协助" +
        (channel.blocking_help > 0 ? " · ⛔ " + channel.blocking_help + " 等答复" : "") +
        ((channel.merging_pending ?? 0) > 0
          ? " · 🔀 " + channel.merging_pending + " 合并中"
          : "") +
        ((channel.baseline_stale ?? 0) > 0
          ? " · 📉 " + channel.baseline_stale + " 待重验"
          : "");
    }
    return (
      <div
        data-testid="coordination-channel-collapsed"
        title={title}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          padding: "6px 0",
          fontSize: 12,
        }}
      >
        <span aria-hidden>🛤</span>
        <span
          data-testid="coordination-channel-badge"
          style={{
            minWidth: 16,
            textAlign: "center",
            borderRadius: 8,
            padding: "0 5px",
            background: "rgba(128,128,128,0.2)",
            color: badgeColor,
          }}
        >
          {badge}
        </span>
      </div>
    );
  }

  return (
    <div data-testid="coordination-channel" style={{ padding: "6px 12px", fontSize: 12 }}>
      {/* 请求失败：错误态 + 重试（不静默空白；已有旧数据时保留展示并叠加提示） */}
      {loadErr && (
        <div
          className="v2-sidebar-error"
          role="alert"
          data-testid="coordination-channel-error"
          style={{ marginBottom: 4 }}
        >
          协调数据取数失败。
          <button type="button" className="v2-ws-session-toggle" onClick={() => load()}>
            重试
          </button>
        </div>
      )}

      {/* 首次加载中（尚无任何数据） */}
      {channel === undefined && !loadErr && (
        <div className="v2-tree-loading" role="status" data-testid="coordination-channel-loading">
          协调数据加载中…
        </div>
      )}

      {/* channel 段缺失：灰色不可用（后端未提供，不得当作 0 显示） */}
      {channel === null && (
        <div data-testid="coordination-channel-missing" role="status" style={{ opacity: 0.6 }}>
          🛤 协调数据不可用
        </div>
      )}

      {channel ? (
        <>
          <button
            type="button"
            data-testid="coordination-channel-row"
            onClick={onMainRowClick}
            title={view === "lanes" ? (expanded ? "折叠会话列表" : "展开会话列表") : "打开协同看板"}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              background: "transparent",
              border: "none",
              padding: "4px 6px",
              borderRadius: 6,
              cursor: "pointer",
              fontSize: 12,
              color: "inherit",
            }}
          >
            <span>🛤 协调 {channel.active_lanes} 活跃</span>
            {" · "}
            <span style={channel.blocking_help > 0 ? { color: "#e53e3e", fontWeight: 600 } : undefined}>
              {channel.pending_help} 待协助
            </span>
            {channel.blocking_help > 0 ? (
              <span style={{ color: "#e53e3e", fontWeight: 600 }}>
                {" · ⛔ "}{channel.blocking_help} 等答复
              </span>
            ) : null}
            {(channel.merging_pending ?? 0) > 0 ? (
              <span style={{ color: "#d69e2e" }}>
                {" · 🔀 "}{channel.merging_pending} 合并中
              </span>
            ) : null}
            {(channel.baseline_stale ?? 0) > 0 ? (
              <span style={{ color: "#d69e2e" }}>
                {" · 📉 "}{channel.baseline_stale} 待重验
              </span>
            ) : null}
            <span aria-hidden style={{ opacity: 0.6, float: "right" }}>
              {expanded ? "▾" : "▸"}
            </span>
          </button>

          {/* 展开态：sessions 列表（空列表显示空态，不静默空白） */}
          {expanded && (
            <div
              data-testid="coordination-channel-sessions"
              style={{ marginTop: 4, borderTop: "1px solid rgba(128,128,128,0.25)", paddingTop: 4 }}
            >
              {Array.isArray(channel.sessions) && channel.sessions.length > 0 ? (
                channel.sessions.map((s, i) => {
                  return (
                    <div
                      key={s.session_id + "-" + i}
                      data-testid="coordination-channel-session"
                      title={s.session_id + " · " + s.branch + " · " + s.status + " · " + (s.last_activity || "")}
                      style={{
                        padding: "3px 6px",
                        opacity: 0.85,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      <code>{(s.session_id || "").slice(0, 8)}</code> · {s.branch || "—"} · {s.status || "—"}
                      {s.last_activity ? " · " + formatRelative(s.last_activity) : ""}
                    </div>
                  );
                })
              ) : (
                <div data-testid="coordination-channel-empty" style={{ opacity: 0.6, padding: "3px 6px" }}>
                  暂无活跃 lane
                </div>
              )}
              {Array.isArray(channel.help_items) && channel.help_items.length > 0 ? (
                <div data-testid="coordination-channel-help" style={{ marginTop: 4 }}>
                  {channel.help_items.slice(0, 5).map((h, i) => {
                    return (
                      <div
                        key={(h.id || "") + "-" + i}
                        data-testid="coordination-channel-help-item"
                        title={(h.topic || "") + " · from " + (h.from_session || "?") + " · " + (h.since || "")}
                        style={{
                          padding: "3px 6px",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          color: h.need === "block" ? "#e53e3e" : "inherit",
                        }}
                      >
                        {(h.need === "block" ? "\u26d4 " : "\u2753 ") + (h.topic || h.id || "未命名") + " · " + (h.from_session || "").slice(0, 8)}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
