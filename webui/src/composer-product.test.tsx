import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { MODEL_CATALOG_CHANGED_EVENT } from "./core/chat";
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
        reasoning_default_effort: "max",
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

  it("模型下拉使用后端 display_name 展示网页版 GPT，同时保持规范 model id", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (!url.includes("/api/v1/models")) return undefined;
      return new Response(JSON.stringify({
        models: ["glm/glm-5.3", "chatgpt-web/web-gpt"],
        current: "glm/glm-5.3",
        catalog: [
          ...modelResponse().catalog.slice(0, 1),
          {
            id: "chatgpt-web/web-gpt",
            provider: "chatgpt-web",
            model: "web-gpt",
            display_name: "网页版 GPT",
            context: 262_144,
            reasoning_capable: true,
            reasoning_control: "provider_owned",
            reasoning_control_supported: true,
            reasoning_can_disable: false,
            reasoning_efforts: ["instant", "medium", "high", "xhigh", "pro"],
            reasoning_default_effort: "high",
          },
        ],
      }), { status: 200 });
    }));
    render(<Composer />);

    const select = (await screen.findByTestId("model-select")) as HTMLSelectElement;
    expect(within(select).getByRole("option", { name: "网页版 GPT" })).toHaveValue("chatgpt-web/web-gpt");
    fireEvent.change(select, { target: { value: "chatgpt-web/web-gpt" } });
    expect(sessionStore.getState().model).toBe("chatgpt-web/web-gpt");

    fireEvent.click(screen.getByTestId("reasoning-button"));
    const popover = screen.getByTestId("reasoning-popover");
    const xhigh = within(popover).getByRole("button", { name: "xhigh" });
    expect(xhigh).toBeEnabled();
    fireEvent.click(xhigh);
    expect(sessionStore.getState().thinkingMode).toBe("on");
    expect(sessionStore.getState().reasoningEffort).toBe("xhigh");
    expect(screen.getByTestId("reasoning-button").textContent).toContain("xhigh");
  });

  it("DeepSeek 网页版只暴露 instant/high 两档 provider-owned 推理", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (!url.includes("/api/v1/models")) return undefined;
      return new Response(JSON.stringify({
        models: ["glm/glm-5.3", "deepseek-web/web-deepseek"],
        current: "glm/glm-5.3",
        catalog: [
          ...modelResponse().catalog.slice(0, 1),
          {
            id: "deepseek-web/web-deepseek",
            provider: "deepseek-web",
            model: "web-deepseek",
            display_name: "DeepSeek 网页版",
            context: 131_072,
            reasoning_capable: true,
            reasoning_control: "provider_owned",
            reasoning_control_supported: true,
            reasoning_can_disable: false,
            reasoning_efforts: ["instant", "high"],
            reasoning_default_effort: "high",
          },
        ],
      }), { status: 200 });
    }));
    render(<Composer />);

    const select = (await screen.findByTestId("model-select")) as HTMLSelectElement;
    expect(within(select).getByRole("option", { name: "DeepSeek 网页版" })).toHaveValue(
      "deepseek-web/web-deepseek"
    );
    fireEvent.change(select, { target: { value: "deepseek-web/web-deepseek" } });
    fireEvent.click(screen.getByTestId("reasoning-button"));
    const popover = screen.getByTestId("reasoning-popover");
    expect(within(popover).getByRole("button", { name: "instant" })).toBeEnabled();
    expect(within(popover).getByRole("button", { name: "high" })).toBeEnabled();
    expect(within(popover).queryByRole("button", { name: "xhigh" })).toBeNull();
    expect(within(popover).queryByRole("button", { name: "pro" })).toBeNull();

    fireEvent.click(within(popover).getByRole("button", { name: "instant" }));
    expect(sessionStore.getState().thinkingMode).toBe("on");
    expect(sessionStore.getState().reasoningEffort).toBe("instant");
    expect(screen.getByTestId("reasoning-button").textContent).toContain("instant");
  });

  it("附件插入菜单支持点击外侧和 Escape 关闭，避免移动端浮层滞留", () => {
    vi.stubGlobal("fetch", baseFetch());
    render(<Composer />);

    const trigger = screen.getByTestId("insert-button");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    expect(screen.getByTestId("insert-popover")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId("insert-popover")).toBeNull();

    fireEvent.click(trigger);
    expect(screen.getByTestId("insert-popover")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("insert-popover")).toBeNull();
  });

  it("推理菜单支持点击外侧和 Escape 关闭并声明 popup 语义", async () => {
    vi.stubGlobal("fetch", baseFetch());
    render(<Composer />);
    const trigger = await screen.findByTestId("reasoning-button");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");

    fireEvent.click(trigger);
    expect(screen.getByTestId("reasoning-popover")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId("reasoning-popover")).toBeNull();

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("reasoning-popover")).toBeNull();
  });

  it("provider catalog 变更事件会刷新下拉且不覆盖 stale session 选择", async () => {
    let catalog = modelResponse();
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/models")) {
        return new Response(JSON.stringify(catalog), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const select = await screen.findByTestId("model-select") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("glm/glm-5.3"));

    catalog = {
      ...modelResponse(),
      models: ["cognilocal/qwen3.8-27b-mlx-8bit"],
      current: "glm/glm-5.3",
      current_available: false,
      catalog: modelResponse().catalog.filter((row) => row.id !== "glm/glm-5.3"),
    } as ReturnType<typeof modelResponse> & { current_available: boolean };
    window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED_EVENT));

    await waitFor(() => {
      expect(select.value).toBe("glm/glm-5.3");
      const stale = within(select).getByRole("option", { name: /当前不可用/ }) as HTMLOptionElement;
      expect(stale.disabled).toBe(true);
      expect(within(select).getByRole("option", { name: "qwen3.8-27b-mlx-8bit" })).toBeInTheDocument();
    });
    expect(sessionStore.getState().model).toBe("glm/glm-5.3");
  });

  it("模型目录瞬时读取失败仍显示当前会话模型，不把UI伪装成默认模型", async () => {
    let fail = false;
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/models")) {
        return fail
          ? new Response(JSON.stringify({ detail: "temporary failure" }), { status: 503 })
          : new Response(JSON.stringify(modelResponse()), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const select = await screen.findByTestId("model-select") as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("glm/glm-5.3"));

    fail = true;
    window.dispatchEvent(new Event(MODEL_CATALOG_CHANGED_EVENT));

    await waitFor(() => {
      expect(sessionStore.getState().model).toBe("glm/glm-5.3");
      expect(select.value).toBe("glm/glm-5.3");
      expect(within(select).getByRole("option", { name: /当前选择.*目录暂不可用/ })).toBeInTheDocument();
    });
  });
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
    await waitFor(() => expect(screen.getByText(/offline.txt.*失败/)).toBeInTheDocument());
    // 失败原因必须正文可见：手机/触屏没有 hover，不能只藏在 title tooltip。
    expect(screen.getByText("网络连接失败，附件未上传。")).toBeInTheDocument();
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

  it("超长文本粘贴无损转为附件，输入框指令不被重复发送", async () => {
    let uploadFilename = "";
    let uploadData = "";
    let sentBody: Record<string, unknown> | null = null;
    vi.stubGlobal("fetch", baseFetch((url, init) => {
      if (url.includes("/api/v1/upload")) {
        const uploadBody = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        uploadFilename = String(uploadBody.filename ?? "");
        uploadData = String(uploadBody.data ?? "");
        return new Response(JSON.stringify({
          status: "ok",
          attachment_ref: REF_A,
          source_filename: uploadFilename,
          content_type: "text",
          size_bytes: 20_000,
        }), { status: 200 });
      }
      if (url.includes("/api/v1/chat/stream")) {
        sentBody = JSON.parse(String(init?.body ?? "{}"));
        return new Response(doneStream(), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const ta = screen.getByTestId("composer-input") as HTMLTextAreaElement;
    const longText = "x".repeat(20_000);
    fireEvent.change(ta, { target: { value: "请分析这个附件" } });
    ta.setSelectionRange(ta.value.length, ta.value.length);
    fireEvent.paste(ta, {
      clipboardData: {
        files: [],
        getData: (type: string) => type === "text/plain" ? longText : "",
      },
    });

    await waitFor(() => expect(uploadFilename).not.toBe(""));
    expect(uploadFilename).toMatch(/^pasted-text-\d+\.txt$/);
    expect(uploadData).toBe(btoa(longText));
    expect(ta.value).toBe("请分析这个附件");
    expect(screen.getByTestId("composer-hint").textContent).toContain("已作为文本附件添加");
    await waitFor(() => expect(screen.getByText(/^pasted-text-/)).toBeInTheDocument());

    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => expect(sentBody).not.toBeNull());
    expect(sentBody).toMatchObject({
      message: "请分析这个附件",
      attachments: [{ ref: REF_A }],
    });
    expect(JSON.stringify(sentBody)).not.toContain(longText);
  });

  it("超长粘贴附件可撤销并把原文恢复到当前光标位置", async () => {
    vi.stubGlobal("fetch", baseFetch((url) => {
      if (url.includes("/api/v1/upload")) {
        return new Response(JSON.stringify({
          status: "ok",
          attachment_ref: REF_A,
          source_filename: "pasted-text.txt",
          content_type: "text",
          size_bytes: 20_000,
        }), { status: 200 });
      }
      return undefined;
    }));
    render(<Composer />);
    const ta = screen.getByTestId("composer-input") as HTMLTextAreaElement;
    const longText = "y".repeat(20_000);
    fireEvent.change(ta, { target: { value: "任务：" } });
    ta.setSelectionRange(ta.value.length, ta.value.length);
    fireEvent.paste(ta, {
      clipboardData: {
        files: [],
        getData: (type: string) => type === "text/plain" ? longText : "",
      },
    });
    await waitFor(() => expect(screen.getByText("恢复到输入框")).toBeInTheDocument());

    fireEvent.click(screen.getByText("恢复到输入框"));
    await waitFor(() => expect(ta.value).toBe(`任务：${longText}`));
    expect(screen.queryByText("恢复到输入框")).toBeNull();
    expect(screen.getByTestId("composer-hint").textContent).toContain("已恢复到输入框");
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
    await waitFor(() => expect(screen.getByText(/huge.txt.*失败/)).toBeInTheDocument());
    expect(screen.getByText(/文件超过 10MB 上限/)).toBeInTheDocument();
    expect(uploadCalls).toBe(0);
  });

  it("GLM always_on_effort 不伪装可关闭：展示最低；本地模型才展示关闭", async () => {
    vi.stubGlobal("fetch", baseFetch());
    render(<Composer />);
    await waitFor(() => expect((screen.getByTestId("model-select") as HTMLSelectElement).value).toBe("glm/glm-5.3"));
    expect(screen.getByTestId("reasoning-button").textContent).toContain("自动(max)");
    fireEvent.click(screen.getByTestId("reasoning-button"));
    const popover = screen.getByTestId("reasoning-popover");
    expect(within(popover).queryByText("关闭")).toBeNull();
    expect(within(popover).getByText("最低")).toBeInTheDocument();
    expect(within(popover).getByRole("button", { name: "low" })).toBeInTheDocument();
    expect(within(popover).getByRole("button", { name: "high" })).toBeInTheDocument();
    expect(within(popover).getByRole("button", { name: "max" })).toBeInTheDocument();
    expect(within(popover).queryByRole("button", { name: "medium" })).toBeNull();
    expect(within(popover).getByText(/自动默认：max/)).toBeInTheDocument();
    fireEvent.click(within(popover).getByText("最低"));
    expect(sessionStore.getState().thinkingMode).toBe("off");
    expect(screen.getByTestId("reasoning-button").textContent).toContain("最低");

    fireEvent.change(screen.getByTestId("model-select"), { target: { value: "cognilocal/qwen3.8-27b-mlx-8bit" } });
    fireEvent.click(screen.getByTestId("reasoning-button"));
    if (!screen.queryByTestId("reasoning-popover")) fireEvent.click(screen.getByTestId("reasoning-button"));
    expect(within(screen.getByTestId("reasoning-popover")).getByText("关闭")).toBeInTheDocument();
  });
});
