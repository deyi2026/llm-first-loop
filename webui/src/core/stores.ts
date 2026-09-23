// Web V2 核心：全局状态（轻量自研 store，useSyncExternalStore 驱动；无重型依赖）

import { useSyncExternalStore } from "react";
import type { SessionMeta } from "./api";

export type ThemePreference = "system" | "light" | "dark";
export type ThinkingMode = "auto" | "off" | "on";
export type SidebarView = "sessions" | "files" | "evo" | "esc" | "archived";
export type MainView = "chat" | "learning" | "services";

interface SessionState {
  sessions: SessionMeta[];
  currentSessionId: string | null;
  /** 会话级模型覆盖（chat 请求携带；M47 语义） */
  model: string | null;
  /** 用户刚刚显式选择了模型；仅下一条 human turn 可把该选择写回会话 authority。 */
  modelChangePending: boolean;
  /** 会话级推理等级覆盖（对齐 DSH 模型+推理等级选择；chat 请求携带） */
  reasoningEffort: string | null;
  /** 思维链开关（reasoning_mode：auto/off/on；本地 chat_template 模型选 on 才显式发 enable_thinking） */
  thinkingMode: ThinkingMode;
  /** /new 语义标记（2026-08-18 修复跳回旧会话）: handleNew 后发送需 new_session=true */
  newSessionPending: boolean;
}

const listeners = new Set<() => void>();

function createStore<T extends object>(initial: T) {
  let state: T = initial;
  return {
    getState: () => state,
    setState: (partial: Partial<T>) => {
      state = { ...state, ...partial };
      listeners.forEach((l) => l());
    },
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

// ── 会话 store ──
// 2026-08-18 模型选择持久化（用户反馈'刷新跳回 deepseek 混乱'）:
// localStorage 保存选择——刷新恢复所选（对齐主题持久化模式）
const MODEL_KEY = "lfl.selected.model";
// 2026-08-20（用户反馈）: 刷新时模型等级也要保持——effort 与 model 同模式持久化
const EFFORT_KEY = "lfl.selected.effort";
// 2026-09-04（用户反馈）: V2 缺思维链开关（本地模型需显式 on）——thinkingMode 同模式持久化
const THINKING_KEY = "lfl.selected.thinking";

function readSavedModel(): string | null {
  try {
    if (typeof window === "undefined") return null;
    const v = localStorage.getItem(MODEL_KEY);
    return v || null;
  } catch {
    return null;
  }
}

function readSavedEffort(): string | null {
  try {
    if (typeof window === "undefined") return null;
    const v = localStorage.getItem(EFFORT_KEY);
    return v || null;
  } catch {
    return null;
  }
}

function readSavedThinking(): ThinkingMode {
  try {
    if (typeof window === "undefined") return "auto";
    const v = localStorage.getItem(THINKING_KEY);
    return v === "on" || v === "off" ? v : "auto";
  } catch {
    return "auto";
  }
}

const sessionStoreRaw = createStore<SessionState>({
  sessions: [],
  currentSessionId: null,
  model: readSavedModel(),
  modelChangePending: false,
  reasoningEffort: readSavedEffort(),
  thinkingMode: readSavedThinking(),
  newSessionPending: false,
});

function persistModel(model: string | null): void {
  try {
    if (model) localStorage.setItem(MODEL_KEY, model);
    else localStorage.removeItem(MODEL_KEY);
  } catch {
    /* fail-open */
  }
}

export const sessionStore = {
  getState: sessionStoreRaw.getState,
  setSessions: (sessions: SessionMeta[]) => {
    const state = sessionStoreRaw.getState();
    const current = state.currentSessionId
      ? sessions.find((item) => item.session_id === state.currentSessionId)
      : undefined;
    if (current && !state.modelChangePending) {
      persistModel(current.model ?? null);
      sessionStoreRaw.setState({ sessions, model: current.model ?? null });
      return;
    }
    sessionStoreRaw.setState({ sessions });
  },
  setCurrentSession: (sessionId: string) => {
    const state = sessionStoreRaw.getState();
    const target = sessionId
      ? state.sessions.find((item) => item.session_id === sessionId)
      : undefined;
    if (target) {
      persistModel(target.model ?? null);
      sessionStoreRaw.setState({
        currentSessionId: sessionId,
        model: target.model ?? null,
        modelChangePending: false,
      });
      return;
    }
    sessionStoreRaw.setState({ currentSessionId: sessionId, modelChangePending: false });
  },
  setModel: (model: string | null) => {
    persistModel(model);
    sessionStoreRaw.setState({ model });
  },
  selectModel: (model: string | null) => {
    persistModel(model);
    sessionStoreRaw.setState({ model, modelChangePending: true });
  },
  setModelChangePending: (value: boolean) => sessionStoreRaw.setState({ modelChangePending: value }),
  setReasoningEffort: (effort: string | null) => {
    try {
      if (effort) localStorage.setItem(EFFORT_KEY, effort);
      else localStorage.removeItem(EFFORT_KEY);
    } catch {
      /* fail-open */
    }
    sessionStoreRaw.setState({ reasoningEffort: effort });
  },
  setThinkingMode: (mode: ThinkingMode) => {
    try {
      if (mode === "auto") localStorage.removeItem(THINKING_KEY);
      else localStorage.setItem(THINKING_KEY, mode);
    } catch {
      /* fail-open */
    }
    sessionStoreRaw.setState({ thinkingMode: mode });
  },
  setNewSessionPending: (v: boolean) => sessionStoreRaw.setState({ newSessionPending: v }),
  subscribe: sessionStoreRaw.subscribe,
};

export function useSessions(): SessionMeta[] {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().sessions);
}

export function useCurrentSessionId(): string | null {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().currentSessionId);
}

