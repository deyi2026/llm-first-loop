// Web V2：应用根（三栏壳：侧栏 | 会话主区 | 右侧面板；对齐 DSH ui-layout）

import { useCallback, useEffect, useRef, useState } from "react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { TopBar } from "./components/layout/TopBar";
import { RightPanel } from "./components/layout/RightPanel";
import { Conversation } from "./components/conversation/Conversation";
import { LearningPanel } from "./components/learning/LearningPanel";
import { ServicesPanel } from "./components/services/ServicesPanel";
import { initEventStream } from "./core/events";
import { probeSessionCapabilities } from "./core/capabilities";
import { InteropNotice } from "./components/InteropNotice";
import {
  previewTabsStore,
  rightPanelStore,
  sidebarViewStore,
  useCurrentSessionId,
  useMainView,
  useNewSessionPending,
  useRightPanel,
} from "./core/stores";
import { syncSessionIdInLocation } from "./core/sessionUrl";

// ── 右面板宽度（对齐 DSH 可调右侧栏）：拖拽把手调宽，localStorage 持久化 ──
export const PANEL_WIDTH_KEY = "lfl-panel-width-v1";
export const PANEL_WIDTH_MIN = 288;
export const PANEL_WIDTH_MAX = 720;
export const PANEL_WIDTH_DEFAULT = 400;

export function clampPanelWidth(px: number): number {
  if (!Number.isFinite(px)) return PANEL_WIDTH_DEFAULT;
  return Math.min(PANEL_WIDTH_MAX, Math.max(PANEL_WIDTH_MIN, Math.round(px)));
}

function readPanelWidth(): number {
  const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
  return clampPanelWidth(saved);
}

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
  // 面板开合归 rightPanelStore：预览入口（chips/正文链接/文件树）可全局联动开面板。
  const panel = useRightPanel();
  const panelOpen = panel.open;
  const currentSessionId = useCurrentSessionId();
  const newSessionPending = useNewSessionPending();
  const mainView = useMainView();

  useEffect(() => {
    rightPanelStore.setOpen(!isMobile); // 初始：桌面常开、移动收起（与原行为一致）
  }, []); // eslint-disable-line react-hooks/exhaustive-deps — 仅首载定初值

  // 预览 tab 布局绑定当前会话桶：切换会话时旧桶落盘、新桶恢复（对齐 DSH
  // Session 布局绑定；内容不入存储，tab 重开重取）。
  useEffect(() => {
    previewTabsStore.bindSession(currentSessionId ?? "");
  }, [currentSessionId]);

  useEffect(() => {
    initEventStream(); // SSE 命名事件 + 失联自愈看门狗（对齐 v0.5.6 加固）
    if (typeof matchMedia === "undefined") return;
    const mq = matchMedia("(max-width: 900px)");
    const onChange = () => {
      const nextMobile = mq.matches;
      setIsMobile(nextMobile);
      // 跨断点属于布局模式切换；不要把桌面常驻面板直接变成覆盖内容的移动抽屉。
      setMobileSidebarOpen(false);
      if (nextMobile) rightPanelStore.setOpen(false);
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
    if (isMobile) {
      if (!mobileSidebarOpen) rightPanelStore.setOpen(false);
      setMobileSidebarOpen((v) => !v);
    }
    else setSidebarCollapsed((v) => !v);
  };

  // 预览等外部入口也可能直接 reveal 右面板；移动端只允许一个抽屉占据前景。
  useEffect(() => {
    if (isMobile && panelOpen) setMobileSidebarOpen(false);
  }, [isMobile, panelOpen]);

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

  // 右面板宽度（桌面）：拖拽调宽 + 持久化；移动端抽屉不受影响（inline 不设）
  const [panelWidth, setPanelWidth] = useState(() =>
    typeof window === "undefined" || window.matchMedia?.("(max-width: 900px)").matches
      ? PANEL_WIDTH_DEFAULT
      : readPanelWidth()
  );
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  const onHandleDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      dragRef.current = { startX: e.clientX, startW: panelWidth };
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    },
    [panelWidth]
  );
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      // 向左拖（clientX 减小）= 增宽面板
      setPanelWidth(clampPanelWidth(d.startW + (d.startX - e.clientX)));
    };
    const onUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setPanelWidth((w) => {
        try {
          localStorage.setItem(PANEL_WIDTH_KEY, String(w));
        } catch {
          // 私有模式/配额满：宽度不持久化，不影响当次会话
        }
        return w;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  return (
    <div className={shellClass} data-testid="app-shell">
      <Sidebar collapsed={!isMobile && sidebarCollapsed} />
      {isMobile && mobileSidebarOpen && (
        <div className="v2-scrim" data-testid="sidebar-scrim" onClick={() => setMobileSidebarOpen(false)} />
      )}
      {isMobile && panelOpen && (
        <div
          className="v2-scrim"
          data-testid="panel-scrim"
          onClick={() => rightPanelStore.setOpen(false)}
        />
      )}
      <div className="v2-main">
        <TopBar onToggleSidebar={toggleSidebar} onShowFiles={showConversationFiles} />
        {mainView === "chat" ? <InteropNotice /> : null}
        {mainView === "learning" ? (
          <LearningPanel />
        ) : mainView === "services" ? (
          <ServicesPanel />
        ) : (
          <Conversation />
        )}
      </div>
      <button
        type="button"
        className="v2-icon-btn"
        style={{ alignSelf: "center" }}
        onClick={() => {
          const nextOpen = !panelOpen;
          if (isMobile && nextOpen) setMobileSidebarOpen(false);
          rightPanelStore.setOpen(nextOpen);
        }}
        title="右侧面板"
        aria-label="右侧面板"
      >
        {panelOpen ? "▸" : "◂"}
      </button>
      {panelOpen && !isMobile ? (
        <div
          className="v2-panel-resize-handle"
          data-testid="panel-resize-handle"
          role="separator"
          aria-orientation="vertical"
          title="拖拽调整面板宽度"
          onPointerDown={onHandleDown}
        />
      ) : null}
      <RightPanel open={panelOpen} width={panelOpen && !isMobile ? panelWidth : undefined} />
    </div>
  );
}
