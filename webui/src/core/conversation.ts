// Web V2：对话 store（消息流 / 流式状态 / 历史分页 / 发送·停止·重试）

import { useSyncExternalStore } from "react";
import type { ChatDoneData, ChatMessage } from "./types";
import { streamChatRequest, toChatMessage, buildAssistantNote, fetchHistory, fetchStreamStatus } from "./chat";
import { sessionStore } from "./stores";

const HISTORY_PAGE_SIZE = 100;

interface ConversationState {
  messages: ChatMessage[];
  hasMoreHistory: boolean;
  loadedHistoryCount: number;
  streaming: boolean;
  /** 后台 run 进行中（EVO 后台 run：刷新/切换后可见性） */
  backgroundRunning: boolean;
  /** 当前进行中的助手消息索引（-1=无） */
  streamingIndex: number;
  lastError: string | null;
  /** 本次流式开始时刻（占位符等待时长展示；null=未在流式） */
  streamStartedAt: number | null;
}

const listeners = new Set<() => void>();
let state: ConversationState = {
  messages: [],
  hasMoreHistory: false,
  loadedHistoryCount: 0,
  streaming: false,
  backgroundRunning: false,
  streamingIndex: -1,
  lastError: null,
  streamStartedAt: null,
};

let abortCtrl: AbortController | null = null;
let abortSessionId: string | null = null;
let resumeAbort: AbortController | null = null;
let resumeSessionId: string | null = null;
let bgPollTimer: number | undefined;

// ── 空闲增量轮询（飞书桥等外部通道写入后 Web 及时刷新，无需手动切会话）──
const IDLE_POLL_INTERVAL_MS = 20_000;
let idlePollTimer: number | undefined;
let idlePollSession: string | null = null;
/** 上次探针的服务端最新消息指纹（与服务端自比对，消除本地 toChatMessage 映射差异） */
let idleProbeFp: string | null = null;

function emit(): void {
  listeners.forEach((l) => l());
}

