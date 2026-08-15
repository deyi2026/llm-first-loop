// Web V2：应用根（三栏壳：侧栏 | 会话主区 | 右侧面板；对齐 DSH ui-layout）

import { useEffect, useState } from "react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { RightPanel } from "./components/layout/RightPanel";
import { Conversation } from "./components/conversation/Conversation";
import { initEventStream } from "./core/events";

export function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [isMobile, setIsMobile] = useState(
    typeof matchMedia !== "undefined" && matchMedia("(max-width: 900px)").matches
  );

  useEffect(() => {
    initEventStream(); // SSE 命名事件 + 失联自愈看门狗（对齐 v0.5.6 加固）
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(max-width: 900px)");
    const onChange = () => setIsMobile(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const shellClass = [
    "v2-shell",
    isMobile && sidebarCollapsed ? "mobile-sidebar-open" : "",
    isMobile && !panelOpen ? "mobile-panel-open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClass} data-testid="app-shell">
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
