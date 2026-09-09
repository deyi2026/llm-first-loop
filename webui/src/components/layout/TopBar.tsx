// Web V2：顶栏（侧栏开关 / 会话主区标题 / 模型选择占位 / 主题切换 / 连接状态）

import { zh } from "../../i18n/zh";
import { useConnection } from "../../core/stores";
import { fetchAuthStatus, fetchHealth, logoutBrowserSession } from "../../core/api";
import { useEffect, useState } from "react";
import { SessionHeaderActions } from "./SessionHeaderActions";

export function TopBar({
  onToggleSidebar,
  onShowFiles,
}: {
  onToggleSidebar: () => void;
  onShowFiles?: () => void;
}) {
  const { ok, version, checked } = useConnection();
  const [browserAuthenticated, setBrowserAuthenticated] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      const info = await fetchHealth();
      if (!alive) return;
      connStoreSet(info);
    };
    void poll();
    const timer = window.setInterval(poll, 10000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    void fetchAuthStatus().then((status) => {
      if (alive) setBrowserAuthenticated(Boolean(status?.browser_login && status.authenticated));
    });
    return () => {
      alive = false;
    };
  }, []);

  const handleLogout = async () => {
    if (!(await logoutBrowserSession())) return;
    setBrowserAuthenticated(false);
    window.location.reload();
  };

  return (
    <header className="v2-topbar" data-testid="topbar">
      <button
        type="button"
        className="v2-icon-btn"
        onClick={onToggleSidebar}
        title={zh.collapseSidebar}
        aria-label={zh.collapseSidebar}
      >
        ☰
      </button>
      <span style={{ fontSize: 13, color: "var(--dsw-alias-label-secondary)" }}>会话</span>
      <div style={{ flex: 1 }} />
      <SessionHeaderActions onShowFiles={onShowFiles} />
      {browserAuthenticated && (
        <button
          type="button"
          className="v2-btn ghost"
          onClick={() => void handleLogout()}
          aria-label="退出登录"
          title="退出登录"
        >
          退出
        </button>
      )}
      <div className={`v2-status-badge ${checked && !ok ? "err" : ""}`} data-testid="status-badge">
        <span className="v2-status-dot" />
        <span>
          {!checked ? "…" : ok ? zh.statusConnected : zh.statusDisconnected}
          {ok && version ? ` · v${version}` : ""}
        </span>
      </div>
    </header>
  );
}

// 连接轮询写入（与组件解耦，避免循环引用）
import { connStore } from "../../core/stores";

function connStoreSet(info: { service?: string; version?: string } | null): void {
  connStore.set({
    ok: info !== null,
    service: info?.service ?? "",
    version: info?.version ?? "",
    checked: true,
  });
}
