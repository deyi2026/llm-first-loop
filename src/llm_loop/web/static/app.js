// LLM-First Loop Web 聊天界面（M37，静态原生 JS，无框架）
// 消费 M36 API：POST /api/v1/chat + GET /api/v1/sessions + DELETE /api/v1/sessions/{id}?confirm=true

"use strict";

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  attachments: [], // M39 上传附件上下文（发送时作为 user 消息前缀注入）
  model: null, // M47 当前模型（模型切换下拉，None=装配默认）
  availableModels: [], // M47 服务端声明的可用模型列表（/model 命令校验用）
  typewriterPending: false, // T3: 最新 assistant 回复是否用假流式打字机渲染
};

const els = {
  statusBadge: document.getElementById("status-badge"),
  newSessionBtn: document.getElementById("new-session-btn"),
  searchInput: document.getElementById("search-input"),
  sessionList: document.getElementById("session-list"),
  messages: document.getElementById("messages"),
  messageInput: document.getElementById("message-input"),
  sendBtn: document.getElementById("send-btn"),
  uploadBtn: document.getElementById("upload-btn"),
  fileInput: document.getElementById("file-input"),
  chatArea: document.getElementById("chat-area"),
  modelSelect: document.getElementById("model-select"),
  cmdSuggest: document.getElementById("cmd-suggest"),
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

// ---------- 长文本折叠阈值（T3，spec.md 5.2.1） ----------
const LONG_LINE_THRESHOLD = 200;   // pre 代码块行数超此值折叠为前 20 行摘要
const LONG_CHAR_THRESHOLD = 20000; // 消息体字符数超此值折叠为前 2000 字符摘要

// ---------- Markdown 渲染（M38） ----------
const MD_ALLOWED_TAGS = new Set([
  "p", "strong", "em", "b", "i", "code", "pre", "blockquote",
  "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
  "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "br", "hr", "span", "del",
]);
const MD_ALLOWED_ATTRS = {
  a: ["href", "title"],
  img: ["src", "alt", "title"],
  th: ["align"],
  td: ["align"],
  code: ["class"],
  pre: ["class"],
};
const MD_SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

function sanitizeHtml(raw) {
  // 白名单 DOM sanitizer（M38，防 XSS）：移除危险标签/属性，保留文本内容
  if (typeof DOMParser === "undefined") return null;
  const doc = new DOMParser().parseFromString(raw, "text/html");
  const walk = (node) => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === 1) {
        const tag = child.tagName.toLowerCase();
        if (!MD_ALLOWED_TAGS.has(tag)) {
          // 危险/非白名单标签：移除外壳，保留子节点与文本（不删文本语义）
          while (child.firstChild) node.insertBefore(child.firstChild, child);
          node.removeChild(child);
          continue;
        }
        for (const attr of [...child.attributes]) {
          const an = attr.name.toLowerCase();
          const allowed = (MD_ALLOWED_ATTRS[tag] || []).includes(an);
          if (!allowed || an.startsWith("on")) {
            child.removeAttribute(attr.name);
            continue;
          }
          if (an === "href" || an === "src") {
            let val = (attr.value || "").trim().toLowerCase();
            if (!val.startsWith("#")) {
              const proto = val.match(/^([a-z][a-z0-9+.-]*):/);
              if (proto && !MD_SAFE_PROTOCOLS.has(proto[1] + ":")) {
                child.removeAttribute(attr.name); // 拒绝 javascript:/data: 等可执行协议
                continue;
              }
            }
          }
        }
        walk(child);
      }
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

function renderMarkdown(md) {
  // MD → HTML（marked gfm）→ sanitize；异常返回 null（调用方降级纯文本）
  if (typeof marked === "undefined") return null;
  try {
    const rawHtml = marked.parse(md, { gfm: true });
    return sanitizeHtml(rawHtml);
  } catch (err) {
    console.error("MD 渲染失败，降级纯文本:", err);
    return null;
  }
}

// ---------- P2-1 工具调用链渲染（M49） ----------
function fmtToolArgs(args) {
  // 参数摘要：JSON 序列化，超长截断；stringify 异常降级显示原始字符串
  if (args === undefined || args === null) return "";
  try {
    const s = JSON.stringify(args);
    return s.length > 200 ? s.slice(0, 200) + "…" : s;
  } catch (err) {
    return String(args);
  }
}

function renderToolCalls(toolCalls, container) {
  // 空/非数组直接返回（不产生 DOM 残留）
  if (!Array.isArray(toolCalls) || !toolCalls.length) return;
  const chain = el("div", "tool-call-chain");
  const toggle = el("button", "tool-call-toggle", `🔧 工具调用 ${toolCalls.length} 次 ▸`);
  toggle.type = "button";
  const detail = el("div", "tool-call-detail");
  detail.hidden = true;
  toggle.onclick = () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = `🔧 工具调用 ${toolCalls.length} 次 ${detail.hidden ? "▸" : "▾"}`;
  };
  for (const tc of toolCalls) {
    const item = el("div", "tool-call-item");
    item.appendChild(el("span", "tool-call-name", String(tc.name || "tool")));
    const argsText = fmtToolArgs(tc.arguments);
    if (argsText) item.appendChild(el("div", "tool-call-detail-text", `参数: ${argsText}`));
    detail.appendChild(item);
  }
  chain.appendChild(toggle);
  chain.appendChild(detail);
  container.insertBefore(chain, container.firstChild);
}

