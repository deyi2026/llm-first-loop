// 出产物文件预览视图（对齐 DSH client-ui-sidebar-documentpreview 能力面）：
// 文本分页 + 代码行号、Markdown 渲染、图片 data URI、pdf/html Blob iframe
// （html sandbox="allow-scripts" 无 allow-same-origin）、目录单层浏览、已知
// 二进制空态、重载、行号锚点跳转、HTML 相对 .js/.css 依赖打包（readRelated）。
// 本组件为右侧栏 tab 的 body（无模态壳）；程序只做机械分流，不判断内容语义。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchFilePreview,
  fetchFileRelated,
  type FilePreview,
  type FilePreviewFailure,
  type FileRelated,
} from "../core/api";
import { renderMarkdown } from "../core/markdown";
import { zh } from "../i18n/zh";

const MD_EXT = /\.(md|markdown)$/i;

// HTML 依赖打包上限（对齐 DSH documentpreview 固定安全限）：
// 64 个不同资产、总计 32MiB；单资产 4MiB 由后端 readRelated 拒绝。
const PACK_MAX_ASSETS = 64;
const PACK_MAX_TOTAL_BYTES = 32 * 1024 * 1024;

interface TextPage {
  offset: number;
  lines: string[];
}

function fmtSize(n: number | undefined): string {
  if (n === undefined) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

function joinPath(base: string, name: string): string {
  if (!base || base === "." || base === "/") return name;
  return base.endsWith("/") ? `${base}${name}` : `${base}/${name}`;
}

function failureText(status: number, err: FilePreviewFailure): string {
  if (status === 0) return zh.previewNetworkError;
  switch (err.error) {
    case "not_text":
      return zh.previewNotText;
    case "file_too_large":
    case "too_large":
    case "related_too_large":
      return err.detail || zh.previewTooLarge;
    case "out_of_bounds":
      return zh.previewOutOfBounds;
    case "file_not_found":
    case "dir_not_found":
      return zh.previewNotFound;
    case "ambiguous_path":
      return err.detail || zh.previewAmbiguous;
    case "invalid_range":
    case "unsupported_related_type":
      return err.detail || zh.previewInvalidRange;
    default:
      return err.detail || `${zh.previewFailed}（${err.error || status}）`;
  }
}

interface BytesState {
  type: "image" | "pdf" | "html";
  mime: string;
  size: number;
  content_base64: string;
}

/** 相对引用判定：排除 scheme/协议相对/根绝对/锚点/data/blob（浏览器自解析） */
function isRelativeRef(ref: string): boolean {
  return !!ref && !/^(?:[a-z][a-z0-9+.-]*:|\/\/|#|\/)/i.test(ref);
}

function stripQuery(ref: string): string {
  const i = ref.search(/[?#]/);
  return i < 0 ? ref : ref.slice(0, i);
}

function decodeBase64Text(b64: string): string {
  return new TextDecoder("utf-8", { fatal: true }).decode(
    Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
  );
}

/**
 * HTML 相对依赖打包（对齐 DSH documentpreview HTML renderer + readRelated）：
 * 仅直接声明的经典 <script src> 与 <link rel=stylesheet>；module/绝对/https/
 * <base href> 不打包（浏览器解析）；任一依赖失败/超限 → 整体失败，不部分发布。
 */
export async function packHtmlDependencies(basePath: string, html: string): Promise<string> {
  if (/<base\b/i.test(html)) return html; // base href 存在：解析交给浏览器
  const jobs: Array<{ kind: "script" | "css"; ref: string; full: string }> = [];
  const scriptRe = /<script\b([^>]*?)\bsrc\s*=\s*(["'])([^"']+)\2([^>]*?)>\s*<\/script\s*>/gi;
  let m: RegExpExecArray | null;
  while ((m = scriptRe.exec(html)) !== null) {
    const attrs = `${m[1]} ${m[4]}`;
    if (/type\s*=\s*["']?module["']?/i.test(attrs)) continue; // 模块导入不打包
    const clean = stripQuery(m[3].trim());
    if (!isRelativeRef(clean) || !/\.js$/i.test(clean)) continue;
    jobs.push({ kind: "script", ref: clean, full: m[0] });
  }
  const linkRe = /<link\b([^>]*?)>/gi;
  while ((m = linkRe.exec(html)) !== null) {
    const attrs = m[1];
    if (!/rel\s*=\s*["']?stylesheet/i.test(attrs)) continue;
    const hrefM = /href\s*=\s*(["'])([^"']+)\1/i.exec(attrs);
    if (!hrefM) continue;
    const clean = stripQuery(hrefM[2].trim());
    if (!isRelativeRef(clean) || !/\.css$/i.test(clean)) continue;
    jobs.push({ kind: "css", ref: clean, full: m[0] });
  }
  const distinct = [...new Set(jobs.map((j) => j.ref))];
  if (distinct.length === 0) return html;
  if (distinct.length > PACK_MAX_ASSETS) {
    throw new Error(zh.previewPackTooManyAssets.replace("{n}", String(PACK_MAX_ASSETS)));
  }
  const cache = new Map<string, { text: string; size: number }>();
  let total = 0;
  for (const ref of distinct) {
    const res = await fetchFileRelated(basePath, ref);
    if (res.status !== 200) {
      const err = res.data as FilePreviewFailure;
      throw new Error(`${zh.previewPackFetchFailed.replace("{ref}", ref)}：${failureText(res.status, err)}`);
    }
    const rel = res.data as FileRelated;
    if (rel.type !== "related") {
      throw new Error(zh.previewPackFetchFailed.replace("{ref}", ref));
    }
    let text: string;
    try {
      text = decodeBase64Text(rel.content_base64);
    } catch {
      throw new Error(zh.previewNotText);
    }
    total += rel.size;
    if (total > PACK_MAX_TOTAL_BYTES) {
      throw new Error(zh.previewPackTooLarge);
    }
    cache.set(ref, { text, size: rel.size });
  }
  let out = html;
  for (const j of jobs) {
    const content = cache.get(j.ref)?.text ?? "";
    const safe =
      j.kind === "script" ? content.replace(/<\/script/gi, "<\\/script") : content;
    const replacement = j.kind === "script" ? `<script>${safe}</script>` : `<style>${safe}</style>`;
    out = out.replace(j.full, replacement); // 逐个替换首个匹配，重复标签依次消解
  }
  return out;
}

export function FilePreviewView({
  path: tabPath,
  line,
  lineSeq = 0,
}: {
  path: string;
  /** 1-based 行号锚点（null = 无跳转请求） */
  line: number | null;
  /** 行号请求修订号：同值再请求也会重新触发跳转（对齐 DSH 新 revision） */
  lineSeq?: number;
}) {
  const [path, setPath] = useState(tabPath); // 目录浏览的视图内导航（不改 tab 身份）
  const [phase, setPhase] = useState<
    | { kind: "loading" }
    | { kind: "error"; text: string }
    | {
        kind: "text";
        size: number;
        pages: TextPage[];
        eof: boolean;
        loadingMore: boolean;
        moreFailed: boolean;
      }
    | ({ kind: "bytes" } & BytesState)
    | { kind: "dir"; parent: string; dirs: string[]; files: Array<{ name: string; size: number }> }
    | { kind: "unsupported"; ext: string }
  >({ kind: "loading" });
  // md 默认渲染视图；wrap 仅作用于纯文本/代码视图。
  const [plainMode, setPlainMode] = useState(false);
  const [wrap, setWrap] = useState(true);
  const [reloadTick, setReloadTick] = useState(0);
  const [pendingLine, setPendingLine] = useState<number | null>(line ?? null);
  // html 打包产物（null = 未完成/不适用）
  const [packedHtml, setPackedHtml] = useState<string | null>(null);
  const reqIdRef = useRef(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const flashTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
    };
  }, []);

  const applyFirst = useCallback(
    (result: { status: number; data: FilePreview | FilePreviewFailure }) => {
      const { status, data } = result;
      if (status !== 200) {
        setPhase({ kind: "error", text: failureText(status, data as FilePreviewFailure) });
        return;
      }
      const pv = data as FilePreview;
      switch (pv.type) {
        case "text":
          setPhase({
            kind: "text",
            size: pv.size,
            pages: [{ offset: pv.offset, lines: pv.content.split("\n") }],
            eof: pv.eof,
            loadingMore: false,
            moreFailed: false,
          });
          break;
        case "image":
        case "pdf":
        case "html":
          setPhase({
            kind: "bytes",
            type: pv.type,
            mime: pv.mime,
            size: pv.size,
            content_base64: pv.content_base64,
          });
          break;
        case "dir":
          setPhase({ kind: "dir", parent: pv.parent, dirs: pv.dirs, files: pv.files });
          break;
        case "unsupported_binary":
          setPhase({ kind: "unsupported", ext: pv.ext });
          break;
      }
    },
    []
  );

  // 首载/换路径/重载：文本从第 1 页重读（对齐 DSH reload——不混版本）
  useEffect(() => {
    const reqId = ++reqIdRef.current;
    setPhase({ kind: "loading" });
    setPlainMode(false);
    setPackedHtml(null);
    void fetchFilePreview(path).then((result) => {
      if (reqIdRef.current !== reqId) return; // 迟到响应丢弃
      applyFirst(result);
    });
  }, [path, reloadTick, applyFirst]);

  // 行号锚点请求 revision：prop 变化（含同值新 seq）→ 重新挂起执行
  useEffect(() => {
    setPendingLine(line ?? null);
  }, [line, lineSeq]);

  const loadMore = useCallback(async () => {
    if (phase.kind !== "text" || phase.eof || phase.loadingMore) return;
    const last = phase.pages[phase.pages.length - 1];
    const nextOffset = last.offset + last.lines.length;
    setPhase({ ...phase, loadingMore: true, moreFailed: false });
    const reqId = reqIdRef.current;
    const result = await fetchFilePreview(path, nextOffset);
    if (reqIdRef.current !== reqId) return;
    if (result.status !== 200) {
      // 加载更多失败：保留已载内容 + 如实标记（对齐 DSH：later failure retains
      // content）；锚点自动翻页在有失败标记时停转，人工重试后继续。
      setPhase({ ...phase, loadingMore: false, moreFailed: true });
      return;
    }
    const pv = result.data as FilePreview;
    if (pv.type !== "text") return;
    setPhase((prev) =>
      prev.kind !== "text"
        ? prev
        : {
            ...prev,
            pages: [...prev.pages, { offset: pv.offset, lines: pv.content.split("\n") }],
            eof: pv.eof,
            loadingMore: false,
            moreFailed: false,
          }
    );
  }, [phase, path]);

  // HTML 依赖打包：bytes(html) 相位触发；失败 → 整体错误态（不部分发布）
  useEffect(() => {
    if (phase.kind !== "bytes" || phase.type !== "html") {
      setPackedHtml(null);
      return;
    }
    let alive = true;
    setPackedHtml(null);
    let htmlText: string;
    try {
      htmlText = decodeBase64Text(phase.content_base64);
    } catch {
      setPhase({ kind: "error", text: zh.previewNotText });
      return;
    }
    void packHtmlDependencies(path, htmlText).then(
      (packed) => {
        if (alive) setPackedHtml(packed);
      },
      (err: unknown) => {
        if (alive) {
          setPhase({ kind: "error", text: err instanceof Error ? err.message : String(err) });
        }
      }
    );
    return () => {
      alive = false;
    };
  }, [phase, path]);

  // Blob URL 生命周期归 effect 管：pdf 用原始字节，html 用打包产物；
  // image 用 data URI 直渲染不经 Blob。
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    if (phase.kind !== "bytes" || phase.type === "image") {
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
      return;
    }
    if (phase.type === "html" && packedHtml === null) return; // 打包中
    const url =
      phase.type === "html"
        ? URL.createObjectURL(new Blob([packedHtml!], { type: "text/html" }))
        : URL.createObjectURL(
            new Blob([Uint8Array.from(atob(phase.content_base64), (c) => c.charCodeAt(0))], {
              type: phase.mime,
            })
          );
    setBlobUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return url;
    });
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [phase, packedHtml]);

  const mdHtml = useMemo(() => {
    if (phase.kind !== "text") return "";
    return renderMarkdown(
      phase.pages.map((p) => p.lines.join("\n")).join("\n"),
      undefined,
      { enableMath: true }
    );
  }, [phase]);

  // 行号锚点执行（对齐 DSH openResource line 语义）：
  // - 纯文本/代码视图有锚点：翻页至目标行 → 滚动 + 高亮，一次性应答；
  // - Markdown 渲染态无锚点：挂起，切纯文本时执行；
  // - 字节/目录/不支持视图不消费行号（对齐 DSH byte-mode）；
  // - 目标行超 EOF：机械事实，静默丢弃。
  useEffect(() => {
    if (pendingLine === null) return;
    if (phase.kind !== "text") {
      if (phase.kind !== "loading") setPendingLine(null);
      return;
    }
    const isMd = MD_EXT.test(path);
    if (isMd && !plainMode) return; // 挂起
    const last = phase.pages[phase.pages.length - 1];
    const lastLine = last.offset + last.lines.length - 1;
    if (pendingLine <= lastLine) {
      const el = rootRef.current?.querySelector(`[data-line="${pendingLine}"]`);
      if (el) {
        el.scrollIntoView?.({ block: "center" });
        el.classList.add("anchor-flash");
        if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
        flashTimerRef.current = window.setTimeout(() => el.classList.remove("anchor-flash"), 2000);
        setPendingLine(null); // answered once
      }
    } else if (!phase.eof && !phase.loadingMore && !phase.moreFailed) {
      void loadMore();
    } else if (phase.eof || phase.moreFailed) {
      setPendingLine(null);
    }
  }, [pendingLine, phase, plainMode, path, loadMore]);

  const navigate = (next: string) => {
    if (next === path) return;
    setPath(next);
  };

  const renderBody = () => {
    switch (phase.kind) {
      case "loading":
        return <div className="v2-preview-hint">{zh.previewLoading}</div>;
      case "error":
        return <div className="v2-preview-hint err" role="alert">{phase.text}</div>;
      case "unsupported":
        return (
          <div className="v2-preview-empty" data-testid="preview-unsupported">
            <span className="v2-preview-empty-icon">📦</span>
            <span>{zh.previewUnsupportedBinary.replace("{ext}", phase.ext)}</span>
          </div>
        );
      case "bytes":
        if (phase.type === "image") {
          return (
            <div className="v2-preview-media">
              <img
                src={`data:${phase.mime};base64,${phase.content_base64}`}
                alt={path}
                className="v2-preview-img"
                data-testid="preview-image"
              />
            </div>
          );
        }
        if (phase.type === "html" && packedHtml === null) {
          return <div className="v2-preview-hint">{zh.previewPacking}</div>;
        }
        return (
          <iframe
            title={phase.type === "pdf" ? "pdf-preview" : "html-preview"}
            src={blobUrl ?? undefined}
            className="v2-preview-frame"
            data-testid={phase.type === "pdf" ? "preview-pdf" : "preview-html"}
            // 对齐 DSH：HTML 沙箱只给 allow-scripts，绝无 allow-same-origin——
            // 文档脚本不可触父应用源/文件读取；pdf 无脚本面也统一沙箱。
            sandbox={phase.type === "html" ? "allow-scripts" : undefined}
          />
        );
      case "dir": {
        const rows = [
          ...phase.dirs.map((name) => ({ name, dir: true, size: undefined as number | undefined })),
          ...phase.files.map((f) => ({ name: f.name, dir: false, size: f.size })),
        ];
        return (
          <div className="v2-preview-dir" data-testid="preview-dir">
            {phase.parent && phase.parent !== "." ? (
              <button
                type="button"
                className="v2-preview-dir-up"
                onClick={() => navigate(phase.parent)}
              >
                ↩ {zh.previewParent}
              </button>
            ) : null}
            {rows.length === 0 ? (
              <div className="v2-preview-hint">{zh.previewEmptyDir}</div>
            ) : (
              rows.map((r) => (
                <button
                  type="button"
                  key={r.name}
                  className="v2-preview-dir-row"
                  onClick={() => navigate(joinPath(path, r.name))}
                >
                  <span>{r.dir ? "📁" : "📄"}</span>
                  <span className="v2-preview-dir-name">{r.name}</span>
                  {r.size !== undefined ? (
                    <span className="v2-preview-dir-size">{fmtSize(r.size)}</span>
                  ) : null}
                </button>
              ))
            )}
          </div>
        );
      }
      case "text": {
        const isMd = MD_EXT.test(path);
        const showPlain = !isMd || plainMode;
        return (
          <div className="v2-preview-text">
            {showPlain ? (
              <div className={`v2-preview-lines ${wrap ? "wrap" : "nowrap"}`}>
                {phase.pages.flatMap((p) =>
                  p.lines.map((lineText, i) => (
                    <div className="v2-preview-line" key={`${p.offset}-${i}`} data-line={p.offset + i}>
                      <span className="v2-preview-lineno">{p.offset + i}</span>
                      <span className="v2-preview-line-text">{lineText || " "}</span>
                    </div>
                  ))
                )}
              </div>
            ) : (
              <div
                className="v2-md v2-preview-md"
                data-testid="preview-markdown"
                dangerouslySetInnerHTML={{ __html: mdHtml }}
              />
            )}
            {phase.moreFailed ? (
              <div className="v2-preview-truncated err" role="status">{zh.previewLoadMoreFailed}</div>
            ) : null}
            {!phase.eof ? (
              <button
                type="button"
                className="v2-btn v2-preview-loadmore"
                disabled={phase.loadingMore}
                onClick={() => void loadMore()}
                data-testid="preview-load-more"
              >
                {phase.loadingMore ? zh.previewLoadingMore : zh.previewLoadMore}
              </button>
            ) : null}
          </div>
        );
      }
    }
  };

  const isText = phase.kind === "text";
  const isMd = MD_EXT.test(path);

  return (
    <div className="v2-preview-view" ref={rootRef} data-testid="file-preview">
      <div className="v2-preview-head">
        <span className="v2-preview-path" title={path}>{path}</span>
        {phase.kind === "text" || phase.kind === "bytes" ? (
          <span className="v2-preview-size">{fmtSize(phase.size)}</span>
        ) : null}
        <span className="v2-preview-tools">
          {isText && isMd ? (
            <button
              type="button"
              className="v2-icon-btn"
              title={plainMode ? zh.previewRendered : zh.previewPlain}
              onClick={() => setPlainMode((v) => !v)}
            >
              {plainMode ? "◧" : "▤"}
            </button>
          ) : null}
          {isText ? (
            <button
              type="button"
              className="v2-icon-btn"
              title={wrap ? zh.previewNoWrap : zh.previewWrap}
              onClick={() => setWrap((v) => !v)}
            >
              {wrap ? "↵" : "→"}
            </button>
          ) : null}
          <button
            type="button"
            className="v2-icon-btn"
            title={zh.previewReload}
            onClick={() => {
              setPath(tabPath); // 重载回 tab 身份路径（退出目录浏览导航）
              setReloadTick((t) => t + 1);
            }}
            data-testid="preview-reload"
          >
            ↻
          </button>
        </span>
      </div>
      {isText && isMd && !plainMode && pendingLine !== null ? (
        <div className="v2-preview-line-pending" role="status">
          {zh.previewLinePending.replace("{n}", String(pendingLine))}
        </div>
      ) : null}
      <div className="v2-preview-body">{renderBody()}</div>
    </div>
  );
}
