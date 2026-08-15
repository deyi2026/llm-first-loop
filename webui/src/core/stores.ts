// Web V2 核心：全局状态（轻量自研 store，useSyncExternalStore 驱动；无重型依赖）

import { useSyncExternalStore } from "react";
import type { SessionMeta } from "./api";

export type ThemePreference = "system" | "light" | "dark";

interface SessionState {
  sessions: SessionMeta[];
  currentSessionId: string | null;
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
const sessionStoreRaw = createStore<SessionState>({ sessions: [], currentSessionId: null });

export const sessionStore = {
  getState: sessionStoreRaw.getState,
  setSessions: (sessions: SessionMeta[]) => sessionStoreRaw.setState({ sessions }),
  setCurrentSession: (sessionId: string) => sessionStoreRaw.setState({ currentSessionId: sessionId }),
  subscribe: sessionStoreRaw.subscribe,
};

export function useSessions(): SessionMeta[] {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().sessions);
}

export function useCurrentSessionId(): string | null {
  return useSyncExternalStore(sessionStore.subscribe, () => sessionStore.getState().currentSessionId);
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
const connStoreRaw = createStore<{ ok: boolean; service: string; version: string; checked: boolean }>({
  ok: false,
  service: "",
  version: "",
  checked: false,
});

export const connStore = {
  getState: connStoreRaw.getState,
  set: (v: Partial<{ ok: boolean; service: string; version: string; checked: boolean }>) =>
    connStoreRaw.setState(v),
  subscribe: connStoreRaw.subscribe,
};

export function useConnection(): { ok: boolean; service: string; version: string; checked: boolean } {
  return useSyncExternalStore(connStore.subscribe, () => connStore.getState());
}
