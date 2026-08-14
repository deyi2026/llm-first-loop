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
  initResponsive(); // P4-2: 移动端响应式初始化（侧栏抽屉 + 视口兜底）
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
