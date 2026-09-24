// Web V2：Markdown 渲染（marked + DOMPurify 白名单 + KaTeX 数学 + 轻量代码高亮）
// 视觉对齐 DSH：--dsw-alias-markdown-* 底色、--shiki-token-* 语法色（token 层定义）

import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({
  gfm: true,
  breaks: true,
});

type MathRenderToString = (expr: string, displayMode: boolean) => string;

let mathRenderToString: MathRenderToString | null = null;
let mathRendererLoad: Promise<void> | null = null;

export function isMathRendererReady(): boolean {
  return mathRenderToString !== null;
}

/** Load KaTeX only when a rendered, non-live surface actually contains math. */
export async function ensureMathRenderer(): Promise<void> {
  if (mathRenderToString) return;
  if (!mathRendererLoad) {
    mathRendererLoad = import("./mathRenderer")
      .then(({ renderTrustedMath }) => {
        mathRenderToString = renderTrustedMath;
      })
      .catch((error) => {
        // A transient chunk failure must be retryable; callers keep literal Markdown visible.
        mathRendererLoad = null;
        throw error;
      });
  }
  await mathRendererLoad;
}

// 代码块渲染：banner（语言 + 字符数 + 复制按钮）+ 轻量高亮（对齐 DSH 代码块结构）。
// 复制按钮点击由 Markdown 组件事件委托处理（dangerouslySetInnerHTML 无法绑 React 事件）。
marked.use({
  renderer: {
    code({ text, lang }) {
      const escAttr = (s: string) =>
        s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const langSafe = escAttr((lang ?? "").trim());
      const body = highlightCode(text, langSafe);
      const langLabel = langSafe ? `<span class="v2-code-lang">${langSafe}</span>` : "";
      const count = text.length;
      return (
        '<div class="v2-code-block">' +
        '<div class="v2-code-banner">' +
        langLabel +
        `<span class="v2-code-count">${count} 字符</span>` +
        '<button type="button" class="v2-code-copy" aria-label="复制代码">复制</button>' +
        "</div>" +
        `<pre><code class="lang-${langSafe || "text"}">${body}</code></pre>` +
        "</div>"
      );
    },
  },
});

const ALLOWED_TAGS = [
  "p", "br", "hr", "strong", "em", "del", "code", "pre", "blockquote", "ul", "ol", "li",
  "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "table", "thead", "tbody", "tr", "th", "td",
  "span", "div", "input", "details", "summary", "button",
];

const ALLOWED_ATTR = ["href", "src", "alt", "title", "class", "checked", "type", "aria-label"];

// Must contain no Markdown punctuation because placeholders pass through `marked.parse`.
const MATH_PLACEHOLDER_RE = /\uE100LFLMATH(\d+)X\uE101/g;

/**
 * Convert math to opaque placeholders, not HTML.
 *
 * KaTeX needs a handful of inline style/ARIA/MathML attributes for correct layout and
 * accessibility.  Sending its HTML through the generic user-Markdown sanitizer strips
 * those attributes; globally allowing `style` would in turn let raw user HTML escape the
 * intended presentation boundary.  We therefore sanitize Markdown first and restore only
 * HTML produced by our local KaTeX instance afterwards. `trust:false` keeps KaTeX's own
 * URL/HTML escape hatches disabled.
 */
function extractTrustedMath(src: string): {
  source: string;
  restore: (sanitizedHtml: string) => string;
} {
  const renderMath = mathRenderToString;
  if (!renderMath) return { source: src, restore: (value) => value };
  const rendered: string[] = [];
  const stashMath = (expr: string, displayMode: boolean, original: string): string => {
    try {
      const html = renderMath(expr, displayMode);
      const index = rendered.push(html) - 1;
      return `\uE100LFLMATH${index}X\uE101`;
    } catch {
      // Malformed or unsupported TeX stays literal rather than becoming a red error span.
      return original;
    }
  };

  let source = src.replace(/\$\$([\s\S]+?)\$\$/g, (match, expr: string) =>
    stashMath(expr, true, match)
  );
  source = source.replace(/(^|[^$])\$([^$\n]+?)\$(?![$])/g, (match, pre: string, expr: string) => {
    const originalMath = match.slice(pre.length);
    const placeholder = stashMath(expr, false, originalMath);
    return `${pre}${placeholder}`;
  });

  return {
    source,
    restore: (sanitizedHtml: string) =>
      sanitizedHtml.replace(MATH_PLACEHOLDER_RE, (match: string, rawIndex: string) => {
        const html = rendered[Number(rawIndex)];
        return html === undefined ? match : html;
      }),
  };
}

