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
async function runStreamChat(body, loading) {
  let acc = "";
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
      addMessage("assistant", "", null, null);
      const wrap = els.messages.querySelector(".message-wrap:last-of-type");
      bodyNode = wrap ? wrap.querySelector(".answer-body") : null;
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
    if (streamed) {
      const last = state.messages[state.messages.length - 1];
      if (last && last.role === "assistant") {
        last.note = note;
      }
      renderMessages();
    } else {
      addMessage("error", note);
    }
    // 重试入口：保留已生成分片，重新发起请求
    const retryBtn = el("button", "retry-btn", "重试");
    retryBtn.type = "button";
    retryBtn.onclick = () => runStreamChat(state.retryRequest, null);
    els.messages.appendChild(retryBtn);
    els.messages.scrollTop = els.messages.scrollHeight;
  }
}

