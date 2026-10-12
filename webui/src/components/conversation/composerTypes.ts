export type AttachStatus = "ok" | "pending" | "degraded" | "error";

export interface ComposerAttachment {
  id: string;
  filename: string;
  result_text: string;
  preview?: string;
  status: AttachStatus;
  detail?: string;
  attachment_ref?: string;
  content_type?: string;
  size_bytes?: number;
  sha256?: string;
  /** 仅 Composer 本地使用：超长粘贴无损转附件后，允许用户撤销并恢复原文。 */
  restorable_text?: string;
}
