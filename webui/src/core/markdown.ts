// Web V2：Markdown 渲染（marked + DOMPurify 白名单 + KaTeX 数学 + 轻量代码高亮）
// 视觉对齐 DSH：--dsw-alias-markdown-* 底色、--shiki-token-* 语法色（token 层定义）

import { marked } from "marked";
import DOMPurify from "dompurify";
import katex from "katex";
import "katex/dist/katex.min.css";

marked.setOptions({
  gfm: true,
  breaks: true,
});

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

/** 行内/块级数学 → KaTeX HTML（失败 fail-open 原样返回） */
function renderMath(src: string): string {
  // 块级 $$...$$
  let out = src.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) => {
    try {
      return katex.renderToString(expr.trim(), { displayMode: true, throwOnError: false });
    } catch {
      return _m;
    }
  });
  // 行内 $...$
  out = out.replace(/(^|[^$])\$([^$\n]+?)\$(?![$])/g, (_m, pre: string, expr: string) => {
    try {
      return `${pre}${katex.renderToString(expr.trim(), { displayMode: false, throwOnError: false })}`;
    } catch {
      return _m;
    }
  });
  return out;
}

/** 已知文件扩展名（路径样式判定用） */
const PATH_EXT = /\.(py|ts|tsx|js|jsx|md|json|sh|css|yaml|yml|toml|html|txt|sql|go|rs|java|vue|svg|c|h|cpp|lock|ini|cfg)$/i;

/** 路径样式判定：无空白、非 URL、含 / 或以已知扩展名结尾（防把命令/普通词误判） */
function looksLikePath(code: string): boolean {
  if (!code || code.length > 200 || /\s/.test(code)) return false;
  if (/^(https?:|www\.)/i.test(code)) return false;
  return code.includes("/") || PATH_EXT.test(code);
}

export function renderMarkdown(src: string, clickablePaths?: Set<string>): string {
  if (!src) return "";
  try {
    const math = renderMath(src);
    const raw = marked.parse(math) as string;
    let clean = DOMPurify.sanitize(raw, {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|data:image\/|#)/i,
    });
    // 文件路径内联链接（对齐 DSH producedFileMentions）：
    // ① 命中出产物集合（edit_file 产出，相对/绝对 forms endsWith 互通）必可点；
    // ② 路径样式的 inline code 也可点——点击时后端校验存在性（404 如实提示，
    //    防误开不静默）。URL/命令/普通词排除。
    const paths = clickablePaths ? [...clickablePaths] : [];
    clean = clean.replace(/<code>([^<]*)<\/code>/g, (_m, codeRaw: string) => {
      const code = codeRaw.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
      const producedHit = paths.some((p) => p === code || code.endsWith(p) || p.endsWith(code));
      if (!producedHit && !looksLikePath(code)) return _m;
      const htmlEsc = code.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<span class="v2-file-link" data-path="${htmlEsc}" title="打开 ${htmlEsc}">${htmlEsc}</span>`;
    });
    return clean;
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
