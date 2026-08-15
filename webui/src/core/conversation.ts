// Web V2：对话 store（消息流 / 流式状态 / 历史分页 / 发送·停止·重试）

import { useSyncExternalStore } from "react";
import type { ChatDoneData, ChatMessage } from "./types";
import { streamChatRequest, toChatMessage, buildAssistantNote, fetchHistory } from "./chat";
import { sessionStore } from "./stores";

const HISTORY_PAGE_SIZE = 100;

interface ConversationState {
  messages: ChatMessage[];
  hasMoreHistory: boolean;
  loadedHistoryCount: number;
  streaming: boolean;
  /** 当前进行中的助手消息索引（-1=无） */
  streamingIndex: number;
  lastError: string | null;
}

const listeners = new Set<() => void>();
let state: ConversationState = {
  messages: [],
  hasMoreHistory: false,
  loadedHistoryCount: 0,
  streaming: false,
  streamingIndex: -1,
  lastError: null,
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
  const resp = await fetchHistory(sessionId, HISTORY_PAGE_SIZE, 0);
  const messages = resp.messages.map(toChatMessage);
  conversationStore.setState({
    messages,
    hasMoreHistory: resp.has_more,
    loadedHistoryCount: messages.length,
    streaming: false,
    streamingIndex: -1,
    lastError: null,
  });
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
export async function sendMessage(
  text: string,
  attachments: Array<{ filename: string; result_text: string }>
): Promise<void> {
  const cur = conversationStore.getState();
  const sessionId = sessionStore.getState().currentSessionId;
  if (!sessionId) return;
  const attachmentPrefix = attachments
    .map((a) => `[附件 ${a.filename}] ${a.result_text}`)
    .join("\n\n");
  const effectiveText = attachmentPrefix ? `${attachmentPrefix}\n\n${text}` : text;

  const userMsg: ChatMessage = { role: "user", content: text };
  const placeholder: ChatMessage = {
    role: "assistant",
    content: "",
    reasoningContent: "",
    toolCalls: null,
    note: null,
    streaming: true,
  };
  conversationStore.setState({
    messages: [...cur.messages, userMsg, placeholder],
    streaming: true,
    streamingIndex: cur.messages.length + 1,
    lastError: null,
  });

  const body = {
    message: effectiveText,
    session_id: sessionId,
    model: sessionStore.getState().model,
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