function renderToolMessage(msg, container) {
  // 历史 tool 角色消息 → 折叠回执（解析 [状态: xxx] 前缀作为摘要）
  const chain = el("div", "tool-call-chain");
  const content = String(msg.content || "");
  const m = content.match(/^\[([^\]]+)\]/);
  // M52: 异常回执醒目（error/failure/安全硬阻断/程序异常 → 红色警示样式 + ⚠️）
  const statusText = m ? m[1] : "";
  const isError = /error|failure|失败|参数错误|安全硬阻断|程序异常/i.test(statusText)
    || /^\[安全硬阻断\]/.test(content) || /^\[程序异常\]/.test(content);
  const summary = `${isError ? "⚠️" : "🔧"} ${statusText || "工具回执"}`;
  const toggle = el("button", "tool-call-toggle" + (isError ? " tool-call-toggle-error" : ""), `${summary} ▸`);
  toggle.type = "button";
  const detail = el("div", "tool-call-detail");
  detail.hidden = true;
  toggle.onclick = () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = `${summary} ${detail.hidden ? "▸" : "▾"}`;
  };
  detail.appendChild(el("div", "tool-call-detail-text", content));
  // M52: 分层截断/已归档 → "查看完整原文"（按 tool_call_id 精确取档案，失败如实提示）
  const layered = content.includes("[工具输出已分层]") || content.includes("已另存至压缩档案");
  if (layered && msg.tool_call_id && state.currentSessionId) {
    const btn = el("button", "tool-call-full-btn", "📄 查看完整原文");
    btn.type = "button";
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = "⏳ 加载中…";
      try {
        const resp = await fetch(`/api/v1/sessions/${state.currentSessionId}/archive/${msg.tool_call_id}`);
        const data = await resp.json();
        if (resp.ok) {
          detail.appendChild(el("div", "tool-call-detail-text tool-call-full-text",
            `── 完整原文（${data.tool_name || "tool"}，${data.chars} 字符，归档于 ${data.ts}）──\n${data.content}`));
          btn.remove();
        } else {
          btn.disabled = false;
          btn.textContent = `📄 原文不可用：${data.detail || "未知原因"}`;
        }
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "📄 加载失败（网络异常），点击重试";
      }
    };
    chain.appendChild(btn);
  }
  chain.appendChild(toggle);
  chain.appendChild(detail);
  container.appendChild(chain);
}

