// Web V2：侧边栏（会话列表只读展示：标题/预览/来源通道标签/激活态）
// 阶段 1 骨架——搜索/置顶/删除/fork 等交互在阶段 3 接入。

import { useEffect, useState } from "react";
import { channelLabel, type SessionMeta } from "../../core/api";
import { refreshSessionsAndCurrent } from "../../core/events";
import { sessionStore, useCurrentSessionId, useSessions } from "../../core/stores";
import { zh } from "../../i18n/zh";

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const pad = (n: number) => String(n).padStart(2, "0");
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  const sessions = useSessions();
  const currentId = useCurrentSessionId();
  const [query, setQuery] = useState("");

  useEffect(() => {
    void refreshSessionsAndCurrent();
  }, []);

  const filtered = sessions.filter((s) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (s.title || "").toLowerCase().includes(q) ||
      (s.last_message_preview || "").toLowerCase().includes(q)
    );
  });

  if (collapsed) {
    return (
      <aside className="v2-sidebar collapsed" data-testid="sidebar">
        <div className="v2-brand">
          <span className="v2-brand-logo">L</span>
        </div>
      </aside>
    );
  }

  return (
    <aside className="v2-sidebar" data-testid="sidebar">
      <div className="v2-brand">
        <span className="v2-brand-logo">L</span>
        <span>{zh.brand}</span>
        <span style={{ color: "var(--dsw-alias-label-tertiary)", fontWeight: 400, fontSize: 12 }}>
          {zh.brandSub}
        </span>
      </div>
      <button type="button" className="v2-new-session" data-testid="new-session">
        ＋ {zh.newSession}
      </button>
      <input
        className="v2-session-search"
        type="text"
        placeholder={zh.searchPlaceholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label={zh.searchPlaceholder}
      />
      <div className="v2-session-list" data-testid="session-list">
        {filtered.map((s: SessionMeta) => (
          <button
            key={s.session_id}
            type="button"
            className={`v2-session-item ${s.session_id === currentId ? "active" : ""}`}
            onClick={() => {
              sessionStore.setCurrentSession(s.session_id);
            }}
            data-testid="session-item"
          >
            <span className="v2-session-title">{s.title || "未命名"}</span>
            <span className="v2-session-preview">
              {s.last_message_preview || "（空会话）"}
              {s.updated_at ? ` · ${formatTime(s.updated_at)}` : ""}
            </span>
            <span className="v2-channel-tag">{channelLabel(s.channel)}</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <div style={{ padding: 12, fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
            {query ? "无匹配会话" : "暂无会话"}
          </div>
        )}
      </div>
      <div className="v2-sidebar-footer">
        <span>{zh.sessionCount.replace("{n}", String(sessions.length))}</span>
      </div>
    </aside>
  );
}
