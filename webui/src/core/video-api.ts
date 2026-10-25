import { api } from "./api";

export interface VideoConfig {
  diffusion_model: string;
  text_encoder: string;
  video_vae: string;
  audio_vae: string;
  text_encoder_cpu: boolean;
  offload_to_cpu: boolean;
  timeout_s: number;
}
export interface VideoJob {
  id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  created_at: number;
  error: string | null;
  request: { prompt: string; width: number; height: number; frames: number };
  output: { sha256: string; size_bytes: number } | null;
}
export interface VideoStatus {
  config: VideoConfig;
  version: string;
  prerequisites_ready: boolean;
  missing: string[];
  jobs: VideoJob[];
}

export async function videoApi<T>(path = "", options?: RequestInit): Promise<T> {
  const { status, data } = await api<T & { detail?: unknown }>(`/api/v1/video${path}`, options);
  if (status < 200 || status >= 300) {
    throw new Error(typeof data.detail === "string" ? data.detail : status === 0 ? "网络连接失败，请刷新任务列表确认状态。" : `视频请求失败（${status}）`);
  }
  return data;
}

export const videoJson = (method: string, value: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
