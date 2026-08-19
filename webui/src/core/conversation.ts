// Web V2：对话 store（消息流 / 流式状态 / 历史分页 / 发送·停止·重试）
//
// 并发会话纪律（2026-08-19 修复"两个会话同时进行时内容串显/交叉污染"）：
// store 是全局单例，messages 只能归属一个会话。所有异步写入都必须经过会话守卫：
// - state.sessionId = 当前 messages 归属的会话（权威"视图归属"标记）
// - loadHistory 带序号 + 当前会话检查：快速切换 A→B→A 时乱序返回不得覆盖新视图
// - sendMessage/resume 的流式增量与终态写入：归属会话已切走 → 直接丢弃
//   （内容不丢：后端 run 持续执行并落盘，切回时 checkBackgroundRun 重放/重载恢复）
// - 切换会话时立即清空视图进入加载态：旧会话的流式内容不再残留显示在新会话下

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
  /** 当前 messages 归属的会话 id（null=新建会话未落库）；流式/终态写入的会话守卫 */
  sessionId: string | null;
  /** 历史加载中（切换会话后到历史到达前的加载态） */
  loading: boolean;
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
  sessionId: null,
  loading: false,
};

let abortCtrl: AbortController | null = null;

/** 会话加载序号：每次 loadHistory 递增；仅最新一次允许落盘（防 A→B→A 快速切换乱序覆盖） */
let loadSeq = 0;
/** 本地消息写入序号：加载期间发生本地追加（发送/resume 占位）→ 加载结果早于新消息，视为过期丢弃 */
let localWriteSeq = 0;

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

export async function loadHistory(sessionId: string): Promise<void> {
  const seq = ++loadSeq;
  const writeMark = localWriteSeq;
  // 切换会话：立即中止当前流式/恢复订阅，防旧会话内容继续渲染进新视图
  if (conversationStore.getState().streaming) stopStreaming();
  if (resumeAbort) {
    resumeAbort.abort();
    resumeAbort = null;
  }
  const st = conversationStore.getState();
  if (st.sessionId !== sessionId) {
    // 目标会话 ≠ 当前展示会话：立即清空视图进入加载态——
    // 否则旧会话内容（含正在流式的内容）会残留显示在新会话标题下，造成"串会话"误解
    conversationStore.setState({
      messages: [],
      hasMoreHistory: false,
      loadedHistoryCount: 0,
      streaming: false,
      streamingIndex: -1,
      lastError: null,
      streamStartedAt: null,
      backgroundRunning: false,
      sessionId,
      loading: true,
    });
  } else {
    conversationStore.setState({ loading: true });
  }
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, 0);
  // 会话守卫：期间用户已切走/更新加载 → 丢弃本次结果（防旧会话历史覆盖当前视图）
  if (seq !== loadSeq) return;
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  const live = conversationStore.getState();
  if (localWriteSeq !== writeMark) {
    // 加载期间本地已追加本会话新消息（发送/resume 占位）：fetch 早于新消息——
    // 历史拼接到本地消息之前（新消息/流式占位保留不被覆盖），streamingIndex 随前缀平移
    if (live.sessionId === sessionId && live.messages.length > 0) {
      const history = resp.messages.map(toChatMessage);
      const shift = history.length;
      conversationStore.setState({
        messages: [...history, ...live.messages],
        hasMoreHistory: resp.has_more,
        loadedHistoryCount: shift,
        sessionId,
        loading: false,
        streamingIndex: live.streaming ? Math.max(-1, live.streamingIndex + shift) : -1,
      });
    }
    return;
  }
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
    sessionId,
    loading: false,
  });
  // EVO 后台 run：加载后查后台生成状态——running 则轮询直到完成（刷新/切换后可见进行中任务）
  void checkBackgroundRun(sessionId);
}

let bgPollTimer: number | undefined;
// 对齐 DSH（2026-08-18 修复串行）: resume 订阅的 abort 控制器——切换会话时中止，
// 防 A 会话的 resume 流式串写进 B 会话视图
let resumeAbort: AbortController | null = null;

/** 后台 run 检查：running → resume 订阅（重放已生成内容+实时流式——对齐 DSH 刷新可见中间状态）；
 *  订阅失败/非 running → 回退轮询直到完成重载。 */
