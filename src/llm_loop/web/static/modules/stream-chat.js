async function streamChatRequest(body, onDelta, onReasoningDelta, onToolRound) {
  let resp;
  try {
    resp = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, data: null, errorType: "network", error: { detail: "连接中断，已保留已生成内容" } };
  }
  if (!resp.ok || !resp.body || typeof resp.body.getReader !== "function") {
    let data = null;
    try { data = await resp.json(); } catch { /* ignore */ }
    return { ok: false, status: resp.status, data, errorType: "http", error: data };
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneData = null;
  let errorData = null;
  let finished = false;
  while (!finished) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch {
      // 读异常 = 连接中断（区别于 SSE error 事件，不 throw 穿透）
      return { ok: false, status: 0, data: null, errorType: "network", error: { detail: "连接中断，已保留已生成内容" } };
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
      if (!dataLine) continue;
      let evt;
      try { evt = JSON.parse(dataLine.slice(6)); } catch { continue; }
      if (evt.type === "answer_delta") onDelta(evt.data && evt.data.data);
      else if (evt.type === "reasoning_delta") { if (onReasoningDelta) onReasoningDelta(evt.data && evt.data.data); }
      else if (evt.type === "tool_round") { if (onToolRound) onToolRound(evt.data); }
      else if (evt.type === "done") { doneData = evt.data; finished = true; break; }
      else if (evt.type === "error") { errorData = evt.data; finished = true; break; } // error 为终态（D3）
    }
  }
  if (doneData) return { ok: true, status: 200, data: doneData, error: null };
  if (errorData) return { ok: false, status: 200, data: null, errorType: "engine", error: errorData };
  return { ok: false, status: 200, data: null, errorType: "network", error: { detail: "连接中断，已保留已生成内容" } };
}

function buildAssistantNote(data) {
  const note = [];
  if (data.truncated) note.push("（回答被截断，建议新建会话或调整 prompt 继续）");
  if (data.verification_note) note.push(data.verification_note);
  if (data.model_used) {
    let footer = `—— ${data.model_used}`;
    if (data.tokens_in || data.tokens_out) {
      footer += ` · ${fmtTokens(data.tokens_in)}入/${fmtTokens(data.tokens_out)}出`;
    }
    note.push(footer);
  }
  return note.join("\n") || null;
}