/**
 * 在数学预处理阶段保护 Markdown 代码字面量。
 *
 * renderMath() 发生在 marked.parse() 之前；若直接扫描整段 Markdown，shell 代码里的
 * `"$PWD" ... "$PWD"` 会被误识别成一段 `$...$` 数学，然后 KaTeX HTML 再被代码块
 * renderer 转义成可见文本，最终连“复制代码”都会复制污染后的 `<span class="katex">`。
 *
 * 这里只做机械字面量隔离：先暂存 fenced/inline code，数学处理结束后逐字恢复，随后仍
 * 交给 marked 正常解析。不会判断代码语义，也不会改变真正的数学文本。
 */
function protectMarkdownLiteralsFromMath(src: string): { masked: string; restore: (value: string) => string } {
  const segments: string[] = [];
  const stash = (value: string): string => {
    const index = segments.push(value) - 1;
    return `\uE000LFL_CODE_${index}\uE001`;
  };

  // Use the same Markdown grammar as the renderer. Besides code, protect link/image/raw
  // HTML tokens because `$...$` inside href/src/attributes is Markdown syntax, not prose
  // math. Protecting the complete token is intentionally conservative: link-label math is
  // less important than never mutating a destination before `marked.parse`.
  const literals: string[] = [];
  marked.walkTokens(marked.lexer(src), (token) => {
    if (["code", "codespan", "link", "image", "html"].includes(token.type)) {
      const raw = (token as { raw?: string }).raw;
      if (raw) literals.push(raw);
    }
  });
  let masked = src;
  // Outer code blocks must be protected before any shorter inline literal.
  for (const literal of literals.sort((a, b) => b.length - a.length)) {
    if (literal && masked.includes(literal)) masked = masked.split(literal).join(stash(literal));
  }

  // CommonMark backslash-escaped dollars are explicit literals. Hide each escaped pair
  // from the math scanner and restore it before Markdown parsing so marked can remove the
  // escape in the normal way (`\$5` -> `$5`).
  masked = masked.replace(/\\\$/g, (literal) => stash(literal));

  const restore = (value: string): string =>
    value.replace(/\uE000LFL_CODE_(\d+)\uE001/g, (match: string, rawIndex: string) => {
      const segment = segments[Number(rawIndex)];
      return segment === undefined ? match : segment;
    });

  return { masked, restore };
}

/** Mechanical candidate check used only to decide whether the optional KaTeX chunk is needed. */
export function hasMathCandidate(src: string): boolean {
  if (!src || !src.includes("$")) return false;
  try {
    const { masked } = protectMarkdownLiteralsFromMath(src);
    return (
      /\$\$[\s\S]+?\$\$/.test(masked) ||
      /(^|[^$])\$([^$\n]+?)\$(?![$])/.test(masked)
    );
  } catch {
    // Candidate detection is a performance hint only; fail closed to literal Markdown.
    return false;
  }
}

/** 已知文件扩展名（路径样式判定用） */
const PATH_EXT = /\.(py|ts|tsx|js|jsx|md|json|sh|css|yaml|yml|toml|html|txt|sql|go|rs|java|vue|svg|c|h|cpp|lock|ini|cfg)$/i;

/** 路径样式判定：无空白、非 URL、含 / 或以已知扩展名结尾（防把命令/普通词误判） */
function looksLikePath(code: string): boolean {
  if (!code || code.length > 200 || /\s/.test(code)) return false;
  if (/^(https?:|www\.)/i.test(code)) return false;
  return code.includes("/") || PATH_EXT.test(code);
}

export interface RenderMarkdownOptions {
  /** reasoning/debug surfaces may contain shell variables such as $d$p; disable KaTeX there. */
  enableMath?: boolean;
}

