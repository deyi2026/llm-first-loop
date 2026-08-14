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

// ---------- P4-3 数学公式渲染（KaTeX 本地分发 + 占位符净化注入） ----------
// 管线：extractMath（公式移出正文为占位符）→ marked + sanitize（净化先于渲染）→
//       restoreMathInHtml（净化后经 DOM API 注入 KaTeX 元素，白名单一字不改）
const MATH_PLACEHOLDER_PREFIX = "@@MATH_";
const MATH_FORMULA_MAX = 50;          // 单条消息公式渲染上限
const MATH_RENDER_BUDGET_MS = 200;    // 单条消息公式渲染耗时预算（ms）
const MATH_KATEX_JS = "/static/katex/katex.min.js";   // 本地分发，无 CDN
const MATH_KATEX_CSS = "/static/katex/katex.min.css"; // 本地分发，无 CDN
let mathEngineState = { promise: null, available: false }; // 模块级按需加载状态（非 state 数据）

function extractMath(src) {
  // 公式识别器（O(n) 单遍扫描）：块级定界符优先（$$…$$ / \[…\]），行内（$…$ / \(…\)）
  // 代码区豁免（围栏/缩进/行内代码）+ 转义豁免（\ 前缀的定界符不识别）
  // 未识别到公式时 text 恒等于 src、formulas 为空（零行为影响）
  const text = String(src || "");
  const formulas = [];
  if (!text) return { text, formulas };
  const out = [];
  let i = 0;
  let fenced = false;      // ``` 围栏代码区
  let fenceChar = "";
  let blockBuf = null;     // 块级公式内容暂存（闭合后生成占位符，不进入 out）
  const hasUnclosedBlock = { display: false, start: -1, delim: "" }; // 未闭合块级定界符追踪
  while (i < text.length) {
    const ch = text[i];
    const two = text.slice(i, i + 2);
    // 围栏代码区状态机（``` 或 ~~~）
    if (!fenced && (two === "``" || two === "~~") && text[i + 2] === ch) {
      const lineStart = out.length === 0 || out[out.length - 1] === "\n";
      if (lineStart || text[i - 1] === "\n" || i === 0) {
        const lineEnd = text.indexOf("\n", i + 3);
        if (lineEnd === -1) { fenced = true; fenceChar = ch; out.push(text.slice(i)); break; }
        const line = text.slice(i, lineEnd);
        const isClosing = line.trim().slice(0, 3) === ch + ch + ch;
        if (!isClosing) { fenced = true; fenceChar = ch; out.push(text.slice(i, lineEnd)); i = lineEnd; continue; }
      }
    }
    if (fenced) {
      const closeIdx = text.indexOf("\n" + fenceChar + fenceChar + fenceChar, i);
      if (closeIdx === -1) { out.push(text.slice(i)); break; }
      out.push(text.slice(i, closeIdx + 4));
      i = closeIdx + 4;
      fenced = false;
      continue;
    }
    // 块级公式内部：内容一律暂存（不进入 out），仅识别闭合定界符
    if (hasUnclosedBlock.display) {
      const closesNow =
        (hasUnclosedBlock.delim === "$$" && two === "$$") ||
        (hasUnclosedBlock.delim === "\\[" && (two === "\\]" || two === "\\["));
      if (closesNow) {
        const idx = formulas.length;
        const tex = blockBuf ? blockBuf.join("") : "";
        formulas.push({ idx, tex, display: true });
        out.push(`${MATH_PLACEHOLDER_PREFIX}${idx}@@`);
        hasUnclosedBlock.display = false;
        blockBuf = null;
        i += 2;
        continue;
      }
      blockBuf.push(ch);
      i += 1;
      continue;
    }
    // 缩进代码区（行首 4 空格及以上）与行内代码区（`…`）豁免
    const lineStartPos = text.lastIndexOf("\n", i - 1) + 1;
    if (i === lineStartPos && text[i] === " " && text.slice(i, i + 4) === "    ") {
      let j = i;
      while (j < text.length && text[j] !== "\n") j += 1;
      out.push(text.slice(i, j));
      i = j;
      continue;
    }
    if (ch === "`") {
      let j = i;
      while (j < text.length && text[j] === "`") j += 1;
      const backtickLen = j - i;
      const end = text.indexOf("`".repeat(backtickLen), j);
      if (end === -1) { out.push(text.slice(i)); break; }
      out.push(text.slice(i, end + backtickLen));
      i = end + backtickLen;
      continue;
    }
    // 转义豁免：定界符前有奇数个反斜杠则跳过（\$ / \( / \[）
    const bsCount = (() => { let n = 0; let k = i - 1; while (k >= 0 && text[k] === "\\") { n += 1; k -= 1; } return n; })();
    if (bsCount % 2 === 1) { out.push(ch); i += 1; continue; }
    // 块级定界符开始（块级优先于行内 $，避免 $$x$$ 被误拆）
    if (two === "$$") {
      hasUnclosedBlock.display = true; hasUnclosedBlock.start = i; hasUnclosedBlock.delim = "$$";
      blockBuf = [];
      i += 2;
      continue;
    }
    if (two === "\\[") {
      hasUnclosedBlock.display = true; hasUnclosedBlock.start = i; hasUnclosedBlock.delim = "\\[";
      blockBuf = [];
      i += 2;
      continue;
    }
    // 行内定界符：$ 与 \(
    if (ch === "$" && !(two === "$$")) {
      const end = text.indexOf("$", i + 1);
      if (end === -1) { out.push(ch); i += 1; continue; } // 未闭合 → 原文保留（fail-open）
      const inner = text.slice(i + 1, end);
      if (inner.includes("\n")) { out.push(ch); i += 1; continue; } // 行内公式不跨行
      const idx = formulas.length;
      formulas.push({ idx, tex: inner, display: false });
      out.push(`${MATH_PLACEHOLDER_PREFIX}${idx}@@`);
      i = end + 1;
      continue;
    }
    if (two === "\\(" ) {
      const end = text.indexOf("\\)", i + 2);
      if (end === -1) { out.push(ch); i += 1; continue; }
      const inner = text.slice(i + 2, end);
      const idx = formulas.length;
      formulas.push({ idx, tex: inner, display: false });
      out.push(`${MATH_PLACEHOLDER_PREFIX}${idx}@@`);
      i = end + 2;
      continue;
    }
    out.push(ch);
    i += 1;
  }
  if (hasUnclosedBlock.display) {
    console.warn("公式定界符未闭合（fail-open，按原文呈现）", hasUnclosedBlock.delim);
  }
  return { text: out.join(""), formulas };
}

