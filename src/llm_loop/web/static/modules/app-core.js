function addMessage(role, content, note, toolCalls, reasoningContent) {
  const m = { role, content, note, reasoningContent: reasoningContent || null, toolRounds: null };
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
    state.retryRequest = body; // D2 断流重试：保存请求体供重试复用
    await runStreamChat(body, loading);
  } catch (err) {
    loading.remove();
    addMessage("error", `网络错误：${err.message}`);
  } finally {
    els.sendBtn.disabled = false;
    els.messageInput.focus();
  }

  loadSessions(); // 刷新侧栏（会话可能新建/更新）
}

// ---------- P4-2 移动端响应式（窄屏抽屉 + 视口兜底，fail-open 降级桌面布局） ----------
