function isNarrowScreen() {
  // 窄屏判定：与 CSS 断点共用同一阈值；异常降级返回 false（桌面布局）
  try {
    return window.matchMedia("(max-width: 767.98px)").matches;
  } catch (e) {
    console.error("isNarrowScreen 失败（fail-open，按桌面布局处理）", e);
    return false;
  }
}

function handleVisualViewportChange() {
  // 无 dvh 支持且 visualViewport 可用时，软键盘弹出同步 #app 高度保证输入区可达
  try {
    let supportsDvh = false;
    try { supportsDvh = CSS.supports("height", "100dvh"); } catch (e) { /* 不支持即回退 */ }
    if (supportsDvh) return; // CSS 100dvh 已处理动态视口，JS 无需兜底
    if (window.visualViewport) {
      const syncHeight = () => {
        els.app.style.height = `${window.visualViewport.height}px`;
      };
      window.visualViewport.addEventListener("resize", syncHeight);
      window.visualViewport.addEventListener("scroll", syncHeight);
    }
  } catch (e) {
    console.error("handleVisualViewportChange 失败（fail-open，CSS 100vh 回退）", e);
  }
}

function setSidebarOpen(open) {
  // 仅窄屏生效；宽屏幂等返回，防覆盖态残留
  if (!isNarrowScreen()) return;
  els.app.classList.toggle("sidebar-open", Boolean(open));
}

function initResponsive() {
  // 注册侧栏开合事件源 + 断点切换归位 + 视口兜底；异常 fail-open 不阻断既有功能
  try {
    els.sidebarToggle.addEventListener("click", () => {
      const willOpen = !els.app.classList.contains("sidebar-open");
      setSidebarOpen(willOpen);
    });
    els.sidebarScrim.addEventListener("click", () => setSidebarOpen(false));
    window.matchMedia("(max-width: 767.98px)").addEventListener("change", (evt) => {
      if (!evt.matches) setSidebarOpen(false); // 切回宽屏自动归位
    });
    handleVisualViewportChange();
  } catch (e) {
    console.error("响应式初始化失败（fail-open，保持桌面布局）", e);
  }
}

