// 出产物文件预览模态（对齐 DSH client-ui-sidebar-documentpreview 的能力面，
// 落在 LFL 现有模态壳内）：文本分页 + 代码行号、Markdown 渲染、图片 data URI、
// pdf/html Blob iframe（html 带 sandbox="allow-scripts" 且无 allow-same-origin，
// 与 DSH 同规：脚本不可触父页面源）、目录单层浏览、已知二进制空态、重载。
// 程序只做机械分流（扩展名/响应 type），不判断内容语义。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchFilePreview,
  type FilePreview,
  type FilePreviewFailure,
} from "../core/api";
import { renderMarkdown } from "../core/markdown";
import { zh } from "../i18n/zh";

const MD_EXT = /\.(md|markdown)$/i;

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
    case "image_too_large":
      return err.detail || zh.previewTooLarge;
    case "out_of_bounds":
      return zh.previewOutOfBounds;
    case "file_not_found":
    case "dir_not_found":
      return zh.previewNotFound;
    case "ambiguous_path":
      return err.detail || zh.previewAmbiguous;
    case "invalid_range":
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

export function FilePreviewModal({
  path: initialPath,
  onClose,
}: {
  path: string;
  onClose: () => void;
}) {
  const [path, setPath] = useState(initialPath);
  const [phase, setPhase] = useState<
    | { kind: "loading" }
    | { kind: "error"; text: string }
    | { kind: "text"; size: number; pages: TextPage[]; eof: boolean; loadingMore: boolean }
    | ({ kind: "bytes" } & BytesState)
    | { kind: "dir"; parent: string; dirs: string[]; files: Array<{ name: string; size: number }> }
    | { kind: "unsupported"; ext: string }
  >({ kind: "loading" });
  // md 默认渲染视图；html/pdf 为字节视图。wrap 仅作用于纯文本/代码视图。
  const [plainMode, setPlainMode] = useState(false);
  const [wrap, setWrap] = useState(true);
  const [reloadTick, setReloadTick] = useState(0);
  const reqIdRef = useRef(0);

  // Escape 关闭（与 mask 点击一致）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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
    void fetchFilePreview(path).then((result) => {
      if (reqIdRef.current !== reqId) return; // 迟到响应丢弃
      applyFirst(result);
    });
  }, [path, reloadTick, applyFirst]);

  const loadMore = useCallback(async () => {
    if (phase.kind !== "text" || phase.eof || phase.loadingMore) return;
    const last = phase.pages[phase.pages.length - 1];
    const nextOffset = last.offset + last.lines.length;
    setPhase({ ...phase, loadingMore: true });
    const reqId = reqIdRef.current;
    const result = await fetchFilePreview(path, nextOffset);
    if (reqIdRef.current !== reqId) return;
    if (result.status !== 200) {
      // 加载更多失败：保留已载内容 + 如实提示（对齐 DSH：later failure retains content）
      setPhase({ ...phase, loadingMore: false, eof: false });
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
          }
    );
  }, [phase, path]);

  // Blob URL 生命周期归 effect 管：pdf/html 相位建立、离开/替换时撤销；
  // image 用 data URI 直渲染，不经 Blob（避免多余对象 URL 生命周期）。
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    if (phase.kind !== "bytes" || phase.type === "image") {
      setBlobUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
      return;
    }
    const bytes = Uint8Array.from(atob(phase.content_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: phase.mime }));
    setBlobUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return url;
    });
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [phase]);

  const mdHtml = useMemo(() => {
    if (phase.kind !== "text") return "";
    return renderMarkdown(
      phase.pages.map((p) => p.lines.join("\n")).join("\n"),
      undefined,
      { enableMath: true }
    );
  }, [phase]);

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
                  p.lines.map((line, i) => (
                    <div className="v2-preview-line" key={`${p.offset}-${i}`}>
                      <span className="v2-preview-lineno">{p.offset + i}</span>
                      <span className="v2-preview-line-text">{line || " "}</span>
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
    <div className="v2-preview-mask" data-testid="file-preview" onClick={onClose}>
      <div className="v2-preview-card" onClick={(e) => e.stopPropagation()}>
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
              onClick={() => setReloadTick((t) => t + 1)}
              data-testid="preview-reload"
            >
              ↻
            </button>
          </span>
          <button type="button" className="v2-preview-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="v2-preview-body">{renderBody()}</div>
      </div>
    </div>
  );
}
