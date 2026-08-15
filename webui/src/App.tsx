// Web V2：应用根（三栏壳：侧栏 | 会话主区 | 右侧面板；对齐 DSH ui-layout）

import { useState } from "react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { RightPanel } from "./components/layout/RightPanel";
import { Conversation } from "./components/conversation/Conversation";
import { initEventStream } from "./core/events";
import { useEffect } from "react";

export function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);

  useEffect(() => {
    initEventStream(); // SSE 命名事件 + 失联自愈看门狗（对齐 v0.5.6 加固）
  }, []);

  return (
    <div className="v2-shell" data-testid="app-shell">
      <Sidebar collapsed={sidebarCollapsed} />
      <div className="v2-main">
        <TopBar onToggleSidebar={() => setSidebarCollapsed((v) => !v)} />
        <Conversation />
      </div>
      <button
        type="button"
        className="v2-icon-btn"
        style={{ alignSelf: "center" }}
        onClick={() => setPanelOpen((v) => !v)}
        title="右侧面板"
        aria-label="右侧面板"
      >
        {panelOpen ? "▸" : "◂"}
      </button>
      <RightPanel open={panelOpen} />
    </div>
  );
}