export function useModel(): string | null {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().model);
}

export function useThinkingMode(): ThinkingMode {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().thinkingMode);
}

export function useReasoningEffort(): string | null {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().reasoningEffort);
}

export function useNewSessionPending(): boolean {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().newSessionPending);
}

// ── 侧栏视图 store：允许顶栏“查看聊天中的文件”等真实导航动作打开对应视图 ──
const sidebarViewStoreRaw = createStore<{ view: SidebarView }>({ view: "sessions" });

export const sidebarViewStore = {
  getState: sidebarViewStoreRaw.getState,
  setView: (view: SidebarView) => sidebarViewStoreRaw.setState({ view }),
  subscribe: sidebarViewStoreRaw.subscribe,
};

export function useSidebarView(): SidebarView {
  return useSyncExternalStore(sidebarViewStore.subscribe, () => sidebarViewStore.getState().view);
}

// ── 主区视图：Learning Plane 是固定系统通道，不伪装成普通聊天 Session。 ──
const mainViewStoreRaw = createStore<{ view: MainView }>({ view: "chat" });

export const mainViewStore = {
  getState: mainViewStoreRaw.getState,
  setView: (view: MainView) => mainViewStoreRaw.setState({ view }),
  subscribe: mainViewStoreRaw.subscribe,
};

export function useMainView(): MainView {
  return useSyncExternalStore(mainViewStore.subscribe, () => mainViewStore.getState().view);
}

// ── 右侧面板 store：面板开合 + 活动页签（预览 tab 打开时全局联动 App 壳） ──
export type RightPanelTab = "settings" | "jobs" | "preview";

const rightPanelStoreRaw = createStore<{ open: boolean; tab: RightPanelTab }>({
  open: false,
  tab: "settings",
});

export const rightPanelStore = {
  getState: rightPanelStoreRaw.getState,
  subscribe: rightPanelStoreRaw.subscribe,
  setOpen: (open: boolean) => rightPanelStoreRaw.setState({ open }),
  setTab: (tab: RightPanelTab) => rightPanelStoreRaw.setState({ tab }),
  /** 打开面板并切到指定页签（预览入口共用） */
  reveal: (tab: RightPanelTab) => rightPanelStoreRaw.setState({ open: true, tab }),
};

export function useRightPanel(): { open: boolean; tab: RightPanelTab } {
  return useSyncExternalStore(rightPanelStore.subscribe, rightPanelStore.getState);
}

// ── 预览 tab store（对齐 DSH 右侧栏 tab 语义）：
// 完整路径 = tab 身份（同名不同目录是两个 tab）；重复打开聚焦既有 tab 并更新
// 行号目标（新 revision）；关闭即卸载（Blob/分页状态随组件释放）。
export interface PreviewTabState {
  path: string;
  /** 1-based 行号锚点（null = 无跳转请求）；对 markdown 渲染态挂起直至切纯文本 */
  line: number | null;
  /** 行号请求修订号：每次 open() 递增——同值行号再请求也重新触发跳转 */
  seq: number;
}