export async function checkBackgroundRun(sessionId: string): Promise<void> {
  window.clearInterval(bgPollTimer);
  const status = await fetchStreamStatus(sessionId);
  // 会话守卫：状态查询期间用户已切走 → 不操作当前视图（切回时由新 loadHistory 重新检查）
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  if (!status || !status.running) return;
  // 防重复订阅：该会话已有前台流在渲染（同会话刷新场景）→ 不重复开订阅（防双流双写）
  const st = conversationStore.getState();
  if (st.sessionId === sessionId && st.streaming) return;
  conversationStore.setState({ backgroundRunning: true });
  const resumed = await resumeBackgroundStream(sessionId);
  if (resumed) return; // 订阅成功——流式接管（done 后自动重载）
  // 回退：轮询直到完成（订阅失败/不支持——run 已结束或网络异常）
  bgPollTimer = window.setInterval(async () => {
    const s = await fetchStreamStatus(sessionId);
    if (sessionStore.getState().currentSessionId !== sessionId) {
      window.clearInterval(bgPollTimer);
      return;
    }
    if (!s || !s.running) {
      window.clearInterval(bgPollTimer);
      conversationStore.setState({ backgroundRunning: false });
      void loadHistory(sessionId); // 后台完成 → 重载显示完整结果
    }
  }, 2000);
}

/** 对齐 DSH（2026-08-18）: 刷新/切回时后台 run 进行中 → resume 订阅已有 run——
 *  后端重放已生成 delta（EventBus 有界缓冲 c3c6c6d）+ 实时流式；done 后重载完整结果。 */
async function resumeBackgroundStream(sessionId: string): Promise<boolean> {
  // 会话守卫：发起后用户已切走 → 不再订阅/写入（切回时重新检查）
  if (sessionStore.getState().currentSessionId !== sessionId) return false;
  try {
    const pre = conversationStore.getState();
    // 归属守卫：store 必须仍展示该会话（防占位符注入他会话视图）
    if (pre.sessionId !== sessionId) return false;
    // 流式互斥：该会话已有流在渲染 → 不重复开订阅（防双流双写/双占位）
    if (pre.streaming) return false;
    resumeAbort = new AbortController();
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
    // 本地追加标记：占位符注入后，更早发出的历史加载视为过期（防覆盖占位/流式内容）
    localWriteSeq += 1;
    conversationStore.setState({
      messages: [...cur.messages, placeholder],
      streaming: true,
      streamingIndex: cur.messages.length,
      lastError: null,
      loading: false,
    });
    const acc = { answer: "", reasoning: "" };
    const sid = sessionId;
    const outcome = await streamChatRequest(
      { message: "resume", session_id: sid, resume: true },
      {
        onAnswerDelta: (d) => {
          // 会话守卫：当前会话已切换 → 停止渲染（防串写）
          if (sessionStore.getState().currentSessionId !== sid) return;
          if (conversationStore.getState().sessionId !== sid) return;
          acc.answer += d;
          patchStreaming({ content: acc.answer });
        },
        onReasoningDelta: (d) => {
          if (sessionStore.getState().currentSessionId !== sid) return;
          if (conversationStore.getState().sessionId !== sid) return;
          acc.reasoning += d;
          patchStreaming({ reasoningContent: acc.reasoning });
        },
        onToolRound: () => undefined,
      },
      resumeAbort?.signal
    );
    resumeAbort = null;
    if (outcome.ok && outcome.data) {
      // 归属守卫：完成时仍在本会话才改状态/重载（切走时新会话视图不受干扰）
      if (conversationStore.getState().sessionId === sessionId) {
        conversationStore.setState({ streaming: false, backgroundRunning: false });
      }
      if (sessionStore.getState().currentSessionId === sessionId) {
        void loadHistory(sessionId); // 终态 → 重载完整结果（含工具调用）
      }
      return true;
    }
    // 失败（run 已结束/网络）→ 移除占位、回退轮询（归属守卫防误删他会话消息）
    if (conversationStore.getState().sessionId === sessionId) {
      conversationStore.setState({
        messages: conversationStore.getState().messages.slice(0, -1),
        streaming: false,
      });
    }
    return false;
  } catch {
    return false;
  }
}