export const conversationStore = {
  getState: () => state,
  subscribe: (l: () => void) => {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  setState: (partial: Partial<ConversationState>) => {
    state = { ...state, ...partial };
    emit();
  },
};

export function useConversation(): ConversationState {
  return useSyncExternalStore(conversationStore.subscribe, () => conversationStore.getState());
}

function abortForegroundSubscription(): void {
  const ctrl = abortCtrl;
  if (!ctrl) return;
  ctrl.abort();
  if (abortCtrl === ctrl) {
    abortCtrl = null;
    abortSessionId = null;
  }
}

function abortResumeSubscription(): void {
  const ctrl = resumeAbort;
  if (!ctrl) return;
  ctrl.abort();
  if (resumeAbort === ctrl) {
    resumeAbort = null;
    resumeSessionId = null;
  }
}

/** 会话切换只 detach 旧 SSE，不调用 cancel：后台 run 继续，切回可 resume。 */
function detachSubscriptionsForSession(nextSessionId: string | null): void {
  if (abortCtrl && abortSessionId !== nextSessionId) abortForegroundSubscription();
  if (resumeAbort && resumeSessionId !== nextSessionId) abortResumeSubscription();
}

let observedSessionId = sessionStore.getState().currentSessionId;
sessionStore.subscribe(() => {
  const nextSessionId = sessionStore.getState().currentSessionId;
  if (nextSessionId === observedSessionId) return;
  observedSessionId = nextSessionId;
  detachSubscriptionsForSession(nextSessionId);
  if (bgPollTimer !== undefined) {
    window.clearInterval(bgPollTimer);
    bgPollTimer = undefined;
  }
  // 切换会话：停上一会话的空闲轮询（新会话由 loadHistory 重新 ensure）
  stopIdlePoll();
});

/** 服务端最新消息指纹（limit=1 探针，成本低） */
function fingerprintLatest(m: ChatMessage | undefined): string | null {
  if (!m) return null;
  return JSON.stringify([m.role, m.content, m.note ?? null]);
}

/** 空闲轮询一跳：非空闲/无会话直接退出；指纹变化 → 重载整窗 */
async function idlePollTick(sessionId: string): Promise<void> {
  const st = conversationStore.getState();
  if (st.streaming || st.backgroundRunning || st.loadedHistoryCount === 0) return;
  const resp = await fetchHistory(sessionId, 1, 0);
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  const fp = fingerprintLatest(resp.messages[0] as ChatMessage | undefined);
  if (fp === null) return; // 会话被清空等异常形态：不触发重载（下次探针再判）
  if (idleProbeFp === null) {
    idleProbeFp = fp; // 基线跳
    return;
  }
  if (fp !== idleProbeFp) void loadHistory(sessionId); // 有新写入 → 全量重载（终态可靠）
}

function stopIdlePoll(): void {
  if (idlePollTimer !== undefined) {
    window.clearInterval(idlePollTimer);
    idlePollTimer = undefined;
  }
}

/** 启动空闲增量轮询（幂等；仅当前会话；流式/后台 run 时自动退避不请求） */
export function ensureIdlePoll(sessionId: string): void {
  if (idlePollTimer !== undefined && idlePollSession === sessionId) return;
  stopIdlePoll();
  idlePollSession = sessionId;
  idleProbeFp = null;
  idlePollTimer = window.setInterval(() => void idlePollTick(sessionId), IDLE_POLL_INTERVAL_MS);
}

// ── 外部同步信号刷新（SSE sessions_updated / 看门狗 / 聚焦共用入口）──
let syncRefreshBusy = false;

/** 空闲态重载当前会话消息区：飞书桥等外部写入的推送级可见路径（EVO-20260827-23d33f32）。
 *  async 闩防抖（信号风暴只保留一个在途重载）；run 进行中让路（流式/后台轮询已接管）。 */
export async function refreshCurrentSessionMessages(): Promise<void> {
  if (syncRefreshBusy) return;
  const sessionId = sessionStore.getState().currentSessionId;
  if (!sessionId) return; // 空 current 是"新会话待建"语义（见 events.ts newSessionPending 注释）
  const st = conversationStore.getState();
  if (st.streaming || st.backgroundRunning || st.loadedHistoryCount === 0) return;
  syncRefreshBusy = true;
  try {
    await loadHistory(sessionId);
  } finally {
    syncRefreshBusy = false;
  }
}

export async function loadHistory(sessionId: string): Promise<void> {
  // setCurrentSession 通常先发生；owner-aware detach 不依赖 store 的“当前值”猜旧流归属。
  detachSubscriptionsForSession(sessionId);
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, 0);
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  const messages = resp.messages.map(toChatMessage);
  conversationStore.setState({
    messages,
    hasMoreHistory: resp.has_more,
    loadedHistoryCount: messages.length,
    streaming: false,
    streamingIndex: -1,
    lastError: null,
    streamStartedAt: null,
    backgroundRunning: false,
  });
  // EVO 后台 run：加载后查后台生成状态——running 则轮询直到完成（刷新/切换后可见进行中任务）
  // 空闲增量轮询：飞书桥等外部写入 → Web 20s 内自动刷新；基线指纹直接取自本次加载，省一次探针
  ensureIdlePoll(sessionId);
  idleProbeFp = fingerprintLatest(messages[messages.length - 1]);
  void checkBackgroundRun(sessionId);
}

/** 后台 run 检查：running → resume 订阅（重放已生成内容+实时流式——对齐 DSH 刷新可见中间状态）；
 *  订阅失败/非 running → 回退轮询直到完成重载。 */
