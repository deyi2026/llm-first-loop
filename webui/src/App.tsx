// Web V2：应用根（三栏壳：侧栏 | 会话主区 | 右侧面板；对齐 DSH ui-layout）

import { useEffect, useState } from "react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { RightPanel } from "./components/layout/RightPanel";
import { Conversation } from "./components/conversation/Conversation";
import { initEventStream } from "./core/events";
import { probeSessionCapabilities } from "./core/capabilities";
import { InteropNotice } from "./components/InteropNotice";
import {
  sidebarViewStore,
  useCurrentSessionId,
  useNewSessionPending,
} from "./core/stores";
import { syncSessionIdInLocation } from "./core/sessionUrl";

export function App() {
  // 2026-09-04 修复: sidebarCollapsed 曾同时承担"桌面收起"与"移动抽屉打开"两种相反语义，
  // 导致移动端点 ☰ 拉出抽屉时渲染 48px collapsed 空壳（会话/演进/归档全部不可见）。
  // 拆分为两个独立状态：sidebarCollapsed（桌面收起）/ mobileSidebarOpen（移动抽屉开合）。
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(
    typeof matchMedia !== "undefined" && matchMedia("(max-width: 900px)").matches
  );
  // 2026-09-09 修复: 移动端面板抽屉按需打开（初始收起），桌面保持默认常驻，避免首屏被全高抽屉盖住。
  const [panelOpen, setPanelOpen] = useState(!isMobile);
  const currentSessionId = useCurrentSessionId();
  const newSessionPending = useNewSessionPending();

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

  useEffect(() => {
    if (currentSessionId) syncSessionIdInLocation(currentSessionId);
    else if (newSessionPending) syncSessionIdInLocation(null);
  }, [currentSessionId, newSessionPending]);

  // 后端能力探测：拿到真实会话 id 后探测会话级端点（jobs/continuity），
  // 缺失时隐藏对应入口（开源精简后端），存在时保持完整行为。
  useEffect(() => {
    probeSessionCapabilities(currentSessionId);
  }, [currentSessionId]);

  const toggleSidebar = () => {
    if (isMobile) setMobileSidebarOpen((v) => !v);
    else setSidebarCollapsed((v) => !v);
  };

  const showConversationFiles = () => {
    sidebarViewStore.setView("files");
    if (isMobile) setMobileSidebarOpen(true);
    else setSidebarCollapsed(false);
  };

  const shellClass = [
    "v2-shell",
    isMobile && mobileSidebarOpen ? "mobile-sidebar-open" : "",
    // 2026-09-09 修复: 此前为 !panelOpen，与 CSS 语义相反——
    // app.css 中 .v2-shell.mobile-panel-open .v2-panel { transform: none }，
    // 且 RightPanel 在 open=false 时 return null；旧写法导致
    // 面板渲染时被 translateX(100%) 移出屏幕，未渲染时 class 反而存在。
    // 机械一致不变量：mobile-panel-open class 与 RightPanel DOM 挂载必须同开同关。
    isMobile && panelOpen ? "mobile-panel-open" : "",
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
        <TopBar onToggleSidebar={toggleSidebar} onShowFiles={showConversationFiles} />
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
