async function loadSessions() {
  const { status, data } = await api("/api/v1/sessions");
  if (status !== 200) return;
  state.sessions = data.sessions || [];
  renderSessions();
}

async function loadSessionMessages(sessionId) {
  // D2: 首屏仅加载最近 HISTORY_PAGE_SIZE 条，更早按需加载
  const { status, data } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages?limit=${HISTORY_PAGE_SIZE}`
  );
  if (status !== 200) return;
  // P2-1: 白名单保留 tool 角色（工具调用回执），历史刷新后仍可见
  // P3-1: 保留 tool_call_id（回执侧配对键），供工具调用与回执配对
  state.messages = (data.messages || [])
    .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool")
    .map((m) => ({ role: m.role, content: m.content, note: null, reasoningContent: m.reasoning_content || null, toolCallId: m.tool_call_id || null }));
  state.hasMoreHistory = !!data.has_more;
  state.loadedHistoryCount = (data.messages || []).length;
  renderMessages();
}

async function loadEarlierHistory() {
  // D2: 按需加载更早历史（offset = 已加载条数），追加到顶部
  if (!state.currentSessionId) return;
  const { status, data } = await api(
    `/api/v1/sessions/${encodeURIComponent(state.currentSessionId)}/messages?limit=${HISTORY_PAGE_SIZE}&offset=${state.loadedHistoryCount}`
  );
  if (status !== 200) {
    addMessage("error", "加载更早消息失败，可重试。");
    return;
  }
  const earlier = (data.messages || [])
    .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool")
    .map((m) => ({ role: m.role, content: m.content, note: null, toolCallId: m.tool_call_id || null }));
  state.messages = [...earlier, ...state.messages];
  state.hasMoreHistory = !!data.has_more;
  state.loadedHistoryCount += (data.messages || []).length;
  renderMessages(false); // 追加到顶部，不滚动到底部
}

function renderLoadMoreButton() {
  // D2: 消息列表顶部提示"加载更早"/"已到最早"
  if (state.hasMoreHistory) {
    const btn = el("button", "load-more-btn", "↑ 加载更早消息");
    btn.type = "button";
    btn.onclick = () => loadEarlierHistory();
    els.messages.insertBefore(btn, els.messages.firstChild);
  } else if (state.loadedHistoryCount > 0 && state.messages.length >= state.loadedHistoryCount) {
    const hint = el("div", "history-hint", "已到最早消息");
    els.messages.insertBefore(hint, els.messages.firstChild);
  }
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
  setSidebarOpen(false); // P4-2: 窄屏选择会话后自动收起抽屉
}

function newSession() {
  state.currentSessionId = null;
  state.messages = [];
  renderMessages();
  renderSessions();
  els.messageInput.focus();
  setSidebarOpen(false); // P4-2: 窄屏新建会话后自动收起抽屉
}

async function deleteSession(sessionId) {
  if (!window.confirm("删除为不可逆操作，确认删除该会话？")) return; // 二次确认（对齐 confirm=true）
  const { status, data } = await api(
    `/api/v1/sessions/${encodeURIComponent(sessionId)}?confirm=true`,
    { method: "DELETE" }
  );
  if (status === 200) {
    // P3-1: 删除会话时清理对应声明暂存（无陈旧残留）
    state.declarationIndex.delete(sessionId);
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
