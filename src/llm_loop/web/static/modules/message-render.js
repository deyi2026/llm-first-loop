function renderMessages(scrollToBottom = true) {
  els.messages.innerHTML = "";
  // P3-1: 构建配对索引（每次渲染基于当前数据源重建，无陈旧残留；异常 fail-open 空结构）
  let pairIndex = null;
  try {
    pairIndex = buildToolPairIndex(
      state.messages,
      state.declarationIndex.get(state.currentSessionId) || null
    );
  } catch (e) {
    console.error("buildToolPairIndex 失败（fail-open，回退既有渲染）", e);
  }
  const hasPairIndex = pairIndex && pairIndex.pairedIds && pairIndex.pairedIds.size > 0;
  for (const msg of state.messages) {
    const node = document.createElement("div");
    node.className = "message " + msg.role;
    // M52: 架构事件/程序异常消息醒目（红色左边框，不混入普通消息流）
    if (msg.role === "assistant" && /\[(架构上报|程序异常|安全硬阻断)\]/.test(String(msg.content || ""))) {
      node.classList.add("message-alert");
    }
    if (msg.role === "tool") {
      // P2-1: 历史 tool 角色消息渲染为折叠回执
      // P3-1: 回执 id 命中配对 → 配对卡片承载于此位置；否则独立渲染
      const wrap = document.createElement("div");
      wrap.className = "message-wrap";
      wrap.appendChild(node);
      const paired = hasPairIndex
        && typeof msg.toolCallId === "string" && msg.toolCallId.length > 0
        && pairIndex.pairedIds.has(msg.toolCallId);
      if (paired) {
        const pairDecl = pairIndex.pairs.find((p) => p.id === msg.toolCallId);
        const card = pairDecl ? renderToolPairCard(pairDecl.decl, msg) : null;
        if (card) {
          wrap.appendChild(card);
        } else {
          renderToolMessage(msg, wrap, null); // fail-open: 卡片异常回退独立渲染
        }
      } else {
        const missNote = (typeof msg.toolCallId === "string" && msg.toolCallId.length > 0)
          ? "未找到对应调用" : null;
        renderToolMessage(msg, wrap, missNote);
      }
      els.messages.appendChild(wrap);
      continue;
    }
    if (msg.role === "assistant") {
      // AI 回答：MD 渲染（经 sanitize）；渲染失败降级纯文本（不空白不伪造）
      // P2-1: AI 回复内容前插入折叠工具调用链（若有）
      // P3-1: 过滤已配对声明（配对卡片已在 tool 消息位置承载，不重复呈现）
      let unpairedCalls = null;
      if (Array.isArray(msg.toolCalls) && msg.toolCalls.length) {
        if (hasPairIndex) {
          unpairedCalls = msg.toolCalls.filter(
            (tc) => !(tc && typeof tc.id === "string" && tc.id.length > 0 && pairIndex.pairedIds.has(tc.id))
          );
        } else {
          unpairedCalls = msg.toolCalls;
        }
      }
      if (Array.isArray(unpairedCalls) && unpairedCalls.length) {
        // 历史视图回执已加载（hasToolResults=true）时对未配对声明如实标注"无对应回执"
        renderToolCalls(unpairedCalls, node, pairIndex && pairIndex.hasToolResults);
      }
      // P1-1: 思考区渲染（默认折叠，在正文前方；历史消息恢复）
      if (msg.reasoningContent) {
        renderReasoningBlock(msg.reasoningContent, node);
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
      // 渲染正文 + 后处理（代码块高亮 → 复制按钮 → 长内容折叠）
      const finalize = () => {
        // T3: 代码块语法高亮（renderMarkdown sanitize 之后、复制/折叠之前）
        highlightCodeBlocks(node);
        // 回复内命令框（代码块）右上角也提供复制按钮
        addCodeBlockCopyButtons(node);
        // 长内容分块（2026-08-15：不折叠；超阈值 pre → 顺序分段全量展示）
        chunkLongContent(node);
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
        highlightCodeBlocks(node);
        addCodeBlockCopyButtons(node);
        chunkLongContent(node);
      } else {
        node.textContent = msg.content;
        els.messages.appendChild(node);
      }
      if (msg.note) {
        node.appendChild(el("span", "msg-note", msg.note));
      }
    }
  }
  renderLoadMoreButton();
  if (scrollToBottom) els.messages.scrollTop = els.messages.scrollHeight;
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

// T3: 代码块语法高亮（自研简版，spec 5.3.1 D1 / design §2.1.3.3）
// 关键字/字符串/注释/数字四类 token，用 DOM API 构建 span（textContent + className），不注入 HTML（防 XSS）
// 无语言标识或高亮异常 → 保留纯文本等宽 + console.warn（fail-open，不空白不伪造）
const HIGHLIGHT_KEYWORDS = {
  python: ["def", "return", "if", "elif", "else", "for", "while", "import", "from", "as", "class", "try", "except", "finally", "with", "lambda", "pass", "break", "continue", "in", "is", "not", "and", "or", "None", "True", "False", "raise", "yield", "global", "nonlocal", "assert", "del", "print", "self"],
  js: ["function", "return", "if", "else", "for", "while", "const", "let", "var", "import", "export", "from", "class", "try", "catch", "finally", "new", "typeof", "instanceof", "in", "of", "null", "undefined", "true", "false", "async", "await", "throw", "break", "continue", "switch", "case", "default", "do", "this"],
  shell: ["if", "then", "else", "elif", "fi", "for", "while", "do", "done", "case", "esac", "function", "return", "echo", "export", "local", "readonly", "in", "source", "exit", "set", "unset"],
};

function normalizeLang(lang) {
  if (!lang) return "";
  if (["python", "py"].includes(lang)) return "python";
  if (["js", "javascript", "ts", "typescript"].includes(lang)) return "js";
  if (["shell", "bash", "sh", "zsh"].includes(lang)) return "shell";
  return lang;
}

function highlightCodeBlock(codeEl, lang) {
  const text = codeEl.textContent || "";
  if (!text) return;
  const keywords = HIGHLIGHT_KEYWORDS[lang];
  if (!keywords) {
    console.warn("代码高亮：未知语言，降级纯文本", lang);
    return;
  }
  try {
    const kwSet = new Set(keywords);
    const re = new RegExp(
      "(\"[^\"\\n]*\"|'[^'\\n]*'|`[^`\\n]*`)" + // 字符串
        "|(#[^\\n]*|\\/\\/[^\\n]*)" + // 注释
        "|(\\b\\d+\\.?\\d*\\b)" + // 数字
        "|(\\b[A-Za-z_][A-Za-z0-9_]*\\b)", // 标识符（关键字匹配）
      "g"
    );
    const frag = document.createDocumentFragment();
    let last = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) {
        frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      }
      const full = m[0];
      const str = m[1];
      const comment = m[2];
      const num = m[3];
      const ident = m[4];
      let cls = null;
      if (str !== undefined) cls = "code-str";
      else if (comment !== undefined) cls = "code-comment";
      else if (num !== undefined) cls = "code-num";
      else if (ident !== undefined && kwSet.has(ident)) cls = "code-kw";
      if (cls) {
        const span = document.createElement("span");
        span.className = cls;
        span.textContent = full;
        frag.appendChild(span);
      } else {
        frag.appendChild(document.createTextNode(full));
      }
      last = m.index + full.length;
    }
    if (last < text.length) {
      frag.appendChild(document.createTextNode(text.slice(last)));
    }
    codeEl.textContent = "";
    codeEl.appendChild(frag);
  } catch (err) {
    console.warn("代码高亮失败，降级纯文本:", err);
  }
}

