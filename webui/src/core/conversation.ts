// Web V2：对话 store（消息流 / 流式状态 / 历史分页 / 发送·停止·重试）

import { useSyncExternalStore } from "react";
import type {
  AttachmentFact,
  ChatDoneData,
  ChatMessage,
  QueueItem,
  ToolResultEvent,
  ToolRoundEvent,
} from "./types";
import {
  streamChatRequest,
  toChatMessage,
  buildAssistantNote,
  fetchHistory,
  fetchStreamStatus,
  fetchQueueList,
  enqueueQueueMessage,
  cancelQueueItem,
  claimNextQueued,
} from "./chat";
import { sessionStore } from "./stores";
import {
  mergeFinalToolCalls,
  settleRunningActivities,
  settleToolResult,
  startToolActivity,
} from "./toolActivity";

const HISTORY_PAGE_SIZE = 100;

interface ComposerPrefill {
  text: string;
  attachments: AttachmentFact[];
}

interface ConversationState {
  messages: ChatMessage[];
  composerPrefill: ComposerPrefill | null;
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
  /** 当前会话的 Human Turn 排队项（FIFO 序；后端 durable 事实的本地镜像） */
  queueItems: QueueItem[];
}

const listeners = new Set<() => void>();
let state: ConversationState = {
  messages: [],
  composerPrefill: null,
  hasMoreHistory: false,
  loadedHistoryCount: 0,
  streaming: false,
  backgroundRunning: false,
  streamingIndex: -1,
  lastError: null,
  streamStartedAt: null,
  queueItems: [],
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

/** Fill the composer after an explicit human edit/fork action. Never auto-send. */
export function prefillComposer(text: string, attachments: AttachmentFact[] = []): void {
  conversationStore.setState({
    composerPrefill: { text, attachments: [...attachments] },
  });
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
  // Human Turn 队列：切会话/刷新后恢复队列镜像；空闲且有排队 → 兜底接力
  // （多标签场景：A 标签关页后其 run 终态无人接力，切回时由这里补发）
  void (async () => {
    await refreshQueue(sessionId);
    void relayNextQueued(sessionId);
  })();
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
        onToolRound: (event: ToolRoundEvent) => {
          if (sessionStore.getState().currentSessionId !== sid) return;
          const current = conversationStore.getState();
          const active = current.streamingIndex >= 0
            ? current.messages[current.streamingIndex]?.toolActivities
            : undefined;
          patchStreaming({ toolActivities: startToolActivity(active, event) });
        },
        onToolResult: (event: ToolResultEvent) => {
          if (sessionStore.getState().currentSessionId !== sid) return;
          const current = conversationStore.getState();
          const active = current.streamingIndex >= 0
            ? current.messages[current.streamingIndex]?.toolActivities
            : undefined;
          patchStreaming({ toolActivities: settleToolResult(active, event) });
        },
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
  attachment_ref?: string;
  content_type?: string;
  size_bytes?: number;
  sha256?: string;
}

/** 队列接力选项：以排队时冻结的事实发起（模型/effort 不取当前 UI 值） */
export interface SendQueueOpts {
  queueId: string;
  frozenModel: string | null;
  frozenEffort: string | null;
  frozenReasoningMode: string | null;
}

export async function sendMessage(text: string, attachments: SendAttachment[], opts?: SendQueueOpts): Promise<void> {
  const cur = conversationStore.getState();
  // 空串归一为 null：新工作区/新会话无会话时后端按"新建会话"处理
  // （不可在此 return，否则新工作区发消息被静默拦截）
  const sessionId = sessionStore.getState().currentSessionId || null;
  // 本地发送即将写入/产生新消息：停空闲轮询防竞态（基线由完成后的重载路径重建）
  stopIdlePoll();
  // 附件以服务端 opaque ref 作为唯一授权引用；不再把提取全文拼进 human message。
  // pending/degraded/error 不进入当前模型请求，仍只作为 Composer UI 事实展示。
  const sendable = attachments.filter(
    (a) => a.status === "ok" && typeof a.attachment_ref === "string" && a.attachment_ref.length > 0
  );
  const attachmentRefs = sendable.map((a) => ({ ref: a.attachment_ref! }));
  const userAttachmentFacts: AttachmentFact[] = sendable.map((a) => ({
    ref: a.attachment_ref!,
    filename: a.filename,
    content_type: a.content_type,
    size_bytes: a.size_bytes,
    sha256: a.sha256,
  }));

  const localSendTs = Date.now() / 1000;
  const userMsg: ChatMessage = { role: "user", content: text, attachments: userAttachmentFacts, ts: localSendTs };
  const placeholder: ChatMessage = {
    role: "assistant",
    content: "",
    reasoningContent: "",
    toolCalls: null,
    note: null,
    streaming: true,
    streamStartedAt: Date.now(),
    ts: localSendTs,
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
    message: text,
    attachments: attachmentRefs,
    session_id: sessionId,
    // 队列接力：用排队时冻结的模型/effort/mode（不取当前 UI 值——冻结语义）
    model: opts ? opts.frozenModel : sessionStore.getState().model,
    reasoning_effort: opts ? opts.frozenEffort : sessionStore.getState().reasoningEffort,
    reasoning_mode: opts ? opts.frozenReasoningMode ?? undefined : sessionStore.getState().thinkingMode,
    new_session: newSessionPending || undefined,
    // 队列项回写：run 终态时后端把该 queue 项标 completed/failed（durable 收敛）
    queue_id: opts?.queueId,
  };
  const controller = new AbortController();
  abortCtrl = controller;
  abortSessionId = sessionId;
  const acc = { answer: "", reasoning: "" };

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
      onToolRound: (event: ToolRoundEvent) => {
        if (sessionStore.getState().currentSessionId !== sessionId) return;
        const current = conversationStore.getState();
        const active = current.streamingIndex >= 0
          ? current.messages[current.streamingIndex]?.toolActivities
          : undefined;
        patchStreaming({ toolActivities: startToolActivity(active, event), note: null });
      },
      onToolResult: (event: ToolResultEvent) => {
        if (sessionStore.getState().currentSessionId !== sessionId) return;
        const current = conversationStore.getState();
        const active = current.streamingIndex >= 0
          ? current.messages[current.streamingIndex]?.toolActivities
          : undefined;
        patchStreaming({ toolActivities: settleToolResult(active, event), note: null });
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
  const liveActivities = st.streamingIndex >= 0
    ? st.messages[st.streamingIndex]?.toolActivities
    : undefined;
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
        toolActivities: mergeFinalToolCalls(liveActivities, data.tool_calls),
        note: buildAssistantNote(data),
        streaming: false,
        ts: Date.now() / 1000,
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
        toolActivities: mergeFinalToolCalls(liveActivities, data.tool_calls),
        note: buildAssistantNote(data) ?? "（无文字回答）",
        streaming: false,
        ts: Date.now() / 1000,
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
        toolActivities: mergeFinalToolCalls(liveActivities, data.tool_calls),
        note: buildAssistantNote(data),
        streaming: false,
        ts: Date.now() / 1000,
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
      toolActivities: settleRunningActivities(liveActivities, "interrupted"),
      note,
      streaming: false,
      ts: Date.now() / 1000,
    });
    conversationStore.setState({ lastError: note });
    // 队列路径必有 sessionId（claim 项即来自该会话）；null 时跳过——后端 reaper 兜底
    if (opts?.queueId && sessionId) {
      if (outcome.error?.error === "session_busy") {
        // run owner 已在正式 admission 失败点把该 queue claim 安全回滚；前端只刷新镜像，
        // 不再自行调用 release（客户端不能成为“是否已开始执行”的真相源）。
        await refreshQueue(sessionId);
        return;
      }
      // 真失败（引擎/网络）：后端已把 queue 项标 failed；刷新镜像收敛 UI
      await refreshQueue(sessionId);
    }
    // 失败也是终态：队列接力继续（用户可看到错误后下一条照常发出）
    if (sessionId) void relayNextQueued(sessionId);
    return;
  }
  // 成功终态：FIFO 接力下一条排队消息（冻结事实派发）
  if (opts && sessionId) await refreshQueue(sessionId);
  if (sessionId) void relayNextQueued(sessionId);
}

