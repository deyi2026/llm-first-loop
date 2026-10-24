// P2-4（安全建议书 回收站+撤销）：删除进回收站后的"撤销"提示条。
// 数据流：FileTree doDelete 成功且后端 status==="trashed" 时挂载（携带 undo_token
// 与过期时间戳）；"撤销"按钮 → onUndo（FileTree 调 fsRestore，成功后刷新父目录）；
// 倒计时归零（undo_token 过期）自动收起；Esc / × 手动关闭。
// 无障碍：撤销按钮原生可聚焦且 autoFocus；容器响应 Escape；文案 role=status，错误 role=alert。
import { useEffect, useRef, useState } from "react";

function fmtRemain(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

export function UndoDeleteToast({
  name,
  expiresAt,
  busy = false,
  error = "",
  onUndo,
  onClose,
}: {
  /** 被删除条目名（展示用；token 不出现在文案里）。 */
  name: string;
  /** 撤销窗口截止时间戳（ms）。 */
  expiresAt: number;
  /** 撤销请求进行中（禁用按钮，防重复提交）。 */
  busy?: boolean;
  /** 撤销失败的中文错误（fsRestore 透出）。 */
  error?: string;
  onUndo: () => void;
  onClose: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  // 每秒刷新倒计时；归零即 undo_token 过期，自动收起（不再提供已失效的撤销入口）。
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (Date.now() >= expiresAt) closeRef.current();
  }, [now, expiresAt]);

  return (
    <div className="v2-tree-undo" data-testid="undo-delete-toast">
      <div
        className="v2-tree-inline-form"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <span className="v2-tree-undo-text" role="status">
          已移入回收站：{name}（{fmtRemain(expiresAt - now)} 内可撤销）
        </span>
        <button
          type="button"
          className="v2-btn primary"
          data-testid="undo-delete-btn"
          disabled={busy}
          autoFocus
          onClick={onUndo}
        >
          撤销
        </button>
        <button type="button" className="v2-icon-btn" title="关闭" aria-label="关闭撤销提示" onClick={onClose}>
          ×
        </button>
      </div>
      {error ? (
        <div className="v2-tree-action-error" role="alert" data-testid="undo-error">
          {error}
        </div>
      ) : null}
    </div>
  );
}