function loadMathEngine() {
  // 按需加载 KaTeX（本地资源，首屏零负担；失败 resolve(false)，available=false 后不重试）
  if (mathEngineState.promise) return mathEngineState.promise;
  mathEngineState.promise = new Promise((resolve) => {
    try {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = MATH_KATEX_CSS;
      document.head.appendChild(link);
      const script = document.createElement("script");
      script.src = MATH_KATEX_JS;
      script.onload = () => {
        mathEngineState.available = typeof window.katex !== "undefined";
        if (!mathEngineState.available) console.error("公式引擎不可用（fail-open）: katex 未定义");
        resolve(mathEngineState.available);
      };
      script.onerror = () => {
        mathEngineState.available = false;
        console.error("公式引擎不可用（fail-open）: 资源加载失败");
        resolve(false);
      };
      document.head.appendChild(script);
    } catch (err) {
      mathEngineState.available = false;
      console.error("公式引擎不可用（fail-open）:", err);
      resolve(false);
    }
  });
  return mathEngineState.promise;
}

function renderMathElement(tex, displayMode) {
  // 单公式渲染：throwOnError=true 使非法语法抛错并降级原文；trust=false 禁可执行协议
  const placeholder = el("span", "math-placeholder");
  const fallback = document.createTextNode(String(tex || ""));
  loadMathEngine().then((ok) => {
    if (!ok) {
      console.error("公式引擎不可用（fail-open），按原文显示公式");
      if (placeholder.parentNode) placeholder.parentNode.replaceChild(fallback, placeholder);
      else placeholder.appendChild(fallback);
      return;
    }
    try {
      window.katex.render(String(tex || ""), placeholder, {
        displayMode: Boolean(displayMode),
        throwOnError: true,
        trust: false,
      });
    } catch (err) {
      console.error("公式渲染失败（fail-open），按原文显示公式:", err);
      if (placeholder.parentNode) placeholder.parentNode.replaceChild(fallback, placeholder);
      else placeholder.appendChild(fallback);
    }
  });
  return placeholder;
}

