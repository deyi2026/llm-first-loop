import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LocalRuntimePanel } from "./components/layout/LocalRuntimePanel";
import type { LocalRuntimeStatus } from "./core/api";

const STATUS: LocalRuntimeStatus = {
  backend: "llama",
  port: 8901,
  alias: "qwen3.8-flash-next",
  ctx: 65536,
  model_path: "/m/unsloth/Qwen3.8-Flash-Next-GGUF",
  state: { launchd: "running", pid: 63923, rss_gb: 54.2, port_listening: true, health: true },
  free_gb: 12.4,
  wire_model_ids: ["qwen3.8-flash-next"],
  provider: { id: "cognilocal", base_url: "http://localhost:8901/v1" },
  suggested_model_ref: "cognilocal/qwen3.8-flash-next",
  stashed_backends: ["mlx"],
  models: [
    { name: "unsloth/Qwen3.8-Flash-Next-GGUF", size_gb: 77.2, kind: "gguf", shards: "3/3", shards_ok: true, mmproj: true, active: true },
    { name: "lmstudio-community/Qwen3.8-27B-MLX-8bit", size_gb: 27.5, kind: "mlx", shards: null, shards_ok: null, mmproj: null, active: false },
    { name: "empero-ai/Broken-Shards-GGUF", size_gb: 20, kind: "gguf", shards: "1/3", shards_ok: false, mmproj: false, active: false },
  ],
  job: null,
};

function ok(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  vi.stubGlobal("confirm", vi.fn(() => true));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("local runtime panel", () => {
  it("展示运行时状态、模型类型与 provider 接入；当前模型禁用切换", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok(STATUS)));
    render(<LocalRuntimePanel />);
    await waitFor(() => expect(screen.getByTestId("local-runtime")).toBeInTheDocument());
    expect(screen.getByText(/cognilocal/)).toBeInTheDocument();
    expect(screen.getAllByText("GGUF").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("MLX").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("当前").length).toBeGreaterThanOrEqual(1);
    // 三个模型行：仅完整分片的非当前模型可切
    const switchButtons = screen.getAllByRole("button", { name: "切换" });
    expect(switchButtons).toHaveLength(3);
    expect((switchButtons[0] as HTMLButtonElement).disabled).toBe(true); // active
    expect((switchButtons[1] as HTMLButtonElement).disabled).toBe(false); // mlx 可切
    expect((switchButtons[2] as HTMLButtonElement).disabled).toBe(true); // 分片缺失
  });

  it("切换动作提交 job；完成后展示同步结果并回调目录刷新", async () => {
    const posts: unknown[] = [];
    let synced = 0;
    let latestJob: unknown = null;  // 与真实后端一致：status 内嵌最新 job
    const runningJob = { id: "job1", action: "switch_model", label: "切换模型", status: "running", started_at: 1, duration_s: 0, rc: null, output_tail: [], result: null, error: null };
    const doneJob = { id: "job1", action: "switch_model", label: "切换模型", status: "done", started_at: 1, duration_s: 63.2, rc: 0, output_tail: ["switch plan:", "warmup ok"], result: { registry_synced: true, model_ref: "cognilocal/qwen3.8-27b" }, error: null };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/local-runtime") return ok({ ...STATUS, job: latestJob });
      if (url === "/api/v1/local-runtime/jobs" && init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        latestJob = runningJob;
        return ok({ job: runningJob }, 202);
      }
      if (url === "/api/v1/local-runtime/jobs/job1") {
        latestJob = doneJob;
        return ok(doneJob);
      }
      return ok({});
    }));
    render(<LocalRuntimePanel onSynced={() => { synced += 1; }} />);
    await waitFor(() => expect(screen.getByText(/Qwen3.8-27B-MLX-8bit/)).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "切换" })[1]);
    await vi.waitFor(() => expect(posts).toEqual([{ action: "switch_model", model: "lmstudio-community/Qwen3.8-27B-MLX-8bit" }]));
    // 轮询到 done 后：同步消息 + onSynced 回调（fake timers 推进 2.5s 轮询周期）
    vi.useFakeTimers();
    await vi.advanceTimersByTimeAsync(2600);
    await vi.waitFor(() => expect(screen.getByText(/已同步到注册表：cognilocal\/qwen3.8-27b/)).toBeInTheDocument());
    vi.useRealTimers();
    expect(synced).toBe(1);
    expect(screen.getByText(/warmup ok/)).toBeInTheDocument();
  });

  it("stop 需 confirm 且携带 confirm=true", async () => {
    let confirmCalled = false;
    vi.stubGlobal("confirm", vi.fn(() => { confirmCalled = true; return true; }));
    const posts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/local-runtime") return ok(STATUS);
      if (url === "/api/v1/local-runtime/jobs" && init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return ok({ job: { id: "job2", action: "stop", label: "停止服务", status: "done", started_at: 1, duration_s: 2, rc: 0, output_tail: ["bootout ok"], result: null, error: null } }, 202);
      }
      return ok({});
    }));
    render(<LocalRuntimePanel />);
    await waitFor(() => expect(screen.getByText("停止")).toBeInTheDocument());
    fireEvent.click(screen.getByText("停止"));
    await vi.waitFor(() => expect(posts).toEqual([{ action: "stop", confirm: true }]));
    expect(confirmCalled).toBe(true);
    await vi.waitFor(() => expect(screen.getByText("完成（2s）")).toBeInTheDocument());
  });

  it("拒绝确认时不发起 stop", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const posts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/local-runtime") return ok(STATUS);
      if (url === "/api/v1/local-runtime/jobs" && init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
      }
      return ok({});
    }));
    render(<LocalRuntimePanel />);
    await waitFor(() => expect(screen.getByText("停止")).toBeInTheDocument());
    fireEvent.click(screen.getByText("停止"));
    // 拒绝确认：无任何 job 提交、无消息变化
    await waitFor(() => expect(screen.queryByText(/正在…/)).toBeNull());
    expect(posts).toEqual([]);
  });
});
