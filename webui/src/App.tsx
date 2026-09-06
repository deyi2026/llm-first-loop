// Web V2：应用根（三栏壳：侧栏 | 会话主区 | 右侧面板；对齐 DSH ui-layout）

import { useEffect, useState } from "react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { RightPanel } from "./components/layout/RightPanel";
import { Conversation } from "./components/conversation/Conversation";
import { initEventStream } from "./core/events";
import { InteropNotice } from "./components/InteropNotice";

export function App() {
  // 2026-09-04 修复: sidebarCollapsed 曾同时承担"桌面收起"与"移动抽屉打开"两种相反语义，
  // 导致移动端点 ☰ 拉出抽屉时渲染 48px collapsed 空壳（会话/演进/归档全部不可见）。
  // 拆分为两个独立状态：sidebarCollapsed（桌面收起）/ mobileSidebarOpen（移动抽屉开合）。
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(true);
  const [isMobile, setIsMobile] = useState(
    typeof matchMedia !== "undefined" && matchMedia("(max-width: 900px)").matches
  );

  useEffect(() => {
    initEventStream(); // SSE 命名事件 + 失联自愈看门狗（对齐 v0.5.6 加固）
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(max-width: 900px)");
    const onChange = () => {
      setIsMobile(mq.matches);
      if (!mq.matches) setMobileSidebarOpen(false); // 切回桌面自动收抽屉
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggleSidebar = () => {
    if (isMobile) setMobileSidebarOpen((v) => !v);
    else setSidebarCollapsed((v) => !v);
  };

  const shellClass = [
    "v2-shell",
    isMobile && mobileSidebarOpen ? "mobile-sidebar-open" : "",
    isMobile && !panelOpen ? "mobile-panel-open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClass} data-testid="app-shell">
      <Sidebar collapsed={!isMobile && sidebarCollapsed} />
      {isMobile && mobileSidebarOpen && (
        <div className="v2-scrim" data-testid="sidebar-scrim" onClick={() => setMobileSidebarOpen(false)} />
      )}
      <div className="v2-main">
        <TopBar onToggleSidebar={toggleSidebar} />
        <InteropNotice />
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
