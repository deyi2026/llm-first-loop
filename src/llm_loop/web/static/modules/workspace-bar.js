// EVO-20260923 工作区管理条：注册表曾被动积累临时目录垃圾（评测/probe/调试
// cwd 被自动注册）。根治配套：运行时守卫拒绝临时 cwd 自动注册 + 本 UI 提供
// 显式入口。后端 M36 面：GET/POST /api/v1/workspaces、POST .../switch、
// DELETE .../{id}（当前工作区不可注销；注销不删会话数据，可重新打开）。

async function loadWorkspaces() {
  const { status, data } = await api("/api/v1/workspaces");
  if (status !== 200) return;
  state.workspaces = data.workspaces || [];
  state.currentWorkspace = data.current || "";
  renderWorkspaceBar();
}

function _wsLabel(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts[parts.length - 1] || String(path || "(未命名)");
}

function renderWorkspaceBar() {
  const sel = els.workspaceSelect;
  sel.innerHTML = "";
  const list = state.workspaces || [];
  for (const w of list) {
    const opt = document.createElement("option");
    opt.value = w.id;
    opt.textContent = _wsLabel(w.path);
    opt.title = w.path;
    opt.selected = w.id === state.currentWorkspace;
    sel.appendChild(opt);
  }
  if (!list.length) {
    const opt = document.createElement("option");
    opt.textContent = "无工作区";
    opt.value = "";
    sel.appendChild(opt);
  }
  sel.disabled = !list.length;
  // 后端约束同源：当前工作区不可注销；选中当前项时禁用注销按钮
  els.workspaceDelBtn.disabled = !list.length || sel.value === state.currentWorkspace;
}

function _resetConversationView() {
  state.currentSessionId = null;
  state.messages = [];
  state.hasMoreHistory = false;
  state.loadedHistoryCount = 0;
  renderMessages();
}

async function switchWorkspace(wsId) {
  if (!wsId || wsId === state.currentWorkspace) return;
  const { status, data } = await api("/api/v1/workspaces/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: wsId }),
  });
  if (status !== 200) {
    addMessage("error", `切换工作区失败：${(data && (data.detail || data.error)) || status}`);
    renderWorkspaceBar(); // 回滚选择框到当前工作区
    return;
  }
  state.currentWorkspace = wsId;
  _resetConversationView();
  addMessage("system", `已切换工作区：${data.path || ""}`);
  await loadSessions();
  renderWorkspaceBar();
}

async function registerWorkspaceByPath() {
  const raw = window.prompt("输入要打开的目录绝对路径：", "");
  const path = (raw || "").trim();
  if (!path) return;
  const { status, data } = await api("/api/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (status !== 200) {
    addMessage("error", `打开工作区失败：${(data && (data.detail || data.error)) || status}`);
    return;
  }
  state.currentWorkspace = data.id || "";
  _resetConversationView();
  addMessage("system", `已打开工作区：${data.path || path}`);
  await loadSessions();
  await loadWorkspaces();
}

async function removeWorkspace() {
  const wsId = els.workspaceSelect.value;
  if (!wsId || wsId === state.currentWorkspace) return;
  const ws = (state.workspaces || []).find((w) => w.id === wsId);
  const label = ws ? ws.path : wsId;
  if (!window.confirm(`注销工作区？\n${label}\n\n会话数据保留，之后可重新打开该目录。`)) {
    renderWorkspaceBar();
    return;
  }
  const { status, data } = await api(
    `/api/v1/workspaces/${encodeURIComponent(wsId)}`,
    { method: "DELETE" }
  );
  if (status !== 200) {
    addMessage("error", `注销失败：${(data && (data.detail || data.error)) || status}`);
    return;
  }
  addMessage("system", `已注销工作区：${label}`);
  await loadWorkspaces();
}

els.workspaceSelect.addEventListener("change", () => switchWorkspace(els.workspaceSelect.value));
els.workspaceAddBtn.addEventListener("click", registerWorkspaceByPath);
els.workspaceDelBtn.addEventListener("click", removeWorkspace);
