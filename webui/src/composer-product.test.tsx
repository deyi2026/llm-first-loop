import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { conversationStore } from "./core/conversation";
import { sessionStore } from "./core/stores";

function doneStream(body: Record<string, unknown> = { session_id: "s1", final_answer: "ok" }) {
  const bytes = new TextEncoder().encode(`data: {"type":"done","data":${JSON.stringify(body)}}\n\n`);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

const REF_A = "attachment://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const REF_B = "attachment://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function modelResponse() {
  return {
    models: ["glm/glm-5.3", "cognilocal/qwen3.8-27b-mlx-8bit"],
    current: "glm/glm-5.3",
    catalog: [
      {
        id: "glm/glm-5.3",
        provider: "glm",
        model: "glm-5.3",
        context: 1_000_000,
        reasoning_capable: true,
        reasoning_control: "always_on_effort",
        reasoning_control_supported: true,
        reasoning_can_disable: false,
        reasoning_efforts: ["low", "high", "max"],
      },
      {
        id: "cognilocal/qwen3.8-27b-mlx-8bit",
        provider: "cognilocal",
        model: "qwen3.8-27b-mlx-8bit",
        context: 262_144,
        reasoning_capable: true,
        reasoning_control: "chat_template",
        reasoning_control_supported: true,
        reasoning_can_disable: true,
        reasoning_efforts: ["low", "medium", "high", "max", "xhigh"],
      },
    ],
  };
}