function patchStreaming(partial: Partial<ChatMessage>): void {
  const st = conversationStore.getState();
  if (st.streamingIndex < 0) return;
  const idx = st.streamingIndex;
  const messages = st.messages.map((m, i) => (i === idx ? { ...m, ...partial } : m));
  conversationStore.setState({ messages });
}

// ══ Human Turn 排队（生成中 cmd/ctrl+Enter 插话；后端 durable 事实）══
// 模型（P0 假对齐修复）：zh.ts 已宣称"Cmd/Ctrl+Enter 插话发送（排队）"但
// 原实现流式时静默 return。本块补齐真实能力：入队冻结事实 → run 终态后
// FIFO 接力派发（多标签原子 claim 只有一个成功）。

/** 刷新当前会话队列镜像（FIFO 序；切会话/入队/取消/接力后调用） */
export async function refreshQueue(sessionId: string): Promise<void> {
  const resp = await fetchQueueList(sessionId);
  if (!resp) return;
  // 会话守卫：切换期间返回的旧会话队列不写回当前视图
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  conversationStore.setState({ queueItems: resp.items });
}

/** 入队一条 human turn（流式时 Composer cmd/ctrl+Enter 调用）：
 *  冻结 message/attachments/model/effort/created_at；返回 false 时调用方提示错误。 */