export function renderMarkdown(
  src: string,
  clickablePaths?: Set<string>,
  options: RenderMarkdownOptions = {}
): string {
  if (!src) return "";
  try {
    let markdown = src;
    let restoreMath = (value: string) => value;
    if (options.enableMath !== false && mathRenderToString) {
      const protectedLiterals = protectMarkdownLiteralsFromMath(src);
      const math = extractTrustedMath(protectedLiterals.masked);
      markdown = protectedLiterals.restore(math.source);
      restoreMath = math.restore;
    }
    const raw = marked.parse(markdown) as string;
    let clean = DOMPurify.sanitize(raw, {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|data:image\/|#)/i,
    });
    // 文件路径内联链接（对齐 DSH producedFileMentions）：
    // ① 命中出产物集合（edit_file 产出，相对/绝对 forms endsWith 互通）必可点；
    // ② 路径样式的 inline code 也可点——点击时后端校验存在性（404 如实提示，
    //    防误开不静默）。URL/命令/普通词排除。
    // ③ 行/列锚点（对齐 DSH openResource line 参数 + 代码导航按列定位）：
    //    `path:42` / `path:42:7`（1-based 行/列）拆出 data-line/data-col，
    //    预览打开后翻页定位到该行列并高亮。
    const paths = clickablePaths ? [...clickablePaths] : [];
    clean = clean.replace(/<code>([^<]*)<\/code>/g, (_m, codeRaw: string) => {
      const code = codeRaw.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
      let pathText = code;
      let lineAttr = "";
      let lineNum = 0;
      let colNum = 0;
      const lineRef = /^([^\s:]+):(\d{1,6})(?::(\d{1,4}))?$/.exec(code);
      if (lineRef && PATH_EXT.test(lineRef[1])) {
        pathText = lineRef[1];
        lineNum = Number(lineRef[2]);
        colNum = lineRef[3] ? Number(lineRef[3]) : 0;
        lineAttr = ` data-line="${lineNum}"` + (colNum ? ` data-col="${colNum}"` : "");
      }
      const producedHit = paths.some((p) => p === pathText || pathText.endsWith(p) || p.endsWith(pathText));
      if (!producedHit && !looksLikePath(pathText)) return _m;
      const htmlEsc = pathText.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const suffix = lineNum ? `:${lineNum}${colNum ? `:${colNum}` : ""}` : "";
      const title = lineNum
        ? `打开并跳转到 ${colNum ? `行 ${lineNum} 列 ${colNum}` : `行 ${lineNum}`}`
        : `打开 ${htmlEsc}`;
      return `<span class="v2-file-link" data-path="${htmlEsc}"${lineAttr} title="${title}">${htmlEsc}${suffix}</span>`;
    });
    return restoreMath(clean);
  } catch {
    return DOMPurify.sanitize(src, { ALLOWED_TAGS, ALLOWED_ATTR });
  }
}

/** 轻量语法高亮（单遍分词器，对齐原版能力；颜色走 --shiki-token-* 由主题层切换） */
const HIGHLIGHT_KEYWORDS = new Set([
  "def", "class", "return", "import", "from", "if", "else", "elif", "for", "while",
  "try", "except", "finally", "with", "as", "pass", "break", "continue", "lambda",
  "yield", "async", "await", "raise", "global", "nonlocal", "match", "case",
  "True", "False", "None", "and", "or", "not", "in", "is", "const", "let", "var",
  "function", "export", "new", "typeof", "switch", "case", "default", "do", "void",
  "int", "float", "char", "double", "long", "struct", "enum", "static", "void",
]);

export function highlightCode(code: string, _lang?: string): string {
  const re =
    /("[^"\n]*"|'[^'\n]*'|`[^`\n]*`)|(#[^\n]*|\/\/[^\n]*)|(\b\d+\.?\d*\b)|(\b[A-Za-z_][A-Za-z0-9_]*\b)/g;
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code)) !== null) {
    if (m.index > last) out += esc(code.slice(last, m.index));
    const [, str, comment, num, ident] = m;
    let cls: string | null = null;
    if (str !== undefined) cls = "shiki-string";
    else if (comment !== undefined) cls = "shiki-comment";
    else if (num !== undefined) cls = "shiki-number";
    else if (ident !== undefined && HIGHLIGHT_KEYWORDS.has(ident)) cls = "shiki-keyword";
    if (cls) out += `<span class="${cls}">${esc(m[0])}</span>`;
    else out += esc(m[0]);
    last = m.index + m[0].length;
  }
  out += esc(code.slice(last));
  return out;
}