// D1~D4: 真流式请求 + 渲染 + 结果处理（滚动跟随/断流重试/错误边界/空回答清理）
// 2026-08-17 续联：opts.resume=true 订阅已有后台 run（断线自动续收/刷新恢复），
// 复用最后一条 assistant 消息气泡（不新建），acc 初始取页面上已显示内容（防丢已生成分片）。
let resumeAttempts = 0; // 自动续联尝试次数（上限 2，防网络抖动递归风暴）
async function runStreamChat(body, loading, opts = {}) {
  const resume = !!opts.resume;
  let acc = "";
  if (resume) {
    const wrap = els.messages.querySelector(".message-wrap:last-of-type");
    const ans = wrap && wrap.querySelector(".answer-body");
    const last = state.messages[state.messages.length - 1];
    acc = ans ? ans.textContent : (last && last.role === "assistant" ? last.content || "" : "");
  }
  let accReasoning = "";
  let bodyNode = null;
  let reasoningBlock = null;
  let toolRoundBlock = null;
  let toolRounds = [];
  let streamed = false;
  const ensureStreamed = () => {
    if (!streamed) {
      streamed = true;
      if (loading) loading.remove();
      if (resume) {
        // resume：复用最后一条 assistant 消息气泡（断线续收/刷新恢复，不新建）
        const wrap = els.messages.querySelector(".message-wrap:last-of-type");
        const last = state.messages[state.messages.length - 1];
        if (wrap && last && last.role === "assistant") {
          bodyNode = wrap.querySelector(".answer-body");
        } else {
          addMessage("assistant", "", null, null);
          const w = els.messages.querySelector(".message-wrap:last-of-type");
          bodyNode = w ? w.querySelector(".answer-body") : null;
        }
      } else {
        addMessage("assistant", "", null, null);
        const wrap = els.messages.querySelector(".message-wrap:last-of-type");
        bodyNode = wrap ? wrap.querySelector(".answer-body") : null;
      }
    }
  };
  const result = await streamChatRequest(body, (delta) => {
    ensureStreamed();
    acc += delta;
    if (bodyNode) {
      const html = renderMarkdown(acc);
      bodyNode.innerHTML = html !== null ? html : acc;
      if (isMessagesAtBottom()) {
        // D1: 仅底部态跟随，用户上滚查看历史时暂停（不打断阅读）
        els.messages.scrollTop = els.messages.scrollHeight;
      }
    }
  }, (reasoningDelta) => {
    // P1-1: 流式思考分片渐进渲染（与正文并行互不阻塞，spec 4.1.1/5.1.1 规则 5）
    ensureStreamed();
    accReasoning += reasoningDelta;
    if (bodyNode && !reasoningBlock) {
      reasoningBlock = renderReasoningBlock(accReasoning, bodyNode);
    } else if (reasoningBlock) {
      reasoningBlock.setReasoning(accReasoning);
    }
    if (isMessagesAtBottom()) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
  }, (toolRound) => {
    // P2-1: 工具轮次进展渐进渲染（与正文/思考区并行互不阻塞，spec 4.1.1/5.1.1 规则 6）
    ensureStreamed();
    toolRounds.push(toolRound);
    if (bodyNode && !toolRoundBlock) {
      toolRoundBlock = renderToolRoundProgress(bodyNode);
    }
    if (toolRoundBlock) {
      toolRoundBlock.setProgress(toolRounds);
    }
    if (isMessagesAtBottom()) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
  });

  if (result.ok && result.data) {
    const data = result.data;
    resumeAttempts = 0; // 续联成功：重置计数
    state.currentSessionId = data.session_id;
    // P3-1: done 终态暂存声明侧事实（session_id 键控，合并写入不覆盖既有键，纯页面内存态）
    if (data.session_id && Array.isArray(data.tool_calls)) {
      let sessionDecls = state.declarationIndex.get(data.session_id);
      if (!sessionDecls) {
        sessionDecls = new Map();
        state.declarationIndex.set(data.session_id, sessionDecls);
      }
      for (const tc of data.tool_calls) {
        if (tc && typeof tc.id === "string" && tc.id.length > 0 && !sessionDecls.has(tc.id)) {
          sessionDecls.set(tc.id, { id: tc.id, name: tc.name || "tool", arguments: tc.arguments });
        }
      }
    }
    const finalText = (data.final_answer || "").trim();
    if (streamed) {
      const last = state.messages[state.messages.length - 1];
      if (last && last.role === "assistant") {
        if (finalText) {
          last.content = data.final_answer;
          if (Array.isArray(data.tool_calls) && data.tool_calls.length) last.toolCalls = data.tool_calls;
          last.note = buildAssistantNote(data);
          // P1-1: done 终态覆盖流式累积（终态一致，spec 5.1.1 规则 6a）
          last.reasoningContent = data.reasoning_content || (accReasoning || null);
        } else if (Array.isArray(data.tool_calls) && data.tool_calls.length) {
          // D4: 纯工具轮 → 保留工具链 + 占位，不伪造文字
          last.content = "";
          last.toolCalls = data.tool_calls;
          last.note = "（无文字回答）";
        } else {
          // D4: 空回答且无工具痕迹 → 移除空占位（不残留空气泡）
          state.messages.pop();
        }
      }
      renderMessages();
    } else if (resume) {
      // resume 无 delta 直接 done（run 已近完成）：更新最后一条 assistant 消息，不重复新建
      if (loading) loading.remove();
      const last = state.messages[state.messages.length - 1];
      if (last && last.role === "assistant") {
        last.content = finalText; // 终态一致：无条件覆盖（纯工具轮清空残留）
        if (data.reasoning_content) last.reasoningContent = data.reasoning_content;
        if (Array.isArray(data.tool_calls) && data.tool_calls.length) last.toolCalls = data.tool_calls;
        last.note = buildAssistantNote(data);
        renderMessages();
      } else {
        addMessage("assistant", finalText || "（无文字回答）", buildAssistantNote(data), data.tool_calls, data.reasoning_content || null);
      }
    } else {
      if (loading) loading.remove();
      if (finalText) {
        state.typewriterPending = true; // 降级：假流式打字机
        addMessage("assistant", data.final_answer, buildAssistantNote(data), data.tool_calls, data.reasoning_content || null);
      } else if (Array.isArray(data.tool_calls) && data.tool_calls.length) {
        addMessage("assistant", "", "（无文字回答）", data.tool_calls);
      } else {
        addMessage("error", "（无文字回答）");
      }
    }
    if (data.tokens_in || data.tokens_out) {
      state.pageTokensIn = (state.pageTokensIn || 0) + data.tokens_in;
      state.pageTokensOut = (state.pageTokensOut || 0) + data.tokens_out;
      renderTokenStats();
    }
  } else if (result.status === 404) {
    if (loading) loading.remove();
    addMessage("error", (result.data && result.data.detail) || "会话不存在，请新建会话。");
    state.currentSessionId = null;
  } else {
    // D2: 网络/引擎错误区分提示 + 可重试（不静默重连，fail-open ≠ fail-silent）
    if (loading) loading.remove();
    const isNetwork = result.errorType === "network";
    const detail = result.error && result.error.detail ? result.error.detail : "服务内部错误。";
    const note = `${isNetwork ? "" : "[程序异常] "}${detail}`;
    // 自动续联：网络中断 → resume 订阅续收（后台 run 继续执行；上限 2 次防递归风暴）
    if (isNetwork && state.retryRequest && state.retryRequest.session_id && resumeAttempts < 2) {
      resumeAttempts += 1;
      const rnote = document.createElement("div");
      rnote.className = "reconnect-note";
      rnote.textContent = `连接中断，正在自动重连…（${resumeAttempts}/2）`;
      els.messages.appendChild(rnote);
      els.messages.scrollTop = els.messages.scrollHeight;
      setTimeout(async () => {
        try { if (rnote.parentNode) rnote.parentNode.removeChild(rnote); } catch { /* ignore */ }
        // resume 请求体：同会话订阅已有 run（不提交新 run，message 占位不会被消费）
        await runStreamChat({ ...state.retryRequest, resume: true }, null, { resume: true });
      }, 1500);
      return;
    }
    if (streamed) {
      const last = state.messages[state.messages.length - 1];
      if (last && last.role === "assistant") {
        last.note = note;
      }
      renderMessages();
    } else {
      addMessage("error", note);
    }
    // EVO 后台 run：session_busy → 自动轮询状态，完成后刷新历史（用户无需手动刷新）
    if (result.error && result.error.error === "session_busy" && state.currentSessionId) {
      const sid = state.currentSessionId;
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`/api/v1/chat/stream/status?session_id=${encodeURIComponent(sid)}`);
          const st = await r.json();
          if (!st.running) {
            clearInterval(poll);
            if (typeof loadSessionMessages === "function") {
              await loadSessionMessages(sid); // 完成 → 加载最新历史（含完整结果）
            }
            addMessage("system", "该会话的生成已完成，可查看结果。");
          }
        } catch { /* 轮询失败忽略，下次再试 */ }
      }, 2000);
    }
    // 重试入口：保留已生成分片，重新发起请求
    const retryBtn = el("button", "retry-btn", "重试");
    retryBtn.type = "button";
    retryBtn.onclick = () => runStreamChat(state.retryRequest, null);
    els.messages.appendChild(retryBtn);
    els.messages.scrollTop = els.messages.scrollHeight;
  }
}

// 2026-08-17 刷新恢复：页面加载后检查当前会话是否有后台 run 进行中，
// 有则提示 + resume 订阅续收（done 终态覆盖完整结果，刷新不再丢进行中内容）。
// 无进行中 run → 静默返回（历史已由 loadSessionMessages 加载）。
async function checkResumeOnLoad() {
  const sid = state.currentSessionId;
  if (!sid) return;
  let st = null;
  try {
    const r = await fetch(`/api/v1/chat/stream/status?session_id=${encodeURIComponent(sid)}`);
    st = await r.json();
  } catch { /* fail-open：状态不可达时不阻塞首屏 */ return; }
  if (!st || !st.running) return;
  const loading = el("div", "message assistant loading", "该会话正在生成中，正在恢复…");
  els.messages.appendChild(loading);
  els.messages.scrollTop = els.messages.scrollHeight;
  try {
    // resume 订阅：message 传占位（后端 resume 分支不消费 message）
    await runStreamChat({ message: "（恢复连接）", session_id: sid, resume: true }, loading, { resume: true });
  } catch {
    try { if (loading.parentNode) loading.parentNode.removeChild(loading); } catch { /* ignore */ }
  }
}

