// LLM-First Loop Web 聊天界面（M37，静态原生 JS，无框架）
// 消费 M36 API：POST /api/v1/chat + GET /api/v1/sessions + DELETE /api/v1/sessions/{id}?confirm=true

"use strict";

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  attachments: [], // M39 上传附件上下文（发送时作为 user 消息前缀注入）
  model: null, // M47 当前模型（模型切换下拉，None=装配默认）
  pendingNewSession: false, // 2026-08-18: /new 后待发标志（下次消息强制新建会话）
  availableModels: [], // M47 服务端声明的可用模型列表（/model 命令校验用）
  typewriterPending: false, // T3: 最新 assistant 回复是否用假流式打字机渲染
  hasMoreHistory: false, // D2: 是否还有更早历史消息（懒加载）
  loadedHistoryCount: 0, // D2: 已加载历史消息条数（offset 基准）
  retryRequest: null, // D2 断流重试: 最近一次流式请求体（重试复用）
  declarationIndex: new Map(), // P3-1: 页面级声明暂存（session_id → Map<toolCallId, {id,name,arguments}>，不落盘）
};

// D2: 历史懒加载分页大小（首屏/每次"加载更早"的条数）
const HISTORY_PAGE_SIZE = 50;

const els = {
  statusBadge: document.getElementById("status-badge"),
  newSessionBtn: document.getElementById("new-session-btn"),
  searchInput: document.getElementById("search-input"),
  sessionList: document.getElementById("session-list"),
  messages: document.getElementById("messages"),
  messageInput: document.getElementById("message-input"),
  sendBtn: document.getElementById("send-btn"),
  clearBtn: document.getElementById("clear-btn"),
  uploadBtn: document.getElementById("upload-btn"),
  fileInput: document.getElementById("file-input"),
  chatArea: document.getElementById("chat-area"),
  modelSelect: document.getElementById("model-select"),
  cmdSuggest: document.getElementById("cmd-suggest"),
  // P4-2: 移动端响应式引用
  app: document.getElementById("app"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
  sidebarScrim: document.getElementById("sidebar-scrim"),
};

// M47 快捷命令定义（argHint 非空表示需附加参数，点击只填入不自动执行）
const COMMANDS = [
  { name: "/new", desc: "新建会话" },
  { name: "/clear", desc: "清除上下文（新建隔离会话，旧会话保留）" },
  { name: "/model", desc: "切换模型，如 /model deepseek-v4-pro（或用下方下拉）", argHint: " <模型名>" },
  { name: "/help", desc: "查看可用命令" },
];

// ---------- 工具 ----------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fmtRelative(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}小时前`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 30) return `${diffDay}天前`;
  return d.toLocaleDateString();
}

async function api(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({}));
  return { status: resp.status, data };
}

function setStatus(ok, text) {
  els.statusBadge.textContent = text;
  els.statusBadge.className = "status-badge " + (ok ? "ok" : "err");
}

// ---------- 长内容分块粒度（2026-08-15 用户需求：不折叠，过长分块输出） ----------
const LONG_LINE_THRESHOLD = 200;   // pre 代码块行数超此值顺序分段（每段 ≤ 200 行全量可见，无折叠）