// ---------- 消息渲染 ----------
function renderMessages() {
  els.messages.innerHTML = "";
  for (const msg of state.messages) {
    const node = document.createElement("div");
    node.className = "message " + msg.role;
    // M52: 架构事件/程序异常消息醒目（红色左边框，不混入普通消息流）
    if (msg.role === "assistant" && /\[(架构上报|程序异常|安全硬阻断)\]/.test(String(msg.content || ""))) {
      node.classList.add("message-alert");
    }
    if (msg.role === "tool") {
      // P2-1: 历史 tool 角色消息渲染为折叠回执
      const wrap = document.createElement("div");
      wrap.className = "message-wrap";
      wrap.appendChild(node);
      renderToolMessage(msg, wrap);
      els.messages.appendChild(wrap);
      continue;
    }
    if (msg.role === "assistant") {
      // AI 回答：MD 渲染（经 sanitize）；渲染失败降级纯文本（不空白不伪造）
      // P2-1: AI 回复内容前插入折叠工具调用链（若有）
      if (Array.isArray(msg.toolCalls) && msg.toolCalls.length) {
        renderToolCalls(msg.toolCalls, node);
      }
      // 正文容器（打字机只作用于正文，不碰工具链/note）
      const body = el("div", "answer-body");
      node.appendChild(body);
      // 一键复制按钮（M39）：位于回复框右下角，复制 final_answer 原文纯文本
      const wrap = document.createElement("div");
      wrap.className = "message-wrap";
      wrap.appendChild(node);
      const copyBtn = el("button", "copy-btn", "复制");
      copyBtn.onclick = () => copyMessage(msg.content, copyBtn);
      wrap.appendChild(copyBtn);
      els.messages.appendChild(wrap);
      if (msg.note) {
        node.appendChild(el("span", "msg-note", msg.note));
      }
      // 渲染正文 + 后处理（代码块复制按钮 + 长内容折叠）
      const finalize = () => {
        // 回复内命令框（代码块）右上角也提供复制按钮
        addCodeBlockCopyButtons(node);
        // T3: 长内容折叠（超阈值 pre/消息体 → 摘要 + 展开全文）
        collapseLongContent(node);
      };
      const html = renderMarkdown(msg.content);
      const shouldTypewrite =
        msg === state.messages[state.messages.length - 1] && state.typewriterPending;
      if (shouldTypewrite) state.typewriterPending = false;
      if (html === null) {
        body.textContent = msg.content;
        finalize();
      } else if (shouldTypewrite) {
        // T3: 前端假流式打字机（仅最新一条 assistant 渐进渲染，历史消息一次性，零后端改动）
        fakeTypewriter(body, msg.content, 40, 20, finalize);
      } else {
        body.innerHTML = html;
        finalize();
      }
    } else {
      // user：M47 起也渲染 MD（纯文本降级）；error：纯文本如实回显
      if (msg.role === "user") {
        const html = renderMarkdown(msg.content);
        if (html !== null) {
          node.innerHTML = html;
        } else {
          node.textContent = msg.content;
        }
        const wrap = document.createElement("div");
        wrap.className = "message-wrap user-wrap";
        wrap.appendChild(node);
        const copyBtn = el("button", "copy-btn copy-btn-left", "复制");
        copyBtn.onclick = () => copyMessage(msg.content, copyBtn);
        wrap.appendChild(copyBtn);
        els.messages.appendChild(wrap);
        addCodeBlockCopyButtons(node);
        collapseLongContent(node);
      } else {
        node.textContent = msg.content;
        els.messages.appendChild(node);
      }
      if (msg.note) {
        node.appendChild(el("span", "msg-note", msg.note));
      }
    }
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

// 为回复中每个代码块（pre）添加右上角复制按钮，复制该代码块文本
function addCodeBlockCopyButtons(container) {
  for (const pre of container.querySelectorAll("pre")) {
    if (pre.parentElement && pre.parentElement.classList.contains("code-block-wrap")) continue;
    const wrap = document.createElement("div");
    wrap.className = "code-block-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const btn = el("button", "code-copy-btn", "复制");
    btn.onclick = () => copyMessage(pre.textContent, btn);
    wrap.appendChild(btn);
  }
}

// T2: 长内容折叠器（重构版：摘要/全文节点分离 + 显隐切换，spec 5.2.1 / design §2.1.3.2）
// collapseUnit：为超阈值容器建「摘要节点 + 全文节点 + 切换按钮」，展开/折叠仅切 hidden，不重建 DOM（消除按钮失效缺陷）
// pre 行数 > LONG_LINE_THRESHOLD → 代码摘要（renderMarkdown 渲染代码块，保留格式）；消息体非代码块 > LONG_CHAR_THRESHOLD → HTML 摘要（复制已渲染元素，保留 MD 格式）
// 折叠异常 fail-open：保留原样 + console.error，不空白不伪造
function collapseUnit(target, summaryNode) {
  // 把 target 现有子节点移入全文节点（appendChild 移动保留事件绑定，不重建 DOM），
  // 再插入摘要节点 + 全文节点 + 切换按钮；展开/折叠仅切 hidden + dataset 状态
  const fullNode = el("div", "collapsed-full");
  while (target.firstChild) {
    fullNode.appendChild(target.firstChild);
  }
  fullNode.hidden = true;
  const btn = el("button", "expand-btn", "展开全文");
  btn.type = "button";
  let collapsed = true;
  btn.onclick = () => {
    collapsed = !collapsed;
    summaryNode.hidden = !collapsed;
    fullNode.hidden = collapsed;
    target.dataset.collapsed = collapsed ? "1" : "";
    btn.textContent = collapsed ? "展开全文" : "折叠";
  };
  target.appendChild(summaryNode);
  target.appendChild(fullNode);
  target.appendChild(btn);
  target.dataset.collapsed = "1";
}

function collapseLongContent(node) {
  try {
    // 1. pre 级折叠：超长代码块（摘要经 renderMarkdown 渲染代码块，保留格式）
    for (const pre of node.querySelectorAll("pre")) {
      if (pre.closest(".collapsed-full")) continue;
      const text = pre.textContent || "";
      const lines = text.split("\n");
      if (lines.length <= LONG_LINE_THRESHOLD) continue;
      const wrap = pre.parentElement;
      if (!wrap || wrap.dataset.collapsed) continue;
      const summaryMd =
        "```\n" + lines.slice(0, 20).join("\n") + "\n…（共 " + lines.length + " 行，已折叠，点击展开全文）\n```";
      const summaryNode = el("div", "collapsed-summary");
      const summaryHtml = renderMarkdown(summaryMd);
      if (summaryHtml !== null) {
        summaryNode.innerHTML = summaryHtml;
      } else {
        summaryNode.appendChild(el("pre", "", lines.slice(0, 20).join("\n") + "\n…（已折叠）"));
      }
      collapseUnit(wrap, summaryNode);
    }
    // 2. 消息体级折叠：非代码块长文本（摘要复制已渲染 HTML 元素，保留 MD 格式，排除已折叠 pre）
    if (!node.dataset.bodyCollapsed) {
      const probe = node.cloneNode(true);
      probe.querySelectorAll("pre, .code-block-wrap, .tool-call-chain, .expand-btn").forEach((e) => e.remove());
      const nonCodeText = probe.textContent || "";
      if (nonCodeText.length > LONG_CHAR_THRESHOLD) {
        node.dataset.bodyCollapsed = "1";
        const summaryNode = el("div", "collapsed-summary");
        let chars = 0;
        for (const child of [...probe.childNodes]) {
          if (chars >= 2000) break;
          summaryNode.appendChild(child.cloneNode(true));
          chars += (child.textContent || "").length;
        }
        summaryNode.appendChild(el("div", "collapsed-summary-hint", "…（内容超长，已折叠，点击展开全文）"));
        collapseUnit(node, summaryNode);
      }
    }
  } catch (err) {
    console.error("长内容折叠失败（fail-open）:", err);
  }
}

// T3: 前端假流式打字机（方案 A，零后端改动，spec 5.3.1 / design §2.1.3.3）
// 按字符分片 MD，逐片 renderMarkdown + sanitize 后替换正文节点，渐进渲染（打字机体验）
// 分片渲染异常 → fail-open：一次性渲染完整内容 + console.error，不空白
function fakeTypewriter(node, answerHtml, chunkChars, intervalMs, onDone) {
  chunkChars = chunkChars || 40;
  intervalMs = intervalMs || 20;
  const total = String(answerHtml || "").length;
  if (total === 0) {
    if (onDone) onDone();
    return;
  }
  let pos = 0;
  const step = () => {
    pos += chunkChars;
    const done = pos >= total;
    const part = done ? answerHtml : answerHtml.slice(0, pos);
    const html = renderMarkdown(part);
    if (html !== null) {
      node.innerHTML = html;
    } else {
      node.textContent = part;
    }
    if (done) {
      if (onDone) onDone();
    } else {
      node.appendChild(el("span", "typewriter-cursor", "▌"));
      els.messages.scrollTop = els.messages.scrollHeight;
      setTimeout(step, intervalMs);
    }
  };
  step();
}

function addMessage(role, content, note, toolCalls) {
  const m = { role, content, note };
  if (Array.isArray(toolCalls) && toolCalls.length) m.toolCalls = toolCalls;
  state.messages.push(m);
  renderMessages();
}

// ---------- M52: token 用量显示 ----------
function fmtTokens(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function renderTokenStats() {
  const elStats = document.getElementById("token-stats");
  if (!elStats) return;
  const inTok = state.pageTokensIn || 0;
  const outTok = state.pageTokensOut || 0;
  if (!inTok && !outTok) { elStats.textContent = ""; return; }
  elStats.textContent = `tokens 本次页面: ${fmtTokens(inTok)}入/${fmtTokens(outTok)}出`;
}

// ---------- 发送消息 ----------
async function sendMessage() {
  const text = els.messageInput.value.trim();
  if (!text) return; // 空消息前端校验
  els.messageInput.value = "";
  autoGrowInput();
  hideCmdSuggest();
  // M39 命令处理：/ 开头消息走纯前端命令分支（不调 API）
  if (text.startsWith("/")) {
    handleCommand(text);
    return;
  }
  // M39 附件上下文前缀注入：发送时附件处理结果作为 user 消息前缀（含来源标注，发送后清空）
  const attachmentPrefix = state.attachments.map((a) => `[附件 ${a.filename}] ${a.result_text}`).join("\n\n");
  const effectiveText = attachmentPrefix ? `${attachmentPrefix}\n\n${text}` : text;
  if (attachmentPrefix) state.attachments = [];
  addMessage("user", text);
  const loading = el("div", "message assistant loading", "思考中…");
  els.messages.appendChild(loading);
  els.messages.scrollTop = els.messages.scrollHeight;
  els.sendBtn.disabled = true;

  try {
    const body = { message: effectiveText };
    if (state.currentSessionId) body.session_id = state.currentSessionId;
    if (state.model) body.model = state.model; // M47 模型切换：对当前请求生效
    const { status, data } = await api("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    loading.remove();

    if (status === 200) {
      state.currentSessionId = data.session_id;
      const note = [];
      if (data.truncated) note.push("（回答被截断，建议新建会话或调整 prompt 继续）");
      if (data.verification_note) note.push(data.verification_note);
      // M51: 回复下方标注实际生成模型（provider/model，含降级后的真实模型）
      // M52: 同一 footer 附带本轮 token 用量（provider 未返回 usage 时不显示）
      if (data.model_used) {
        let footer = `—— ${data.model_used}`;
        if (data.tokens_in || data.tokens_out) {
          footer += ` · ${fmtTokens(data.tokens_in)}入/${fmtTokens(data.tokens_out)}出`;
        }
        note.push(footer);
      }
      // P2-1: 透传本轮工具调用链（tool_calls 已由后端返回，前端渲染折叠链）
      state.typewriterPending = true; // T3: 最新回复用假流式打字机渲染
      addMessage("assistant", data.final_answer, note.join("\n") || null, data.tool_calls);
      // M52: 本次页面会话 token 累计（输入区模型选择旁实时更新）
      if (data.tokens_in || data.tokens_out) {
        state.pageTokensIn = (state.pageTokensIn || 0) + data.tokens_in;
        state.pageTokensOut = (state.pageTokensOut || 0) + data.tokens_out;
        renderTokenStats();
      }
    } else if (status === 404) {
      addMessage("error", data.detail || "会话不存在，请新建会话。");
      state.currentSessionId = null;
    } else if (status === 500) {
      addMessage("error", data.detail || "服务内部错误。");
    } else {
      addMessage("error", `请求失败（${status}）：${data.detail || "未知错误"}`);
    }
  } catch (err) {
    loading.remove();
    addMessage("error", `网络错误：${err.message}`);
  } finally {
    els.sendBtn.disabled = false;
    els.messageInput.focus();
  }

  loadSessions(); // 刷新侧栏（会话可能新建/更新）
}

// ---------- 会话管理 ----------
async function loadSessions() {
  const { status, data } = await api("/api/v1/sessions");
  if (status !== 200) return;
  state.sessions = data.sessions || [];
  renderSessions();
}

async function loadSessionMessages(sessionId) {
  const { status, data } = await api(`/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`);
  if (status !== 200) return;
  // P2-1: 白名单保留 tool 角色（工具调用回执），历史刷新后仍可见
  state.messages = (data.messages || [])
    .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool")
    .map((m) => ({ role: m.role, content: m.content, note: null }));
  renderMessages();
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  const q = els.searchInput.value.trim().toLowerCase();
  const list = state.sessions.filter((s) =>
    !q || (s.title || "").toLowerCase().includes(q) || (s.last_message_preview || "").toLowerCase().includes(q)
  );
  for (const s of list) {
    const item = el("li", "session-item" + (s.session_id === state.currentSessionId ? " active" : ""));
    // M56 置顶按钮（📌 置顶 / 📍 未置顶）
    const pinBtn = el("button", "session-pin" + (s.pinned ? " pinned" : ""), s.pinned ? "📌" : "📍");
    pinBtn.title = s.pinned ? "取消置顶" : "置顶";
    pinBtn.onclick = (e) => {
      e.stopPropagation();
      setSessionPin(s.session_id, !s.pinned);
    };
    item.appendChild(pinBtn);
    const delBtn = el("button", "session-del", "✕");
    delBtn.title = "删除会话";
    delBtn.onclick = (e) => {
      e.stopPropagation();
      deleteSession(s.session_id);
    };
    item.appendChild(delBtn);
    const title = el("div", "session-title", s.title || "未命名");
    // M56 来源标签（飞书会话标注；Web 端不标）
    if (s.channel && s.channel !== "web") {
      title.appendChild(el("span", "session-channel", "飞书"));
    }
    const meta = el(
      "div",
      "session-meta",
      `${fmtRelative(s.updated_at)} · ${s.last_message_preview || "（无消息）"}`
    );
    item.appendChild(title);
    item.appendChild(meta);
    item.onclick = () => selectSession(s.session_id);
    els.sessionList.appendChild(item);
  }
}

// M56 置顶/取消置顶（后端排序：置顶优先）
async function setSessionPin(sessionId, pinned) {
  const { status } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/pin?pinned=${pinned}`,
    { method: "POST" }
  );
  if (status !== 200) {
    addMessage("error", "置顶操作失败。");
  }
  loadSessions();
}

function selectSession(sessionId) {
  state.currentSessionId = sessionId;
  state.messages = [];
  renderMessages();
  renderSessions();
  loadSessionMessages(sessionId); // 加载该会话历史消息
  els.messageInput.focus();
}

function newSession() {
  state.currentSessionId = null;
  state.messages = [];
  renderMessages();
  renderSessions();
  els.messageInput.focus();
}

async function deleteSession(sessionId) {
  if (!window.confirm("删除为不可逆操作，确认删除该会话？")) return; // 二次确认（对齐 confirm=true）
  const { status, data } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}?confirm=true`,
    { method: "DELETE" }
  );
  if (status === 200) {
    if (state.currentSessionId === sessionId) {
      state.currentSessionId = null;
      state.messages = [];
      renderMessages();
    }
    loadSessions();
  } else {
    addMessage("error", data.detail || "会话删除失败。");
  }
}

// ---------- 初始化 ----------
async function init() {
  try {
    const { status } = await api("/health");
    setStatus(status === 200, status === 200 ? "已连接" : "异常");
  } catch {
    setStatus(false, "未连接");
  }
  await loadModels(); // M47 模型切换候选
  await loadSessions();
  initEventStream(); // M56 实时刷新（飞书/Web 会话同步）
  // 优先加载跨端共享当前会话（Web/飞书同一上下文），否则取最近会话
  let target = null;
  try {
    const r = await api("/api/v1/session/current");
    if (r.status === 200 && r.data.current) {
      target = state.sessions.find((s) => s.session_id === r.data.current) || null;
    }
  } catch {
    /* fail-open */
  }
  if (!target) target = state.sessions[0];
  if (target) {
    selectSession(target.session_id);
  }
}

// ---------- M56 SSE 实时刷新（飞书/Web 会话同步） ----------
function initEventStream() {
  if (typeof EventSource === "undefined") return; // 老旧浏览器降级为手动刷新
  const es = new EventSource("/api/v1/events");
  es.addEventListener("sessions_updated", () => {
    loadSessions(); // 刷新列表（预览/置顶顺序/来源标签）
    if (state.currentSessionId) {
      loadSessionMessages(state.currentSessionId); // 刷新当前会话（飞书侧新消息实时可见）
    }
  });
}

// ---------- M39 命令处理（纯前端状态操作，不调 API） ----------
function handleCommand(cmd) {
  const parts = cmd.trim().split(/\s+/);
  const name = (parts[0] || "").toLowerCase();
  if (name === "/new") {
    newSession();
    addMessage("system", "已新建会话（下一条消息将进入全新会话）。");
  } else if (name === "/clear") {
    // M62 修复: 彻底隔离——清空 currentSessionId 等同新建会话，
    // 否则下一条消息仍发到旧会话（上下文超限错误继续出现）
    newSession();
    addMessage("system", "已清除上下文（下一条消息将进入全新会话，旧会话保留可查看）。");
  } else if (name === "/model") {
    const m = (parts[1] || "").trim();
    if (!m) {
      addMessage("error", "用法: /model <模型名>。当前候选见输入栏下方下拉列表。");
    } else if (state.availableModels.length && !state.availableModels.includes(m)) {
      addMessage("error", `模型 ${m} 不被当前 API 支持（可用: ${state.availableModels.join(" / ")}）。已保持当前模型不变。`);
    } else {
      state.model = m;
      for (const opt of els.modelSelect.options) {
        if (opt.value === m) { els.modelSelect.value = m; break; }
      }
      addMessage("system", `已切换模型：${m}（下一条消息生效）。`);
    }
  } else if (name === "/help") {
    addMessage("system", "可用命令：\n/new 新建会话\n/clear 清除上下文（新建隔离会话，旧会话保留）\n/model <模型名> 切换模型（或用输入栏下方下拉）\n/help 帮助\n其余以 / 开头的输入视为未知命令。");
  } else {
    addMessage("error", `未知命令：${name}。输入 /help 查看可用命令。`);
  }
  loadSessions();
}

// ---------- M39 复制按钮（Clipboard API 复制原文纯文本） ----------
async function copyMessage(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = "已复制";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = "复制";
      btn.classList.remove("copied");
    }, 1500);
  } catch (err) {
    // 剪贴板 API 不可用（如非安全上下文）：如实提示 + textarea 降级复制
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      btn.textContent = "已复制";
      btn.classList.add("copied");
      setTimeout(() => { btn.textContent = "复制"; btn.classList.remove("copied"); }, 1500);
    } catch (err2) {
      addMessage("error", `复制失败：${err2.message}`);
    }
  }
}

