// Web V2（对齐 DSH）：跨组件快捷键/操作事件总线
// - composer-fill: 回填输入框（↑ 编辑上一条 / user 消息"重发"→ 回填可修改后发送）
// - search-focus: 聚焦会话内搜索框（⌘K / Ctrl+K）

export const EVT_COMPOSER_FILL = "lfl:composer-fill";
export const EVT_SEARCH_FOCUS = "lfl:search-focus";

export function fillComposer(text: string): void {
  window.dispatchEvent(new CustomEvent(EVT_COMPOSER_FILL, { detail: { text } }));
}

export function focusSearch(): void {
  window.dispatchEvent(new CustomEvent(EVT_SEARCH_FOCUS));
}
