import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { VideoPanel } from "./components/layout/VideoPanel";
import type { VideoStatus } from "./core/video-api";

const STATUS: VideoStatus = {
  config: { diffusion_model: "h3.gguf", text_encoder: "encoder.gguf", video_vae: "video.safetensors", audio_vae: "audio.safetensors", text_encoder_cpu: true, offload_to_cpu: true, timeout_s: 3600 },
  version: "v1", prerequisites_ready: true, missing: [], jobs: [],
};
const ok = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("H3 local video", () => {
  it("shows missing components and does not offer a runnable model", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ ...STATUS, prerequisites_ready: false, missing: ["视频 VAE"] })));
    render(<VideoPanel />);
    await screen.findByText(/尚缺少：视频 VAE/);
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat" } });
    expect(screen.getByRole("button", { name: "生成视频" })).toBeDisabled();
  });

  it("saves config with a revision and uses the new saved configuration", async () => {
    const calls: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)); calls.push(body);
        return ok({ ...STATUS, config: body.config, version: "v2" });
      }
      return ok(STATUS);
    }));
    render(<VideoPanel />);
    await screen.findByLabelText("H3 专用文本编码器");
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat" } });
    fireEvent.change(screen.getByLabelText("H3 专用文本编码器"), { target: { value: "new-encoder.gguf" } });
    expect(screen.getByRole("button", { name: "生成视频" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存视频配置" }));
    await screen.findByText(/视频配置已保存/);
    expect(calls).toEqual([{ expected_version: "v1", config: { ...STATUS.config, text_encoder: "new-encoder.gguf" } }]);
    expect(screen.getByRole("button", { name: "生成视频" })).toBeEnabled();
  });

  it("submits one generation with actual frame counts and preserves exact prompt", async () => {
    const calls: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/jobs") && init?.method === "POST") {
        const request = JSON.parse(String(init.body)); calls.push(request); return ok({ id: "a".repeat(32), status: "queued", request, output: null, error: null }, 202);
      }
      return ok(STATUS);
    }));
    render(<VideoPanel />);
    await screen.findByLabelText("视频描述");
    expect(screen.getByLabelText("视频模型")).toHaveValue("minimax-h3");
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat\nSound: rain" } });
    fireEvent.change(screen.getByLabelText("时长（24 fps）"), { target: { value: "124" } });
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));
    await screen.findByText("视频任务已启动。");
    expect(calls).toEqual([{ prompt: "cat\nSound: rain", width: 640, height: 384, frames: 124, steps: 8, seed: -1, references: [] }]);
  });

  it("restores running jobs, allows cancellation and keeps pending state honest", async () => {
    const id = "b".repeat(32);
    const running = { id, status: "running", request: { prompt: "slow cat" }, output: null, error: null };
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST" ? ok(running, 202) : ok({ ...STATUS, jobs: [running] }));
    vi.stubGlobal("fetch", fetch);
    render(<VideoPanel />);
    await screen.findByText("正在生成");
    fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
    await screen.findByText(/已请求取消/);
    expect(screen.getByText("正在生成")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(`/api/v1/video/jobs/${id}/cancel`, { method: "POST" });
  });

  it("renders only successful output with a video player and download", async () => {
    const id = "c".repeat(32);
    vi.stubGlobal("fetch", vi.fn(async () => ok({ ...STATUS, jobs: [{ id, status: "done", request: { prompt: "cat" }, error: null, output: { sha256: "sha", size_bytes: 123 } }] })));
    const view = render(<VideoPanel />);
    await screen.findByText("已生成");
    expect(view.container.querySelector("video")?.getAttribute("src")).toBe(`/api/v1/video/jobs/${id}/files/output`);
    expect(screen.getByRole("link", { name: "下载视频" })).toHaveAttribute("download");
  });

  it("shows a failed request without automatic replay", async () => {
    let posts = 0;
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") { posts += 1; return ok({ detail: "模型内存不足" }, 503); }
      return ok(STATUS);
    }));
    render(<VideoPanel />);
    await screen.findByLabelText("视频描述");
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat" } });
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("模型内存不足"));
    expect(posts).toBe(1);
  });

  it("retains the accepted job and cancel action when the first follow-up GET fails", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return ok({ id: "d".repeat(32), status: "queued", request: { prompt: "cat" }, output: null, error: null }, 202);
      reads += 1;
      return reads === 1 ? ok(STATUS) : ok({ detail: "temporary read failure" }, 503);
    }));
    render(<VideoPanel />);
    await screen.findByLabelText("视频描述");
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat" } });
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));
    await screen.findByText("temporary read failure");
    expect(screen.getByRole("button", { name: "取消生成" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "生成视频" })).toBeDisabled();
  });

  it("offers the real-qualified low-resolution preview without changing the saved model config", async () => {
    const calls: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        const request = JSON.parse(String(init.body)); calls.push(request);
        return ok({ id: "e".repeat(32), status: "queued", request, output: null, error: null }, 202);
      }
      return ok(STATUS);
    }));
    render(<VideoPanel />);
    await screen.findByLabelText("视频描述");
    fireEvent.change(screen.getByLabelText("视频描述"), { target: { value: "cat" } });
    fireEvent.click(screen.getByRole("button", { name: "使用低分辨率预览参数" }));
    fireEvent.click(screen.getByRole("button", { name: "生成视频" }));
    await screen.findByText("视频任务已启动。");
    expect(calls).toEqual([{ prompt: "cat", width: 256, height: 256, frames: 22, steps: 4, seed: -1, references: [] }]);
  });
});