export async function checkBackgroundRun(sessionId: string): Promise<void> {
  if (bgPollTimer !== undefined) window.clearInterval(bgPollTimer);
  bgPollTimer = undefined;
  const status = await fetchStreamStatus(sessionId);
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  if (!status || !status.running) return;
  conversationStore.setState({ backgroundRunning: true });
  const resumed = await resumeBackgroundStream(sessionId);
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  if (resumed) return; // 订阅成功——流式接管（done 后自动重载）
  // 回退：轮询直到完成（订阅失败/不支持——run 已结束或网络异常）
  bgPollTimer = window.setInterval(async () => {
    if (sessionStore.getState().currentSessionId !== sessionId) {
      if (bgPollTimer !== undefined) window.clearInterval(bgPollTimer);
      bgPollTimer = undefined;
      return;
    }
    const s = await fetchStreamStatus(sessionId);
    if (sessionStore.getState().currentSessionId !== sessionId) return;
    if (!s || !s.running) {
      if (bgPollTimer !== undefined) window.clearInterval(bgPollTimer);
      bgPollTimer = undefined;
      conversationStore.setState({ backgroundRunning: false });
      void loadHistory(sessionId); // 后台完成 → 重载显示完整结果
    }
  }, 2000);
}

/** 对齐 DSH（2026-08-18）: 刷新/切回时后台 run 进行中 → resume 订阅已有 run——
 *  后端重放已生成 delta（EventBus 有界缓冲 c3c6c6d）+ 实时流式；done 后重载完整结果。 */
async function resumeBackgroundStream(sessionId: string): Promise<boolean> {
  const controller = new AbortController();
  resumeAbort = controller;
  resumeSessionId = sessionId;
  try {
    // 流式占位（重放内容实时渲染——同正常发送路径）
    const cur = conversationStore.getState();
    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      reasoningContent: "",
      toolCalls: null,
      note: null,
      streaming: true,
      streamStartedAt: Date.now(),
      tokens_in: 0,
      tokens_out: 0,
      tokens_cache_hit: 0,
    };
    conversationStore.setState({
      messages: [...cur.messages, placeholder],
      streaming: true,
      streamingIndex: cur.messages.length,
      lastError: null,
    });
    const acc = { answer: "", reasoning: "" };
    const sid = sessionId;
    const outcome = await streamChatRequest(
      { message: "resume", session_id: sid, resume: true },
      {
        onAnswerDelta: (d) => {
          // 会话守卫：当前会话已切换 → 停止渲染（防串写）
          if (sessionStore.getState().currentSessionId !== sid) return;
          acc.answer += d;
          patchStreaming({ content: acc.answer });
        },
        onReasoningDelta: (d) => {
          if (sessionStore.getState().currentSessionId !== sid) return;
          acc.reasoning += d;
          patchStreaming({ reasoningContent: acc.reasoning });
        },
        onToolRound: () => undefined,
      },
      controller.signal
    );
    if (resumeAbort === controller) {
      resumeAbort = null;
      resumeSessionId = null;
    }
    if (sessionStore.getState().currentSessionId !== sessionId) return true;
    if (outcome.ok && outcome.data) {
      conversationStore.setState({ streaming: false, backgroundRunning: false });
      void loadHistory(sessionId); // 终态 → 重载完整结果（含工具调用）
      return true;
    }
    // 失败（run 已结束/网络）→ 移除占位、回退轮询
    conversationStore.setState({
      messages: conversationStore.getState().messages.slice(0, -1),
      streaming: false,
    });
    return false;
  } catch {
    if (resumeAbort === controller) {
      resumeAbort = null;
      resumeSessionId = null;
    }
    // 会话已切换时这是主动 detach，不得为旧会话启动回退轮询。
    if (sessionStore.getState().currentSessionId !== sessionId) return true;
    return false;
  }
}

export async function loadEarlierHistory(sessionId: string): Promise<void> {
  const cur = conversationStore.getState();
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, cur.loadedHistoryCount);
  const earlier = resp.messages.map(toChatMessage);
  conversationStore.setState({
    messages: [...earlier, ...cur.messages],
    hasMoreHistory: resp.has_more,
    loadedHistoryCount: cur.loadedHistoryCount + earlier.length,
  });
}