const previewTabsStoreRaw = createStore<{ tabs: PreviewTabState[]; active: string }>({
  tabs: [],
  active: "",
});

let previewTabSeq = 0;

export const previewTabsStore = {
  getState: previewTabsStoreRaw.getState,
  subscribe: previewTabsStoreRaw.subscribe,
  /** 打开（或聚焦）一个预览 tab；同 path 再开 = 更新行号目标（新 revision）并置为活动 tab */
  open(path: string, line: number | null = null): void {
    previewTabSeq += 1;
    const { tabs } = previewTabsStoreRaw.getState();
    const existing = tabs.find((t) => t.path === path);
    if (existing) {
      previewTabsStoreRaw.setState({
        tabs: tabs.map((t) => (t.path === path ? { ...t, line, seq: previewTabSeq } : t)),
        active: path,
      });
    } else {
      previewTabsStoreRaw.setState({ tabs: [...tabs, { path, line, seq: previewTabSeq }], active: path });
    }
    rightPanelStore.reveal("preview");
  },
  close(path: string): void {
    const { tabs, active } = previewTabsStoreRaw.getState();
    const idx = tabs.findIndex((t) => t.path === path);
    if (idx < 0) return;
    const next = tabs.filter((t) => t.path !== path);
    let nextActive = active;
    if (active === path) {
      nextActive = next[Math.min(idx, next.length - 1)]?.path ?? "";
    }
    previewTabsStoreRaw.setState({ tabs: next, active: nextActive });
  },
  setActive(path: string): void {
    previewTabsStoreRaw.setState({ active: path });
  },
  closeAll(): void {
    previewTabsStoreRaw.setState({ tabs: [], active: "" });
  },
};

export function usePreviewTabs(): { tabs: PreviewTabState[]; active: string } {
  return useSyncExternalStore(previewTabsStore.subscribe, previewTabsStore.getState);
}

// ── 主题 store（偏好持久化 localStorage + 跟随系统；body[data-ds-dark-theme] 属性生效） ──
const THEME_KEY = "dsw-theme-preference";

function readThemePreference(): ThemePreference {
  const saved = localStorage.getItem(THEME_KEY);
  return saved === "light" || saved === "dark" ? saved : "system";
}

function systemDark(): boolean {
  return (
    typeof matchMedia !== "undefined" && matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function applyTheme(pref: ThemePreference): void {
  const dark = pref === "dark" || (pref === "system" && systemDark());
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  document.body.toggleAttribute("data-ds-dark-theme", dark);
}

const themeStoreRaw = createStore<{ preference: ThemePreference; dark: boolean }>({
  preference: readThemePreference(),
  dark: readThemePreference() === "dark" || systemDark(),
});

export const themeStore = {
  getState: themeStoreRaw.getState,
  setPreference: (pref: ThemePreference) => {
    localStorage.setItem(THEME_KEY, pref);
    applyTheme(pref);
    themeStoreRaw.setState({ preference: pref, dark: pref === "dark" || (pref === "system" && systemDark()) });
  },
  subscribe: themeStoreRaw.subscribe,
};

// 跟随系统变化（仅在 system 偏好下自动切换）
if (typeof matchMedia !== "undefined") {
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    const pref = themeStore.getState().preference;
    if (pref === "system") {
      applyTheme("system");
      themeStoreRaw.setState({ dark: systemDark() });
    }
  });
}

applyTheme(themeStore.getState().preference);

export function useTheme(): { preference: ThemePreference; dark: boolean } {
  return useSyncExternalStore(themeStore.subscribe, () => themeStore.getState());
}

// ── 连接状态 store（/health 轮询） ──
export interface ConnectionState {
  ok: boolean;
  service: string;
  version: string;
  build: string;
  checked: boolean;
}

const connStoreRaw = createStore<ConnectionState>({
  ok: false,
  service: "",
  version: "",
  build: "",
  checked: false,
});

export const connStore = {
  getState: connStoreRaw.getState,
  set: (v: Partial<ConnectionState>) => connStoreRaw.setState(v),
  subscribe: connStoreRaw.subscribe,
};

export function useConnection(): ConnectionState {
  return useSyncExternalStore(connStore.subscribe, () => connStore.getState());
}