export async function enqueueQueueTurn(
  text: string,
  attachments: SendAttachment[]
): Promise<{ ok: boolean; detail?: string }> {
  const sessionId = sessionStore.getState().currentSessionId;
  if (!sessionId) return { ok: false, detail: "新会话尚未建立，无法排队（先发送第一条消息）" };
  const sendable = attachments.filter(
    (a) => a.status === "ok" && typeof a.attachment_ref === "string" && a.attachment_ref.length > 0
  );
  if (!text.trim() && sendable.length === 0) return { ok: false, detail: "空消息不能排队" };
  const refs = sendable.map((a) => ({ ref: a.attachment_ref! }));
  const st = sessionStore.getState();
  const resp = await enqueueQueueMessage(
    sessionId, text.trim(), refs, st.model, st.reasoningEffort, st.thinkingMode
  );
  if (!resp.ok) {
    return { ok: false, detail: resp.detail ?? "排队失败，请稍后重试" };
  }
  await refreshQueue(sessionId);
  return { ok: true };
}

/** 取消排队项（仅 queued 可取消；claimed 已进入发送流程） */
export async function cancelQueueTurn(queueId: string): Promise<void> {
  const sessionId = sessionStore.getState().currentSessionId;
  if (!sessionId) return;
  const ok = await cancelQueueItem(sessionId, queueId);
  if (!ok) {
    // 已被领取/不存在：刷新镜像收敛（终态由后端回写）
  }
  await refreshQueue(sessionId);
}

/** relay 防重入（多路径终态触发：done/error/停止/切回兜底） */
let relayInFlight: string | null = null;

/** run 终态后 FIFO 接力：原子领取队首 → 以冻结事实发起正式发送。
 *  多标签并发领取只有一个成功；领取后发现 session_busy/本地仍在流式 → release 回滚保持 FIFO。
 *  链式接力由 sendMessage 终态再次触发（队列消费自动递归）。 */
export async function relayNextQueued(sessionId: string): Promise<void> {
  if (relayInFlight === sessionId) return;
  if (sessionStore.getState().currentSessionId !== sessionId) return;
  const st = conversationStore.getState();
  if (st.streaming || st.backgroundRunning) return; // run 仍在进行：等其终态再接力
  const hasQueued = st.queueItems.some((it) => it.status === "queued");
  if (!hasQueued) return;
  relayInFlight = sessionId;
  try {
    const claimed = await claimNextQueued(sessionId);
    if (!claimed) {
      await refreshQueue(sessionId); // 队空或被其他标签领走：收敛镜像
      return;
    }
    await refreshQueue(sessionId); // claimed 状态立即反映到 UI
    // 以冻结事实发起正式发送（模型/effort 用冻结值；queue_id 让后端终态回写队列）
    const frozenAttachments: SendAttachment[] = (claimed.attachment_facts ?? []).map((f) => ({
      filename: f.filename,
      result_text: "",
      status: "ok",
      attachment_ref: f.ref,
      content_type: f.content_type,
      size_bytes: f.size_bytes,
      sha256: f.sha256,
    }));
    // sendMessage 终态（done/error）会再次触发 relayNextQueued → 链式消费。
    // 不 await（fire-and-forget）：await 会让本函数直到 run 终态才结束，
    // 防重入闸 relayInFlight 迟迟不清，反而拦死 sendMessage 终态处的链式接力。
    void sendMessage(claimed.message || "", frozenAttachments, {
      queueId: claimed.queue_id,
      frozenModel: claimed.model ?? null,
      frozenEffort: claimed.reasoning_effort ?? null,
      frozenReasoningMode: (claimed as { reasoning_mode?: string }).reasoning_mode ?? null,
    }).catch(() => {
      // 兜底：sendMessage 不应抛出；抛出则该队列项悬挂，由后端 reaper 回滚
    });
  } finally {
    relayInFlight = null;
  }
}
