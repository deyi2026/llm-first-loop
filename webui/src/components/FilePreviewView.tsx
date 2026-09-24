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
import { previewWatcher, type PreviewStatFacts } from "../core/previewWatch";
import {
  ensureMathRenderer,
  hasMathCandidate,
  highlightCode,
  isMathRendererReady,
  renderMarkdown,
} from "../core/markdown";
import { zh } from "../i18n/zh";

const MD_EXT = /\.(md|markdown)$/i;

// HTML 依赖打包上限（对齐 DSH documentpreview 固定安全限）：
// 64 个不同资产、总计 32MiB；单资产 4MiB 由后端 readRelated 拒绝。
// CSS url()/@import 引用的资产共享同一预算。
const PACK_MAX_ASSETS = 64;
const PACK_MAX_TOTAL_BYTES = 32 * 1024 * 1024;
const CSS_IMPORT_DEPTH_MAX = 3;

/** 版本指纹：size + mtime_ns（读前 stat；对齐 DSH read/version 语义） */
function versionKey(size: number, mtimeNs: number): string {
  return `${size}:${mtimeNs}`;
}

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

interface RelatedAsset {
  absPath: string;
  mime: string;
  b64: string;
  size: number;
  /** 仅文本类依赖（.js/.css）解码后的文本；二进制资产为 null */
  text: string | null;
}

const CSS_URL_PACKABLE_EXT = /\.(png|jpe?g|gif|webp|svg|ico|bmp|woff2?|ttf|otf|eot)$/i;

/**
 * HTML 相对依赖打包（对齐 DSH documentpreview HTML renderer + readRelated，
 * 扩展至 CSS 引用资产）：
 * - 直接声明的经典 <script src> 与 <link rel=stylesheet>；
 * - css 内相对 url(图片/字体) → data URI（以该 css 文件为 base 解析）；
 * - css 内相对 @import "sub.css" 递归内联（限深 CSS_IMPORT_DEPTH_MAX）；
 * - module/绝对/https/data/<base href> 不打包（浏览器解析）；
 * - 任一依赖失败/超限 → 整体失败，不部分发布；64 资产/32MiB 预算共享。
 */
