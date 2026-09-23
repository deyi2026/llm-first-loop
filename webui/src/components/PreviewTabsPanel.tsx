// 右侧栏预览页签面板（对齐 DSH 右侧栏 tab 语义）：
// 完整路径 = tab 身份；tab 标题 = basename；全部 tab 常驻挂载（display 切换）
// 以保留每 tab 的分页/滚动/Blob 状态；关闭即卸载释放。

import { previewTabsStore, usePreviewTabs } from "../core/stores";
import { zh } from "../i18n/zh";
import { FilePreviewView } from "./FilePreviewView";

function basename(p: string): string {
  const parts = p.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : p;
}

export function PreviewTabsPanel() {
  const { tabs, active } = usePreviewTabs();
  if (tabs.length === 0) {
    return (
      <div className="v2-placeholder" data-testid="preview-tabs-empty">
        {zh.previewTabsEmpty}
      </div>
    );
  }
  return (
    <div className="v2-preview-tabs" data-testid="preview-tabs">
      <div className="v2-preview-tabstrip" role="tablist">
        {tabs.map((t) => (
          <div
            key={t.path}
            className={`v2-preview-tab ${t.path === active ? "active" : ""}`}
            role="tab"
            aria-selected={t.path === active}
          >
            <button
              type="button"
              className="v2-preview-tab-btn"
              title={t.path}
              onClick={() => previewTabsStore.setActive(t.path)}
            >
              {basename(t.path)}
              {t.line !== null ? <span className="v2-preview-tab-line">:{t.line}</span> : null}
            </button>
            <button
              type="button"
              className="v2-preview-tab-close"
              aria-label={`${zh.previewCloseTab} ${basename(t.path)}`}
              onClick={() => previewTabsStore.close(t.path)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <div className="v2-preview-tabbodies">
        {tabs.map((t) => (
          <div
            key={t.path}
            className={`v2-preview-tabbody ${t.path === active ? "active" : ""}`}
            hidden={t.path !== active}
          >
            <FilePreviewView path={t.path} line={t.line} lineSeq={t.seq} />
          </div>
        ))}
      </div>
    </div>
  );
}
