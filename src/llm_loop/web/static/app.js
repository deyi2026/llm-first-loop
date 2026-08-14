"use strict";


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

