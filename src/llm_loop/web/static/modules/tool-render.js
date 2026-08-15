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

function renderToolCalls(toolCalls, container, missNote) {
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
    // P3-1: 未配对声明如实标注（仅历史视图回执数据已加载时，避免将"未加载"误报为"无回执"）
    if (missNote) item.appendChild(el("span", "tool-pair-miss-note", "（无对应回执）"));
    detail.appendChild(item);
  }
  chain.appendChild(toggle);
  chain.appendChild(detail);
  container.insertBefore(chain, container.firstChild);
}

function parseToolResultStatus(content) {
  // P3-1: 回执状态判定纯函数（自 renderToolMessage 拆出，配对卡片与独立回执共用）
  const s = String(content || "");
  const m = s.match(/^\[([^\]]+)\]/);
  const statusText = m ? m[1] : "";
  const isError = /error|failure|失败|参数错误|安全硬阻断|程序异常/i.test(statusText)
    || /^\[安全硬阻断\]/.test(s) || /^\[程序异常\]/.test(s);
  const summary = `${isError ? "⚠️" : "🔧"} ${statusText || "工具回执"}`;
  return { statusText, isError, summary };
}

function renderArchiveButton(container, toolCallId, sessionId) {
  // P3-1: M52 分层截断"查看完整原文"按钮（自 renderToolMessage 拆出，配对卡片与独立回执共用）
  // 仅 toolCallId/sessionId 为合法非空字符串时构建；否则返回 null（fail-open）
  if (typeof toolCallId !== "string" || !toolCallId.length) return null;
  if (typeof sessionId !== "string" || !sessionId.length) return null;
  const btn = el("button", "tool-call-full-btn", "📄 查看完整原文");
  btn.type = "button";
  btn.onclick = async () => {
    btn.disabled = true;
    btn.textContent = "⏳ 加载中…";
    try {
      const resp = await fetch(`/api/v1/sessions/${sessionId}/archive/${toolCallId}`);
      const data = await resp.json();
      if (resp.ok) {
        container.appendChild(el("div", "tool-call-detail-text tool-call-full-text",
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
  return btn;
}

function buildToolPairIndex(messages, declIndex) {
  // P3-1: 构建"调用声明 ↔ 工具回执"配对索引（纯函数，无 DOM 依赖，O(N)）
  // id 字符串精确匹配，顺序无关、同 id 归并；非法 id（null/空串/非字符串）不参与配对
  const decls = new Map();
  for (const msg of messages) {
    if (msg && msg.role === "assistant" && Array.isArray(msg.toolCalls)) {
      for (const tc of msg.toolCalls) {
        if (tc && typeof tc.id === "string" && tc.id.length > 0 && !decls.has(tc.id)) {
          decls.set(tc.id, { id: tc.id, name: tc.name || "tool", arguments: tc.arguments });
        }
      }
    }
  }
  if (declIndex && typeof declIndex.forEach === "function") {
    declIndex.forEach((info, id) => {
      if (!decls.has(id)) decls.set(id, info);
    });
  }
  const results = new Map();
  for (const msg of messages) {
    if (msg && msg.role === "tool" && typeof msg.toolCallId === "string" && msg.toolCallId.length > 0) {
      results.set(msg.toolCallId, msg);
    }
  }
  const hasToolResults = results.size > 0;
  const pairs = [];
  const pairedIds = new Set();
  decls.forEach((decl, id) => {
    if (results.has(id)) {
      pairs.push({ id, decl, resultMsg: results.get(id) });
      pairedIds.add(id);
    }
  });
  const unpairedResults = [];
  results.forEach((msg, id) => {
    if (!pairedIds.has(id)) unpairedResults.push({ id, msg });
  });
  const unpairedDecls = [];
  decls.forEach((decl, id) => {
    if (!pairedIds.has(id)) unpairedDecls.push({ id, decl });
  });
  return { pairs, pairedIds, unpairedResults, unpairedDecls, hasToolResults };
}

function renderToolMessage(msg, container, missNote) {
  // 历史 tool 角色消息 → 折叠回执（解析 [状态: xxx] 前缀作为摘要）
  // P3-1: 状态判定与 M52 取档复用拆出的 parseToolResultStatus / renderArchiveButton
  const chain = el("div", "tool-call-chain");
  const content = String(msg.content || "");
  const st = parseToolResultStatus(content);
  const toggle = el("button", "tool-call-toggle" + (st.isError ? " tool-call-toggle-error" : ""), `${st.summary} ▸`);
  toggle.type = "button";
  const detail = el("div", "tool-call-detail");
  detail.hidden = true;
  toggle.onclick = () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = `${st.summary} ${detail.hidden ? "▸" : "▾"}`;
  };
  detail.appendChild(el("div", "tool-call-detail-text", content));
  // P3-1: 孤儿回执如实标注（id 合法但无声明匹配）
  if (missNote) detail.appendChild(el("span", "tool-pair-miss-note", `（${missNote}）`));
  // M52: 分层截断/已归档 → "查看完整原文"（按 tool_call_id 精确取档案，失败如实提示）
  const layered = content.includes("[工具输出已分层]") || content.includes("已另存至压缩档案");
  if (layered) {
    const btn = renderArchiveButton(detail, msg.tool_call_id, state.currentSessionId);
    if (btn) chain.appendChild(btn);
  }
  chain.appendChild(toggle);
  chain.appendChild(detail);
  container.appendChild(chain);
}

function renderToolPairCard(decl, resultMsg) {
  // P3-1: 渲染"调用→回执"配对卡片（tool 消息位置，单一折叠单元，调用侧→箭头→回执侧）
  // 文本经 textContent 构建；name/arguments 额外 sanitizeHtml 纵深防御；异常返回 null（fail-open）
  try {
    const card = el("div", "tool-pair-card");
    const content = String((resultMsg && resultMsg.content) || "");
    const st = parseToolResultStatus(content);
    const toolName = typeof decl.name === "string" && decl.name.length ? decl.name : "tool";
    const safeName = sanitizeHtml(toolName) || toolName;
    const toggle = el("button", "tool-pair-toggle" + (st.isError ? " tool-pair-toggle-error" : ""),
      `${st.isError ? "⚠️" : "🔧"} ${safeName} ▸`);
    toggle.type = "button";
    const body = el("div", "tool-pair-body");
    body.hidden = true;
    toggle.onclick = () => {
      body.hidden = !body.hidden;
      toggle.textContent = `${st.isError ? "⚠️" : "🔧"} ${safeName} ${body.hidden ? "▸" : "▾"}`;
      // REQ-P3-1-10: 展开时底部态滚动跟随（用户上滚则暂停，不打断阅读）
      if (!body.hidden && isMessagesAtBottom()) {
        els.messages.scrollTop = els.messages.scrollHeight;
      }
    };
    const call = el("div", "tool-pair-call");
    call.appendChild(el("span", "tool-call-name", safeName));
    const argsText = fmtToolArgs(decl.arguments);
    if (argsText) {
      call.appendChild(el("div", "tool-call-detail-text", `参数: ${sanitizeHtml(argsText) || argsText}`));
    }
    body.appendChild(call);
    body.appendChild(el("div", "tool-pair-arrow", "→"));
    const result = el("div", "tool-pair-result");
    result.appendChild(el("div", "tool-call-detail-text", content));
    const layered = content.includes("[工具输出已分层]") || content.includes("已另存至压缩档案");
    if (layered) {
      const btn = renderArchiveButton(result, resultMsg.toolCallId, state.currentSessionId);
      if (btn) result.appendChild(btn);
    }
    body.appendChild(result);
    card.appendChild(toggle);
    card.appendChild(body);
    return card;
  } catch (e) {
    console.error("renderToolPairCard 失败（fail-open，回退独立渲染）", e);
    return null;
  }
}

// ---------- P1-1 思考过程渲染 ----------
function renderReasoningBlock(reasoning, parentNode) {
  // 思考展示区：默认折叠 + 点击展开 + 样式区分；插入 parentNode 正文前方
  // 返回 { block, body, setReasoning }：setReasoning 供流式渐进/done 覆盖更新
  // 折叠态仅显示标题提示不渲染完整 DOM（spec 4.1.2）；展开时 renderMarkdown + chunkLongContent
  const block = el("div", "reasoning-block");
  const toggle = el("button", "reasoning-toggle", "💭 思考过程 ▸");
  toggle.type = "button";
  const body = el("div", "reasoning-body");
  body.hidden = true;
  let expanded = false;
  let currentText = "";
  const renderFull = () => {
    const html = renderMarkdown(currentText);
    if (html !== null) {
      body.innerHTML = html;
    } else {
      body.textContent = currentText;
    }
    chunkLongContent(body);
  };
  const setReasoning = (text) => {
    currentText = String(text || "");
    if (expanded) {
      renderFull();
    } else {
      toggle.textContent = `💭 思考过程（${currentText.length} 字）▸`;
    }
  };
  toggle.onclick = () => {
    expanded = !expanded;
    body.hidden = !expanded;
    if (expanded) {
      renderFull();
      toggle.textContent = "💭 思考过程 ▾";
    } else {
      toggle.textContent = `💭 思考过程（${currentText.length} 字）▸`;
    }
  };
  block.appendChild(toggle);
  block.appendChild(body);
  parentNode.insertBefore(block, parentNode.firstChild);
  setReasoning(reasoning);
  return { block, body, setReasoning };
}

function renderToolRoundProgress(parentNode) {
  // P2-1: 工具调用进展占位区（流式期间即时呈现，done 后收敛移除）
  // 返回 { block, setProgress }：setProgress(toolRounds) 供流式渐进更新计数器
  try {
    const block = el("div", "tool-round-progress");
    const counter = el("div", "tool-round-counter");
    block.appendChild(counter);
    parentNode.insertBefore(block, parentNode.firstChild);
    const setProgress = (toolRounds) => {
      const n = toolRounds.length;
      const last = toolRounds[n - 1];
      const name = last && last.tool_name ? sanitizeHtml(last.tool_name) : "工具";
      counter.textContent = `🔧 工具调用 ${n} 次（正在调用 ${name}…）`;
    };
    return { block, setProgress };
  } catch (e) {
    console.error("renderToolRoundProgress 失败（fail-open）", e);
    return { block: null, setProgress: () => {} };
  }
}

// ---------- 消息渲染 ----------