function highlightCodeBlocks(container) {
  for (const code of container.querySelectorAll("pre code")) {
    const m = (code.className || "").match(/language-([\w-]+)/);
    const lang = normalizeLang(m ? m[1] : "");
    highlightCodeBlock(code, lang);
  }
}

// 长内容分块器（2026-08-15 用户需求：回复不折叠，过长分块输出；替代 spec 5.2.1 折叠方案）
// chunkLongContent：pre 行数 > LONG_LINE_THRESHOLD → 顺序拆为多段可见代码块（每段 ≤ 阈值行，
// 段首标注「第 i/N 段 · 共 X 行（自动分块，未折叠）」），无隐藏节点、无展开按钮；
// 消息体不再折叠（全量渲染）。分块异常 fail-open：保留原样 + console.error，不空白不伪造
function chunkLongContent(node) {
  try {
    for (const pre of [...node.querySelectorAll("pre")]) {
      if (pre.closest(".chunked-pre")) continue;
      const text = pre.textContent || "";
      const lines = text.split("\n");
      if (lines.length <= LONG_LINE_THRESHOLD) continue;
      const wrap = pre.parentElement;
      if (!wrap || wrap.dataset.chunked) continue;
      wrap.dataset.chunked = "1";
      // 保留语言标签以维持语法高亮（highlightCodeBlocks 已先跑，分段后逐段重高亮）
      const codeEl = pre.querySelector("code");
      const m = codeEl && /language-([\w-]+)/.exec(codeEl.className || "");
      const lang = m ? m[1] : "";
      const total = lines.length;
      const nChunks = Math.ceil(total / LONG_LINE_THRESHOLD);
      const container = el("div", "chunked-pre");
      for (let i = 0; i < nChunks; i++) {
        const partLines = lines.slice(i * LONG_LINE_THRESHOLD, (i + 1) * LONG_LINE_THRESHOLD);
        container.appendChild(
          el("div", "chunk-marker", "▸ 第 " + (i + 1) + "/" + nChunks + " 段 · 共 " + total + " 行（自动分块，未折叠）")
        );
        const p = el("pre", "");
        const c = el("code", lang ? "language-" + lang : "");
        c.textContent = partLines.join("\n");
        p.appendChild(c);
        highlightCodeBlock(c, lang);
        container.appendChild(p);
      }
      // 原 wrap（code-block-wrap，可能含复制按钮）整段替换为分段容器，再给每段补复制按钮
      wrap.parentElement.replaceChild(container, wrap);
      addCodeBlockCopyButtons(container);
    }
  } catch (err) {
    console.error("长内容分块失败（fail-open）:", err);
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

// T4 D1: 滚动跟随判定（底部检测，抗抖动阈值）
const SCROLL_FOLLOW_THRESHOLD = 4; // px
function isMessagesAtBottom() {
  const el = els.messages;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_FOLLOW_THRESHOLD;
}

// T2.7: 真流式消费（fetch + ReadableStream 解析 SSE，spec 5.2 规则 1）
// answer_delta 逐分片回调 onDelta；done 携带九字段；error 为终态（停止追加分片，不伪造 done）
// 读异常 = 网络中断（errorType:"network"）；SSE error 事件 = 引擎错误（errorType:"engine"）
// 非 2xx（404/413）= http 错误（errorType:"http"）；ReadableStream 不可用 → 降级非流式