// ---------- M39 上传附件 ----------
async function uploadFile(file) {
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = reader.result.split(",")[1]; // data:...;base64, 前缀剥离
    try {
      const { status, data } = await api("/api/v1/upload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, data: b64 }),
      });
      if (status === 200) {
        const statusText = { ok: "处理成功", degraded: "降级", pending: "待处理", error: "失败" }[data.status] || data.status;
        addAttachmentBubble(file.name, data.content_type, statusText, data.result_text, data.detail);
        if (data.status === "ok" || data.status === "pending") {
          // 处理结果暂存附件上下文（发送时作为 user 消息前缀注入）
          state.attachments.push({ filename: file.name, result_text: data.result_text || data.detail || "" });
        }
      } else {
        addMessage("error", `上传失败（${status}）：${data.detail || "未知错误"}`);
      }
    } catch (err) {
      addMessage("error", `上传网络错误：${err.message}`);
    }
  };
  reader.onerror = () => addMessage("error", `读取文件失败：${file.name}`);
  reader.readAsDataURL(file);
}

function addAttachmentBubble(filename, contentType, statusText, resultText, detail) {
  const node = el("div", "attachment-bubble");
  node.appendChild(el("span", "att-name", `📎 ${filename}`));
  node.appendChild(el("div", "att-meta", `类型 ${contentType} · ${statusText}`));
  if (resultText) {
    const preview = el("div", "att-meta", resultText.slice(0, 200) + (resultText.length > 200 ? "…" : ""));
    node.appendChild(preview);
  }
  if (detail && !resultText) {
    node.appendChild(el("div", "att-meta", detail));
  }
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
}