export async function packHtmlDependencies(basePath: string, html: string): Promise<string> {
  if (/<base\b/i.test(html)) return html; // base href 存在：解析交给浏览器
  const fetchCache = new Map<string, RelatedAsset>(); // `${base}\0${ref}` → 资产
  const countedPaths = new Set<string>(); // 解析后绝对路径去重（distinct 资产）
  let totalBytes = 0;

  async function loadRelated(base: string, ref: string, expectText: boolean): Promise<RelatedAsset> {
    const key = `${base}\0${ref}`;
    const cached = fetchCache.get(key);
    if (cached) return cached;
    const res = await fetchFileRelated(base, ref);
    if (res.status !== 200) {
      const err = res.data as FilePreviewFailure;
      throw new Error(`${zh.previewPackFetchFailed.replace("{ref}", ref)}：${failureText(res.status, err)}`);
    }
    const rel = res.data as FileRelated;
    if (rel.type !== "related") {
      throw new Error(zh.previewPackFetchFailed.replace("{ref}", ref));
    }
    if (!countedPaths.has(rel.path)) {
      countedPaths.add(rel.path);
      if (countedPaths.size > PACK_MAX_ASSETS) {
        throw new Error(zh.previewPackTooManyAssets.replace("{n}", String(PACK_MAX_ASSETS)));
      }
      totalBytes += rel.size;
      if (totalBytes > PACK_MAX_TOTAL_BYTES) {
        throw new Error(zh.previewPackTooLarge);
      }
    }
    let text: string | null = null;
    if (expectText) {
      try {
        text = decodeBase64Text(rel.content_base64);
      } catch {
        throw new Error(zh.previewNotText);
      }
    }
    const asset: RelatedAsset = {
      absPath: rel.path,
      mime: rel.mime,
      b64: rel.content_base64,
      size: rel.size,
      text,
    };
    fetchCache.set(key, asset);
    return asset;
  }

  /** 展开 css：内联相对 @import（递归）与 url() 资产（data URI） */
  async function expandCss(cssBaseAbs: string, cssText: string, depth: number): Promise<string> {
    let out = cssText;
    if (depth < CSS_IMPORT_DEPTH_MAX) {
      const importRe = /@import\s+(?:url\(\s*)?["']?([^"')\s;]+)["']?\s*\)?\s*;/gi;
      const imports: Array<{ full: string; ref: string }> = [];
      let im: RegExpExecArray | null;
      while ((im = importRe.exec(cssText)) !== null) {
        const ref = stripQuery(im[1].trim());
        if (!isRelativeRef(ref) || !/\.css$/i.test(ref)) continue;
        imports.push({ full: im[0], ref });
      }
      for (const imp of imports) {
        const asset = await loadRelated(cssBaseAbs, imp.ref, true);
        if (asset.text === null) continue;
        const inner = await expandCss(asset.absPath, asset.text, depth + 1);
        out = out.replace(imp.full, inner);
      }
    }
    const urlRe = /url\(\s*(["']?)([^"')]+)\1\s*\)/gi;
    const urlJobs: Array<{ full: string; ref: string }> = [];
    let um: RegExpExecArray | null;
    while ((um = urlRe.exec(out)) !== null) {
      const ref = stripQuery(um[2].trim());
      if (!isRelativeRef(ref)) continue; // https/data/#/根绝对：浏览器解析
      if (!CSS_URL_PACKABLE_EXT.test(ref)) continue; // 面外扩展留给浏览器
      urlJobs.push({ full: um[0], ref });
    }
    for (const j of urlJobs) {
      const asset = await loadRelated(cssBaseAbs, j.ref, false);
      out = out.replace(j.full, `url(data:${asset.mime};base64,${asset.b64})`);
    }
    return out;
  }

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
  if (jobs.length === 0) return html;

  let out = html;
  for (const j of jobs) {
    const asset = await loadRelated(basePath, j.ref, true);
    if (j.kind === "script") {
      const safe = (asset.text ?? "").replace(/<\/script/gi, "<\\/script");
      out = out.replace(j.full, `<script>${safe}</script>`);
    } else {
      // css 文本经 expandCss 展开（@import 递归 + url() data URI 化）
      const expanded = await expandCss(asset.absPath, asset.text ?? "", 0);
      out = out.replace(j.full, `<style>${expanded}</style>`);
    }
  }
  return out;
}

export function FilePreviewView({
  path: tabPath,
  line,
  col,
  lineSeq = 0,
}: {
  path: string;
  /** 1-based 行号锚点（null = 无跳转请求） */
  line: number | null;
  /** 1-based 列号（null = 行级定位；给定列且在行内 → 列字符高亮 + 水平滚动） */
  col?: number | null;
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
  const [mathRevision, setMathRevision] = useState(0);
  const [wrap, setWrap] = useState(true);
  const [reloadTick, setReloadTick] = useState(0);
  // 行/列锚点：pending = 待执行请求；activeAnchor = 已定位目标（渲染列字符高亮）
  const [pending, setPending] = useState<{ line: number; col: number | null } | null>(
    line != null ? { line, col: col ?? null } : null
  );
  const [activeAnchor, setActiveAnchor] = useState<{ line: number; col: number | null } | null>(null);
  // html 打包产物（null = 未完成/不适用）
  const [packedHtml, setPackedHtml] = useState<string | null>(null);
  // 版本监听（对齐 DSH changes/stale 语义）：readVersion = 当前已载内容的
  // 版本指纹；stale = 观察到较新版本或文件消失（内容不自动替换，用户决定）；
  // restartedHint = 分页续读漂移后从头重读的一次性提示。
  const readVersionRef = useRef<string | null>(null);
  const [stale, setStale] = useState<{ observed: PreviewStatFacts | null } | null>(null);
  const [restartedHint, setRestartedHint] = useState(false);
  const restartTimerRef = useRef<number | null>(null);
  const reqIdRef = useRef(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const flashTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
      if (restartTimerRef.current !== null) window.clearTimeout(restartTimerRef.current);
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
          readVersionRef.current = versionKey(pv.size, pv.mtime_ns);
          setStale(null); // 已观察到的版本经重载成为读取基线，不再报变更
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
          readVersionRef.current = versionKey(pv.size, pv.mtime_ns);
          setStale(null);
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

  // 行/列锚点请求 revision：prop 变化（含同值新 seq）→ 重新挂起执行
  useEffect(() => {
    setPending(line != null ? { line, col: col ?? null } : null);
  }, [line, col, lineSeq]);

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
    const baseline = readVersionRef.current;
    const got = versionKey(pv.size, pv.mtime_ns);
    if (baseline !== null && got !== baseline) {
      // 续读页版本漂移：不混版本——丢弃旧页，从头重读新版本（对齐 DSH
      // "a newer-version page past page one restarts from the beginning"）。
      const fresh = await fetchFilePreview(path, 1);
      if (reqIdRef.current !== reqId) return;
      if (fresh.status === 200) {
        const fp = fresh.data as FilePreview;
        if (fp.type === "text") {
          applyFirst(fresh);
          setRestartedHint(true);
          if (restartTimerRef.current !== null) window.clearTimeout(restartTimerRef.current);
          restartTimerRef.current = window.setTimeout(() => setRestartedHint(false), 3000);
          return;
        }
      }
      // 重读失败：保留旧内容并如实标记（不静默混入）
      setPhase({ ...phase, loadingMore: false, moreFailed: true });
      return;
    }
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
  }, [phase, path, applyFirst]);

  // 版本观察（对齐 DSH changes 流的 stale 提示语义）：已载内容不自动替换；
  // 观察到不同版本 → stale 横幅 + 显式重载入口；观察到相同版本 → 清横幅
  // （已观察版本经重载成为基线后不再报变更）；文件消失 → absent 提示。
  useEffect(() => {
    if (phase.kind !== "text" && phase.kind !== "bytes") return;
    return previewWatcher.register(path, (facts) => {
      if (facts === null) {
        setStale({ observed: null });
        return;
      }
      const observed = versionKey(facts.size, facts.mtime_ns);
      if (readVersionRef.current === null || observed === readVersionRef.current) {
        setStale(null);
        return;
      }
      setStale({ observed: facts });
    });
  }, [path, phase.kind]);

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

  const markdownSource = useMemo(
    () => (phase.kind === "text" ? phase.pages.map((p) => p.lines.join("\n")).join("\n") : ""),
    [phase]
  );
  useEffect(() => {
    if (
      plainMode ||
      !MD_EXT.test(path) ||
      isMathRendererReady() ||
      !hasMathCandidate(markdownSource)
    ) {
      return;
    }
    let active = true;
    void ensureMathRenderer()
      .then(() => {
        if (active) setMathRevision((value) => value + 1);
      })
      .catch(() => {
        // Preview remains usable as literal Markdown if the optional chunk cannot load.
      });
    return () => {
      active = false;
    };
  }, [markdownSource, path, plainMode]);

  const mdHtml = useMemo(
    () => renderMarkdown(markdownSource, undefined, { enableMath: true }),
    [markdownSource, mathRevision]
  );

  // 行/列锚点执行（对齐 DSH openResource line 参数 + 代码导航按列定位）：
  // - 纯文本/代码视图有锚点：翻页至目标行 → 记录 activeAnchor（渲染列字符），
  //   由滚动 effect 一次性应答；
  // - Markdown 渲染态无锚点：挂起，切纯文本时执行；
  // - 字节/目录/不支持视图不消费行号（对齐 DSH byte-mode）；
  // - 目标行超 EOF：机械事实，静默丢弃。
  useEffect(() => {
    if (pending === null) return;
    if (phase.kind !== "text") {
      if (phase.kind !== "loading") setPending(null);
      return;
    }
    const isMd = MD_EXT.test(path);
    if (isMd && !plainMode) return; // 挂起
    const last = phase.pages[phase.pages.length - 1];
    const lastLine = last.offset + last.lines.length - 1;
    if (pending.line <= lastLine) {
      setActiveAnchor({ line: pending.line, col: pending.col });
      setPending(null); // answered once（滚动/高亮由下方 effect 执行）
    } else if (!phase.eof && !phase.loadingMore && !phase.moreFailed) {
      void loadMore();
    } else if (phase.eof || phase.moreFailed) {
      setPending(null);
    }
  }, [pending, phase, plainMode, path, loadMore]);

  // 滚动 + 高亮：activeAnchor 落定后，行级 scrollIntoView + flash；列字符
  // （若在行内）flash + inline nearest 水平滚动（nowrap 代码视口直达列）。
  useEffect(() => {
    if (activeAnchor === null) return;
    if (phase.kind !== "text") return;
    const lineEl = rootRef.current?.querySelector(`[data-line="${activeAnchor.line}"]`);
    if (!lineEl) return;
    lineEl.scrollIntoView?.({ block: "center" });
    lineEl.classList.add("anchor-flash");
    if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
    flashTimerRef.current = window.setTimeout(
      () => lineEl.classList.remove("anchor-flash"),
      2000
    );
    const colEl =
      activeAnchor.col !== null ? lineEl.querySelector("[data-anchor-col]") : null;
    if (colEl) {
      colEl.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      colEl.classList.add("anchor-flash");
      window.setTimeout(() => colEl.classList.remove("anchor-flash"), 2000);
    }
  }, [activeAnchor, phase]);

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
        // 列锚点字符（仅当目标行已定位、列在行内；1-based）
        const anchorLine = activeAnchor?.line ?? null;
        const anchorCol = activeAnchor?.col ?? null;
        return (
          <div className="v2-preview-text">
            {showPlain ? (
              <div className={`v2-preview-lines ${wrap ? "wrap" : "nowrap"}`}>
                {phase.pages.flatMap((p) =>
                  p.lines.map((lineText, i) => {
                    const lineNo = p.offset + i;
                    const showColSpan =
                      anchorLine === lineNo &&
                      anchorCol !== null &&
                      anchorCol >= 1 &&
                      anchorCol <= lineText.length;
                    return (
                      <div className="v2-preview-line" key={`${p.offset}-${i}`} data-line={lineNo}>
                        <span className="v2-preview-lineno">{lineNo}</span>
                        <span className="v2-preview-line-text">
                          {showColSpan ? (
                            // 列锚点行保持字符级切片（锚定优先；高亮暂让位）
                            <>
                              {lineText.slice(0, anchorCol! - 1)}
                              <span className="v2-preview-anchor-col" data-anchor-col>
                                {lineText[anchorCol! - 1]}
                              </span>
                              {lineText.slice(anchorCol!)}
                            </>
                          ) : lineText ? (
                            // 语法高亮（对齐聊天代码块 shiki-token 体系；
                            // highlightCode 自带 HTML 转义，输入为单行源码）
                            <span
                              dangerouslySetInnerHTML={{
                                __html: highlightCode(lineText),
                              }}
                            />
                          ) : (
                            " "
                          )}
                        </span>
                      </div>
                    );
                  })
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
      {isText && isMd && !plainMode && pending !== null ? (
        <div className="v2-preview-line-pending" role="status">
          {zh.previewLinePending.replace("{n}", String(pending.line))}
        </div>
      ) : null}
      {stale !== null && (phase.kind === "text" || phase.kind === "bytes") ? (
        <div className="v2-preview-stale" role="status" data-testid="preview-stale">
          <span>
            {stale.observed === null
              ? zh.previewStaleAbsent
              : zh.previewStaleNotice}
          </span>
          <button
            type="button"
            className="v2-btn ghost"
            onClick={() => {
              setPath(tabPath);
              setReloadTick((t) => t + 1);
            }}
          >
            {zh.previewStaleReload}
          </button>
        </div>
      ) : null}
      {restartedHint ? (
        <div className="v2-preview-line-pending" role="status">{zh.previewRestarted}</div>
      ) : null}
      <div className="v2-preview-body">{renderBody()}</div>
    </div>
  );
}
