// LLM-First Loop Web 聊天界面（M37，静态原生 JS，无框架）
// 消费 M36 API：POST /api/v1/chat + GET /api/v1/sessions + DELETE /api/v1/sessions/{id}?confirm=true

"use strict";

const state = {
  currentSessionId: null,
  messages: [],
  sessions: [],
  attachments: [], // M39 上传附件上下文（发送时作为 user 消息前缀注入）
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
};

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

// ---------- 消息渲染 ----------
function renderMessages() {
  els.messages.innerHTML = "";
  for (const msg of state.messages) {
    const node = document.createElement("div");
    node.className = "message " + msg.role;
    if (msg.role === "assistant") {
      // AI 回答：MD 渲染（经 sanitize）；渲染失败降级纯文本（不空白不伪造）
      const html = renderMarkdown(msg.content);
      if (html !== null) {
        node.innerHTML = html;
      } else {
        node.textContent = msg.content;
      }
      // 复制按钮（M39）：复制 final_answer 原文纯文本，成功"已复制"/失败如实
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
    } else {
      // user/error：纯文本如实回显（user 不渲染 MD，error 原样提示）
      node.textContent = msg.content;
      els.messages.appendChild(node);
      if (msg.note) {
        node.appendChild(el("span", "msg-note", msg.note));
      }
    }
  }
  els.messages.scrollTop = els.messages.scrollHeight;
}

function addMessage(role, content, note) {
  state.messages.push({ role, content, note });
  renderMessages();
}

// ---------- 发送消息 ----------
async function sendMessage() {
  const text = els.messageInput.value.trim();
  if (!text) return; // 空消息前端校验
  els.messageInput.value = "";
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
    const { status, data } = await api("/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    loading.remove();

    if (status === 200) {
      state.currentSessionId = data.session_id;
      const note = [];
      if (data.truncated) note.push("（回答被截断）");
      if (data.verification_note) note.push(data.verification_note);
      addMessage("assistant", data.final_answer, note.join("\n") || null);
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
  state.messages = (data.messages || [])
    .filter((m) => m.role === "user" || m.role === "assistant")
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
    const delBtn = el("button", "session-del", "✕");
    delBtn.title = "删除会话";
    delBtn.onclick = (e) => {
      e.stopPropagation();
      deleteSession(s.session_id);
    };
    item.appendChild(delBtn);
    const title = el("div", "session-title", s.title || "未命名");
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
  await loadSessions();
  // 刷新后自动选中最近会话并恢复其历史消息（无会话则保持空白等待新建）
  const latest = state.sessions[0];
  if (latest) {
    selectSession(latest.session_id);
  }
}

// ---------- M39 命令处理（纯前端状态操作，不调 API） ----------
function handleCommand(cmd) {
  const parts = cmd.trim().split(/\s+/);
  const name = (parts[0] || "").toLowerCase();
  if (name === "/new") {
    newSession();
    addMessage("system", "已新建会话。");
  } else if (name === "/clear") {
    state.messages = [];
    renderMessages();
    addMessage("system", "对话区已清空（会话保留）。");
  } else if (name === "/help") {
    addMessage("system", "可用命令：\n/new 新建会话\n/clear 清空对话区（不删会话）\n/help 帮助\n其余以 / 开头的输入视为未知命令。");
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

els.sendBtn.addEventListener("click", sendMessage);
els.newSessionBtn.addEventListener("click", newSession);
els.searchInput.addEventListener("input", renderSessions);
els.messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
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