// ---------- M47 模型切换 ----------
async function loadModels() {
  const { status, data } = await api("/api/v1/models");
  if (status !== 200) return;
  els.modelSelect.innerHTML = "";
  state.availableModels = [];
  for (const m of data.models) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    els.modelSelect.appendChild(opt);
    state.availableModels.push(m);
  }
  state.model = data.current || null;
  els.modelSelect.value = state.model || "";
}

// ---------- M47 输入框增强：自动增高 + 快捷命令 ----------
function autoGrowInput() {
  const ta = els.messageInput;
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
}

function hideCmdSuggest() {
  els.cmdSuggest.hidden = true;
}

function showCmdSuggest() {
  const value = els.messageInput.value;
  // 仅当以 / 开头且当前行无空格/换行时提示（允许 /model 带参数后不再弹出）
  if (!value.startsWith("/") || value.includes(" ") || value.includes("\n")) {
    hideCmdSuggest();
    return;
  }
  const q = value.slice(1).toLowerCase();
  const items = COMMANDS.filter((c) => c.name.slice(1).startsWith(q));
  if (!items.length) {
    hideCmdSuggest();
    return;
  }
  els.cmdSuggest.innerHTML = "";
  for (const c of items) {
    const item = el("div", "cmd-suggest-item");
    item.appendChild(el("span", "cmd-name", c.name));
    item.appendChild(el("span", "cmd-desc", c.desc));
    item.onclick = () => {
      els.messageInput.value = c.name + (c.argHint ? " " : "");
      els.messageInput.focus();
      hideCmdSuggest();
      if (!c.argHint) sendMessage(); // 无需参数的命令点击即执行
    };
    els.cmdSuggest.appendChild(item);
  }
  els.cmdSuggest.hidden = false;
}

