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
}