export function stopStreaming(): void {
  // Stop 与会话切换不同：先捕获“实际流 owner”，再断订阅并请求后端真取消。
  let sid: string | null = null;
  if (abortCtrl) sid = abortSessionId;
  else if (resumeAbort) sid = resumeSessionId;
  else sid = sessionStore.getState().currentSessionId;
  abortForegroundSubscription();
  abortResumeSubscription();
  // fail-open: 取消失败不影响前端状态（后端 run 终会自然结束落盘）。
  if (sid) {
    void fetch("/api/v1/chat/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sid }),
    }).catch(() => undefined);
  }
  // EVO-20260823 停止按钮修复: SSE abort 只停订阅（后台 run 线程继续执行），
  // 需调后端 cancel API 请求真正取消（runner.cancel → 引擎主循环检查点终止）。
  // （2026-09-04 修复重复声明: 原第二段 const sid 重复取消逻辑与上方重复，删除）
}

/** 发送消息（含附件前缀注入；流式渲染思考/工具轮/正文；done 终态覆盖；错误可重试） */
export interface SendAttachment {
  filename: string;
  result_text: string;
  status?: "ok" | "pending" | "degraded" | "error";
  detail?: string;
}

export async function sendMessage(text: string, attachments: SendAttachment[]): Promise<void> {
  const cur = conversationStore.getState();
  // 空串归一为 null：新工作区/新会话无会话时后端按"新建会话"处理
  // （不可在此 return，否则新工作区发消息被静默拦截）
  const sessionId = sessionStore.getState().currentSessionId || null;
  // 本地发送即将写入/产生新消息：停空闲轮询防竞态（基线由完成后的重载路径重建）
  stopIdlePoll();
  // 只有已经成功识别的附件内容才进入模型输入。
  // pending/degraded/error 仅作为 UI/上传事实展示，不由程序改写成 user prose。
  const okPrefix = attachments
    .filter((a) => a.status === "ok")
    .map((a) => `[附件 ${a.filename}] ${a.result_text}`)
    .join("\n\n");
  const attachmentPrefix = okPrefix;
  const effectiveText = attachmentPrefix ? `${attachmentPrefix}\n\n${text}` : text;

  const userMsg: ChatMessage = { role: "user", content: text };
  const placeholder: ChatMessage = {
    role: "assistant",
    content: "",
    reasoningContent: "",
    toolCalls: null,
    note: null,
    streaming: true,
    streamStartedAt: Date.now(),
    tokens_in: 0,
    tokens_out: 0,
    tokens_cache_hit: 0,
  };
  conversationStore.setState({
    messages: [...cur.messages, userMsg, placeholder],
    streaming: true,
    streamingIndex: cur.messages.length + 1,
    lastError: null,
    streamStartedAt: Date.now(),
  });

  // 2026-08-18 修复跳回旧会话: handleNew 后发送需 new_session=true（消费标记）
  const newSessionPending = sessionStore.getState().newSessionPending;
  if (newSessionPending) sessionStore.setNewSessionPending(false);
  const body = {
    message: effectiveText,
    session_id: sessionId,
    model: sessionStore.getState().model,
    reasoning_effort: sessionStore.getState().reasoningEffort,
    reasoning_mode: sessionStore.getState().thinkingMode,
    new_session: newSessionPending || undefined,
  };
  const controller = new AbortController();
  abortCtrl = controller;
  abortSessionId = sessionId;
  const acc = { answer: "", reasoning: "", toolRounds: 0 };

  const outcome = await streamChatRequest(
    body,
    {
      onAnswerDelta: (d) => {
        // 会话守卫（2026-08-23 多会话串扰修复）: 当前会话已切换 → 停止渲染（防 A 串写 B 视图）
        if (sessionStore.getState().currentSessionId !== sessionId) return;
        acc.answer += d;
        patchStreaming({ content: acc.answer });
      },
      onReasoningDelta: (d) => {
        if (sessionStore.getState().currentSessionId !== sessionId) return;
        acc.reasoning += d;
        patchStreaming({ reasoningContent: acc.reasoning });
      },
      onToolRound: () => {
        if (sessionStore.getState().currentSessionId !== sessionId) return;
        acc.toolRounds += 1;
        patchStreaming({ note: `工具调用进行中（${acc.toolRounds} 轮）…` });
      },
    },
    controller.signal
  );
  if (abortCtrl === controller) {
    abortCtrl = null;
    abortSessionId = null;
  }

  // 终态守卫: 会话已切换 → 不写回（防 A 完成时把结果写进 B 视图）
  if (sessionStore.getState().currentSessionId !== sessionId) {
    return;
  }

  // 终态守卫: 会话已切换 → 不写回（防 A 完成时把结果写进 B 视图）
  if (sessionStore.getState().currentSessionId !== sessionId) {
    return;
  }

  const st = conversationStore.getState();
  const finalize = (msg: ChatMessage) => {
    conversationStore.setState({
      messages: [...st.messages.slice(0, st.streamingIndex), msg, ...st.messages.slice(st.streamingIndex + 1)],
      streaming: false,
      streamingIndex: -1,
      streamStartedAt: null,
    });
  };

  if (outcome.ok && outcome.data) {
    const data = outcome.data as ChatDoneData;
    if (data.session_id) sessionStore.setCurrentSession(data.session_id);
    const finalText = (data.final_answer ?? "").trim();
    if (finalText) {
      finalize({
        role: "assistant",
        content: data.final_answer ?? "",
        reasoningContent: data.reasoning_content ?? (acc.reasoning || null),
        toolCalls: data.tool_calls ?? null,
        note: buildAssistantNote(data),
        streaming: false,
        // M51/M52: 模型 + token 消耗结构化填充（页脚渲染，与历史恢复同源）
        model_used: data.model_used ?? "",
        tokens_in: data.tokens_in ?? 0,
        tokens_out: data.tokens_out ?? 0,
        tokens_cache_hit: data.tokens_cache_hit ?? 0,
      });
    } else if (Array.isArray(data.tool_calls) && data.tool_calls.length > 0) {
      finalize({
        role: "assistant",
        content: "",
        reasoningContent: data.reasoning_content ?? (acc.reasoning || null),
        toolCalls: data.tool_calls,
        note: buildAssistantNote(data) ?? "（无文字回答）",
        streaming: false,
        model_used: data.model_used ?? "",
        tokens_in: data.tokens_in ?? 0,
        tokens_out: data.tokens_out ?? 0,
        tokens_cache_hit: data.tokens_cache_hit ?? 0,
      });
    } else {
      finalize({
        role: "assistant",
        content: acc.answer || "（无文字回答）",
        reasoningContent: data.reasoning_content ?? (acc.reasoning || null),
        note: buildAssistantNote(data),
        streaming: false,
        model_used: data.model_used ?? "",
        tokens_in: data.tokens_in ?? 0,
        tokens_out: data.tokens_out ?? 0,
        tokens_cache_hit: data.tokens_cache_hit ?? 0,
      });
    }
  } else {
    const detail = outcome.error?.detail ?? "服务内部错误。";
    const note = outcome.errorType === "network" ? detail : `[程序异常] ${detail}`;
    finalize({
      role: "assistant",
      content: acc.answer || "",
      reasoningContent: acc.reasoning || null,
      note,
      streaming: false,
    });
    conversationStore.setState({ lastError: note });
  }
}

function patchStreaming(partial: Partial<ChatMessage>): void {
  const st = conversationStore.getState();
  if (st.streamingIndex < 0) return;
  const idx = st.streamingIndex;
  const messages = st.messages.map((m, i) => (i === idx ? { ...m, ...partial } : m));
  conversationStore.setState({ messages });
}