function baseFetch(extra?: (url: string, init?: RequestInit) => Promise<Response | undefined> | Response | undefined) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const custom = await extra?.(url, init);
    if (custom) return custom;
    if (url.includes("/api/v1/models")) return new Response(JSON.stringify(modelResponse()), { status: 200 });
    if (url.includes("/api/v1/chat/stream")) return new Response(doneStream(), { status: 200 });
    return new Response(JSON.stringify({}), { status: 200 });
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStore.setCurrentSession("s1");
  sessionStore.setModel(null);
  sessionStore.setThinkingMode("auto");
  sessionStore.setReasoningEffort(null);
  conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("product composer", () => {
  for (const modifier of ["metaKey", "ctrlKey"] as const) {
    it(`${modifier} + Enter 在生成中把 Human Turn 入队而不是再次直发`, async () => {
      let queueBody: Record<string, unknown> | null = null;
      let directStreamCalls = 0;
      vi.stubGlobal("fetch", baseFetch((url, init) => {
        if (url.endsWith("/api/v1/chat/queue") && init?.method === "POST") {
          queueBody = JSON.parse(String(init.body ?? "{}"));
          return new Response(JSON.stringify({ queue_id: "q-shortcut", position: 1 }), { status: 202 });
        }
        if (url.includes("/api/v1/chat/queue?") && (!init?.method || init.method === "GET")) {
          return new Response(JSON.stringify({ items: [] }), { status: 200 });
        }
        if (url.includes("/api/v1/chat/stream")) {
          directStreamCalls += 1;
        }
        return undefined;
      }));
      conversationStore.setState({ streaming: true, queueItems: [] });
      render(<Composer />);
      const ta = screen.getByTestId("composer-input");
      fireEvent.change(ta, { target: { value: "生成中插话" } });
      fireEvent.keyDown(ta, { key: "Enter", [modifier]: true });
      await waitFor(() => expect(queueBody).not.toBeNull());
      expect(queueBody).toMatchObject({ session_id: "s1", message: "生成中插话" });
      expect(directStreamCalls).toBe(0);
      expect((ta as HTMLTextAreaElement).value).toBe("");
    });
  }
  it("同名多文件按唯一实例跟踪，不串 ref，并一次发送全部成功引用", async () => {
    let uploadCount = 0;
    let sent = "";
    vi.stubGlobal("fetch", baseFetch(async (url, init) => {
      if (url.includes("/api/v1/upload")) {
        uploadCount += 1;
        const ref = uploadCount === 1 ? REF_A : REF_B;
        return new Response(JSON.stringify({ status: "ok", attachment_ref: ref, source_filename: "same.txt", content_type: "text", size_bytes: 3 }), { status: 200 });
      }
      if (url.includes("/api/v1/chat/stream")) {
        sent = String(init?.body ?? "");
        return new Response(doneStream(), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    const a = new File(["one"], "same.txt", { type: "text/plain" });
    const b = new File(["two"], "same.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [a, b] } });
    await waitFor(() => expect(screen.getAllByText("same.txt")).toHaveLength(2));
    await waitFor(() => expect((screen.getByText("发送") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "分析" } });
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => expect(sent).not.toBe(""));
    const body = JSON.parse(sent);
    expect(body.attachments).toEqual([{ ref: REF_A }, { ref: REF_B }]);
  });

  it("pending 附件时禁止发送文字，避免静默丢附件", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) return new Promise<Response>(() => undefined);
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [new File(["wait"], "wait.txt", { type: "text/plain" })] },
    });
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "先发文字" } });
    await waitFor(() => expect(screen.getByText(/wait.txt/)).toBeInTheDocument());
    expect((screen.getByText("发送") as HTMLButtonElement).disabled).toBe(true);
  });

  it("上传网络失败会落为可见 error，不永久 pending", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) throw new TypeError("offline");
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    fireEvent.change(screen.getByTestId("file-input"), {
      target: { files: [new File(["x"], "offline.txt", { type: "text/plain" })] },
    });
    await waitFor(() => expect(screen.getByText(/offline.txt.*降级\/失败/)).toBeInTheDocument());
    expect(screen.getByText(/offline.txt.*降级\/失败/).getAttribute("title")).toContain("网络连接失败");
  });

  it("最近附件从资料入口显式加入，不重新上传", async () => {
    let uploadCalls = 0;
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/attachments/recent")) {
        return new Response(JSON.stringify({ attachments: [{ ref: REF_A, filename: "recent.pdf", size_bytes: 2048, content_type: "pdf" }] }), { status: 200 });
      }
      if (url.includes("/api/v1/upload")) uploadCalls += 1;
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    fireEvent.click(screen.getByText(/最近附件/));
    await waitFor(() => expect(screen.getByText("recent.pdf")).toBeInTheDocument());
    fireEvent.click(screen.getByText("recent.pdf"));
    await waitFor(() => expect(screen.queryByTestId("insert-popover")).toBeNull());
    expect(screen.getByText("recent.pdf")).toBeInTheDocument();
    expect(uploadCalls).toBe(0);
  });

  it("工作区文件经显式 import 转成 attachment ref", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/fs/tree")) {
        return new Response(JSON.stringify({ path: "/ws", parent: null, dirs: [], files: [{ name: "work.md", size: 20 }] }), { status: 200 });
      }
      if (url.includes("/api/v1/attachments/import-workspace")) {
        return new Response(JSON.stringify({ status: "ok", attachment_ref: REF_A, source_filename: "work.md", content_type: "markdown", size_bytes: 20 }), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    fireEvent.click(screen.getByText(/从工作区选择/));
    await waitFor(() => expect(screen.getByText("work.md")).toBeInTheDocument());
    fireEvent.click(screen.getByText("work.md"));
    await waitFor(() => expect(screen.queryByTestId("insert-popover")).toBeNull());
    expect(screen.getByText("work.md")).toBeInTheDocument();
  });

  it("拖放文件会走真实上传并形成附件卡", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) {
        return new Response(JSON.stringify({ status: "ok", attachment_ref: REF_A, source_filename: "drop.txt", content_type: "text", size_bytes: 4 }), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const bar = screen.getByTestId("composer-input").closest(".v2-composer-bar")!;
    fireEvent.drop(bar, { dataTransfer: { files: [new File(["drop"], "drop.txt", { type: "text/plain" })] } });
    await waitFor(() => expect(screen.getByText("drop.txt")).toBeInTheDocument());
  });

  it("粘贴图片按附件处理而不是把二进制塞入 textarea", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) {
        return new Response(JSON.stringify({ status: "ok", attachment_ref: REF_A, source_filename: "clip.png", content_type: "image", size_bytes: 3, result_text: "image" }), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const ta = screen.getByTestId("composer-input") as HTMLTextAreaElement;
    fireEvent.paste(ta, { clipboardData: { files: [new File(["img"], "clip.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByText("clip.png")).toBeInTheDocument());
    expect(ta.value).not.toContain("img");
  });

  it("超过10MB在浏览器端直接报错且不发 upload 请求", async () => {
    let uploadCalls = 0;
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) uploadCalls += 1;
      return undefined;
    }));
    render(<Composer />);
    fireEvent.click(screen.getByTestId("insert-button"));
    const oversized = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "huge.txt", { type: "text/plain" });
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [oversized] } });
    await waitFor(() => expect(screen.getByText(/huge.txt.*降级\/失败/)).toBeInTheDocument());
    expect(screen.getByText(/huge.txt.*降级\/失败/).getAttribute("title")).toContain("超过 10MB");
    expect(uploadCalls).toBe(0);
  });

  it("GLM always_on_effort 不伪装可关闭：展示最低；本地模型才展示关闭", async () => {
    vi.stubGlobal("fetch", baseFetch());
    render(<Composer />);
    await waitFor(() => expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("glm/glm-5.3"));
    fireEvent.click(screen.getByTestId("reasoning-button"));
    const popover = screen.getByTestId("reasoning-popover");
    expect(within(popover).queryByText("关闭")).toBeNull();
    expect(within(popover).getByText("最低")).toBeInTheDocument();
    fireEvent.click(within(popover).getByText("最低"));
    expect(sessionStore.getState().thinkingMode).toBe("off");
    expect(screen.getByTestId("reasoning-button").textContent).toContain("最低");

    fireEvent.change(screen.getByTestId("model-select"), { target: { value: "cognilocal/qwen3.8-27b-mlx-8bit" } });
    fireEvent.click(screen.getByTestId("reasoning-button"));
    if (!screen.queryByTestId("reasoning-popover")) fireEvent.click(screen.getByTestId("reasoning-button"));
    expect(within(screen.getByTestId("reasoning-popover")).getByText("关闭")).toBeInTheDocument();
  });
});
