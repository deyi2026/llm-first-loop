// Web V2：顶栏（侧栏开关 / 会话主区标题 / 模型选择占位 / 主题切换 / 连接状态）

import { zh } from "../../i18n/zh";
import { useConnection, useLearningPage, useMainView } from "../../core/stores";
import { fetchAuthStatus, fetchHealth, logoutBrowserSession } from "../../core/api";
import { useEffect, useState } from "react";
import { SessionHeaderActions } from "./SessionHeaderActions";

export function TopBar({
  onToggleSidebar,
  onShowFiles,
  onTogglePanel,
  panelOpen = false,
  isMobile = false,
}: {
  onToggleSidebar: () => void;
  onShowFiles?: () => void;
  onTogglePanel?: () => void;
  panelOpen?: boolean;
  isMobile?: boolean;
}) {
  const { ok, version, build, checked } = useConnection();
  const mainView = useMainView();
  const learningPage = useLearningPage();
  const viewTitle = mainView === "services"
    ? "服务身份"
    : mainView === "learning"
      ? (learningPage === "knowledge" ? "知识管理" : "学习通道")
      : "会话";
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
      <span className="v2-topbar-view">{viewTitle}</span>
      <div style={{ flex: 1 }} />
      <SessionHeaderActions onShowFiles={onShowFiles} />
      {isMobile && onTogglePanel ? (
        <button
          type="button"
          className="v2-icon-btn v2-mobile-panel-toggle"
          onClick={onTogglePanel}
          title="右侧面板"
          aria-label="右侧面板"
          aria-expanded={panelOpen}
        >
          ▤
        </button>
      ) : null}
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
          {ok && (build || version) ? ` · ${build || `v${version}`}` : ""}
        </span>
      </div>
    </header>
  );
}

// 连接轮询写入（与组件解耦，避免循环引用）
import { connStore } from "../../core/stores";

function connStoreSet(
  info: { service?: string; version?: string; build?: { display?: string } } | null
): void {
  connStore.set({
    ok: info !== null,
    service: info?.service ?? "",
    version: info?.version ?? "",
    build: info?.build?.display ?? "",
    checked: true,
  });
}
