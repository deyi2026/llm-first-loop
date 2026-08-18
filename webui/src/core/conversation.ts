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
  // 对齐 DSH（2026-08-17 用户需求）：切换会话时正在进行的操作内容不丢——
  // 当前流式 abort（SSE 断连 → 后端转后台继续执行）；切回时 checkBackgroundRun
  // 轮询到完成自动重载，过程内容完整保留。
  if (
    conversationStore.getState().streaming &&
    sessionStore.getState().currentSessionId !== sessionId
  ) {
    stopStreaming();
  }
  // 2026-08-18 修复串行：切换会话时中止进行中的 resume 订阅（防串写进新会话视图）
  if (resumeAbort) {
    resumeAbort.abort();
    resumeAbort = null;
  }
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, 0);
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
  if (!status || !status.running) return;
  conversationStore.setState({ backgroundRunning: true });
  const resumed = await resumeBackgroundStream(sessionId);
  if (resumed) return; // 订阅成功——流式接管（done 后自动重载）
  // 回退：轮询直到完成（订阅失败/不支持——run 已结束或网络异常）
  bgPollTimer = window.setInterval(async () => {
    const s = await fetchStreamStatus(sessionId);
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
  try {
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
      resumeAbort?.signal
    );
    resumeAbort = null;
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
  conversationStore.setState({
    messages: [...cur.messages, userMsg, placeholder],
    streaming: true,
    streamingIndex: cur.messages.length + 1,
    lastError: null,
    streamStartedAt: Date.now(),
  });

  const body = {
    message: effectiveText,
    session_id: sessionId,
    model: sessionStore.getState().model,
    reasoning_effort: sessionStore.getState().reasoningEffort,
  };
  abortCtrl = new AbortController();
  const acc = { answer: "", reasoning: "", toolRounds: 0 };

  const outcome = await streamChatRequest(
    body,
    {
      onAnswerDelta: (d) => {
        acc.answer += d;
        patchStreaming({ content: acc.answer });
      },
      onReasoningDelta: (d) => {
        acc.reasoning += d;
        patchStreaming({ reasoningContent: acc.reasoning });
      },
      onToolRound: () => {
        acc.toolRounds += 1;
        patchStreaming({ note: `工具调用进行中（${acc.toolRounds} 轮）…` });
      },
    },
    abortCtrl.signal
  );
  abortCtrl = null;

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