export async function loadEarlierHistory(sessionId: string): Promise<void> {
  const cur = conversationStore.getState();
  const writeMark = localWriteSeq;
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, cur.loadedHistoryCount);
  // 会话守卫：加载期间已切走/本地已追加 → 丢弃（防更早历史拼进他会话视图或覆盖新消息）
  if (conversationStore.getState().sessionId !== sessionId) return;
  if (localWriteSeq !== writeMark) return;
  const earlier = resp.messages.map(toChatMessage);
  conversationStore.setState({
    messages: [...earlier, ...cur.messages],
    hasMoreHistory: resp.has_more,
    loadedHistoryCount: cur.loadedHistoryCount + earlier.length,
  });
}

export function stopStreaming(): void {
  if (abortCtrl) {
    abortCtrl.abort();
    abortCtrl = null;
  }
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
  // 识别成功/待处理附件：内容注入上下文
  const okPrefix = attachments
    .filter((a) => a.status === "ok" || a.status === "pending")
    .map((a) => `[附件 ${a.filename}] ${a.result_text}`)
    .join("\n\n");
  // 识别失败/降级附件：如实标记"图片未包含"（防 LLM 从历史旧图内容幻觉，2026-08-15 现场）
  const failedPrefix = attachments
    .filter((a) => a.status === "degraded" || a.status === "error")
    .map(
      (a) =>
        `[附件 ${a.filename} 未能识别（${a.detail ?? "识别失败"}）——` +
        `本次请求未包含该图片内容，请勿猜测或虚构图片内容]`
    )
    .join("\n\n");
  const attachmentPrefix = [okPrefix, failedPrefix].filter(Boolean).join("\n\n");
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
  // 本地追加标记：在途历史加载（fetch 早于本条消息）视为过期，不得覆盖本地视图
  localWriteSeq += 1;
  conversationStore.setState({
    messages: [...cur.messages, userMsg, placeholder],
    streaming: true,
    streamingIndex: cur.messages.length + 1,
    lastError: null,
    streamStartedAt: Date.now(),
    // 归属会话（历史加载在途时 messages 可能已清空，归属取发送时刻会话；加载态打断）
    sessionId,
    loading: false,
  });

  // 2026-08-18 修复跳回旧会话: handleNew 后发送需 new_session=true（消费标记）
  const newSessionPending = sessionStore.getState().newSessionPending;
  if (newSessionPending) sessionStore.setNewSessionPending(false);
  const body = {
    message: effectiveText,
    session_id: sessionId,
    model: sessionStore.getState().model,
    reasoning_effort: sessionStore.getState().reasoningEffort,
    new_session: newSessionPending || undefined,
  };
  abortCtrl = new AbortController();
  const acc = { answer: "", reasoning: "", toolRounds: 0 };
  // 会话守卫：视图归属已切走 → 丢弃增量（内容不丢：后端 run 继续执行落盘，
  // 切回时经 checkBackgroundRun/loadHistory 恢复）
  const belongs = () => conversationStore.getState().sessionId === sessionId;

  const outcome = await streamChatRequest(
    body,
    {
      onAnswerDelta: (d) => {
        if (!belongs()) return;
        acc.answer += d;
        patchStreaming({ content: acc.answer });
      },
      onReasoningDelta: (d) => {
        if (!belongs()) return;
        acc.reasoning += d;
        patchStreaming({ reasoningContent: acc.reasoning });
      },
      onToolRound: () => {
        if (!belongs()) return;
        acc.toolRounds += 1;
        patchStreaming({ note: `工具调用进行中（${acc.toolRounds} 轮）…` });
      },
    },
    abortCtrl.signal
  );
  abortCtrl = null;

  const finalize = (msg: ChatMessage) => {
    const st = conversationStore.getState();
    // 会话守卫：用户已切走 → 不把本会话内容写进他会话视图（切回时后台 run 重放/重载恢复）
    if (st.sessionId !== sessionId) return;
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
        toolCalls: data.tool_calls,
        note: "（无文字回答）",
        streaming: false,
      });
    } else {
      finalize({ role: "assistant", content: acc.answer || "（无文字回答）", note: null, streaming: false });
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
    // 会话守卫：错误提示只写进本会话视图（切走不污染他会话页头）
    if (belongs()) conversationStore.setState({ lastError: note });
  }
}

function patchStreaming(partial: Partial<ChatMessage>): void {
  const st = conversationStore.getState();
  if (st.streamingIndex < 0) return;
  const idx = st.streamingIndex;
  const messages = st.messages.map((m, i) => (i === idx ? { ...m, ...partial } : m));
  conversationStore.setState({ messages });
}