els.sendBtn.addEventListener("click", sendMessage);
els.newSessionBtn.addEventListener("click", newSession);
els.searchInput.addEventListener("input", renderSessions);
els.messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    // IME 组合态（中文输入法选词/中英文切换）回车不触发发送，避免误操作
    if (e.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    sendMessage();
  }
});
els.messageInput.addEventListener("input", () => {
  autoGrowInput();
  showCmdSuggest();
});
els.modelSelect.addEventListener("change", () => {
  state.model = els.modelSelect.value || null;
  addMessage("system", `已切换模型：${state.model}（下一条消息生效）。`);
});
els.cmdSuggest.addEventListener("mousedown", (e) => e.preventDefault()); // 保持输入框焦点
document.querySelectorAll(".cmd-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const def = COMMANDS.find((c) => c.name === chip.dataset.cmd);
    if (!def) return;
    els.messageInput.value = def.name + (def.argHint ? " " : "");
    els.messageInput.focus();
    hideCmdSuggest();
    if (!def.argHint) sendMessage(); // 无需参数的命令点击即执行
  });
});

els.uploadBtn.addEventListener("click", () => els.fileInput.click());
els.fileInput.addEventListener("change", () => {
  for (const f of els.fileInput.files) uploadFile(f);
  els.fileInput.value = "";
});
// 原生拖拽上传（M39）
["dragover", "drop"].forEach((evt) => {
  els.chatArea.addEventListener(evt, (e) => e.preventDefault());
});
els.chatArea.addEventListener("dragover", () => els.chatArea.classList.add("dragover"));
els.chatArea.addEventListener("dragleave", () => els.chatArea.classList.remove("dragover"));
els.chatArea.addEventListener("drop", (e) => {
  els.chatArea.classList.remove("dragover");
  for (const f of e.dataTransfer.files) uploadFile(f);
});

init();