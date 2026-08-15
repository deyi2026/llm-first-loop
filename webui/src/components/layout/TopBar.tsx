// Web V2：顶栏（侧栏开关 / 会话主区标题 / 模型选择占位 / 主题切换 / 连接状态）

import { zh } from "../../i18n/zh";
import { themeStore, useConnection, useTheme } from "../../core/stores";
import { fetchHealth } from "../../core/api";
import { useEffect } from "react";
import type { ThemePreference } from "../../core/stores";

export function TopBar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const { ok, version, checked } = useConnection();
  const { preference, dark } = useTheme();

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
      <ThemeSwitch preference={preference} dark={dark} />
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

function ThemeSwitch({ preference, dark }: { preference: ThemePreference; dark: boolean }) {
  const items: Array<{ key: ThemePreference; label: string }> = [
    { key: "system", label: zh.themeSystem },
    { key: "light", label: zh.themeLight },
    { key: "dark", label: zh.themeDark },
  ];
  return (
    <div className="v2-theme-switch" data-testid="theme-switch">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          className={preference === it.key ? "active" : ""}
          onClick={() => themeStore.setPreference(it.key)}
          title={`${it.label}（当前${dark ? "暗" : "亮"}）`}
        >
          {it.label}
        </button>
      ))}
    </div>
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