function restoreMathInHtml(html, formulas) {
  // 净化后注入：无占位符短路直返（零开销）；含占位符时经 DOMParser 深度遍历文本节点，
  // 逐条调 renderMathElement 原位注入 KaTeX 元素（DOM API，不经 sanitize 白名单）
  if (!html || typeof html !== "string" || !html.includes(MATH_PLACEHOLDER_PREFIX)) return html;
  if (typeof DOMParser === "undefined" || !Array.isArray(formulas) || !formulas.length) return html;
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const byIdx = new Map(formulas.map((f) => [f.idx, f]));
    let rendered = 0;
    const startTs = Date.now();
    const walk = (node) => {
      for (const child of [...node.childNodes]) {
        if (child.nodeType === 3 && child.nodeValue && child.nodeValue.includes(MATH_PLACEHOLDER_PREFIX)) {
          const frag = document.createDocumentFragment();
          let rest = child.nodeValue;
          while (rest) {
            const idxMatch = rest.match(new RegExp(MATH_PLACEHOLDER_PREFIX + "(\\d+)@@"));
            if (!idxMatch) { frag.appendChild(document.createTextNode(rest)); break; }
            const prefix = rest.slice(0, idxMatch.index);
            if (prefix) frag.appendChild(document.createTextNode(prefix));
            const idx = Number(idxMatch[1]);
            const f = byIdx.get(idx);
            if (f && rendered < MATH_FORMULA_MAX && Date.now() - startTs < MATH_RENDER_BUDGET_MS) {
              frag.appendChild(renderMathElement(f.tex, f.display));
              rendered += 1;
            } else {
              if (f) console.warn("公式渲染超限（fail-open，按原文显示）", idx);
              frag.appendChild(document.createTextNode(MATH_PLACEHOLDER_PREFIX + idxMatch[1] + "@@"));
            }
            rest = rest.slice(idxMatch.index + idxMatch[0].length);
          }
          node.replaceChild(frag, child);
        } else if (child.nodeType === 1) {
          walk(child);
        }
      }
    };
    walk(doc.body);
    return doc.body.innerHTML;
  } catch (err) {
    console.error("公式注入失败（fail-open，按原文显示）:", err);
    return html;
  }
}

function renderMarkdown(md) {
  // MD → HTML（marked gfm）→ sanitize；异常返回 null（调用方降级纯文本）
  // P4-3: 公式占位符管线——extractMath 移出公式 → marked/sanitize 净化 → restoreMathInHtml 注入
  if (typeof marked === "undefined") return null;
  try {
    const extracted = extractMath(md);
    // EVO-20260814: 显式禁用 marked v5+ 弃用默认（mangle/headerIds），消除 console 弃用警告刷屏
    const rawHtml = marked.parse(extracted.text, { gfm: true, mangle: false, headerIds: false });
    const sanitized = sanitizeHtml(rawHtml);
    if (sanitized === null) return null;
    if (extracted.formulas.length === 0) return sanitized; // 无公式短路直返（路径逐字符一致）
    return restoreMathInHtml(sanitized, extracted.formulas);
  } catch (err) {
    console.error("MD 渲染失败，降级纯文本:", err);
    return null;
  }
}

// ---------- P2-1 工具调用链渲染（M49） ----------
