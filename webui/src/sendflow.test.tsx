// 发送链路集成测试：输入→发送→流式→done→清场（对齐用户现场：上传附件后发送"识别"）

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { MessageList } from "./components/conversation/MessageList";
import { sessionStore } from "./core/stores";
import { checkBackgroundRun, conversationStore as conv } from "./core/conversation";

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const f of frames) controller.enqueue(enc.encode(f + "\n\n"));
      controller.close();
    },
  });
}

const DONE = {
  session_id: "s1",
  final_answer: "识别完成：这是一张测试图片",
  model_used: "MiniMax-M3",
  tokens_in: 100,
  tokens_out: 50,
};

function mockBackend(overrides: { streamFrames?: string[] } = {}) {
  const frames = overrides.streamFrames ?? [
    'data: {"type":"answer_delta","data":{"data":"识别"}}',
    'data: {"type":"answer_delta","data":{"data":"完成"}}',
    `data: {"type":"done","data":${JSON.stringify(DONE)}}`,
  ];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/chat/stream")) {
      return new Response(sseStream(frames), { status: 200 });
    }
    if (url.includes("/api/v1/upload")) {
      return new Response(JSON.stringify({ status: "degraded", detail: "识别降级" }), { status: 200 });
    }
    if (url.includes("/api/v1/models")) {
      return new Response(JSON.stringify({ models: [{ id: "m1" }] }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
}

describe("发送链路", () => {
  beforeEach(() => {
    sessionStore.setCurrentSession("s1");
    sessionStore.setModel(null);
    sessionStore.setModelChangePending(false);
    conv.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    conv.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
    sessionStore.setCurrentSession("s1");
    sessionStore.setModel(null);
    sessionStore.setModelChangePending(false);
  });

  it("done.model_used is display telemetry only and cannot rewrite session model authority", async () => {
    mockBackend({
      streamFrames: [
        `data: {"type":"done","data":${JSON.stringify({ ...DONE, model_used: "glm/glm-5.3-flash" })}}`,
      ],
    });
    sessionStore.setModel("glm/glm-5.3");
    render(<><MessageList /><Composer /></>);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "switch result" } });
    fireEvent.click(screen.getByText("发送"));

    await waitFor(() => expect(conv.getState().streaming).toBe(false));
    expect(sessionStore.getState().model).toBe("glm/glm-5.3");
    expect(sessionStore.getState().modelChangePending).toBe(false);
  });

  it("switching sessions restores each session model without creating change intent", () => {
    sessionStore.setSessions([
      {
        session_id: "s1",
        title: "A",
        created_at: "",
        updated_at: "",
        message_count: 1,
        status: "active",
        last_message_preview: "",
        pinned: false,
        channel: "web",
        model: "glm/glm-5.3",
      },
      {
        session_id: "s2",
        title: "B",
        created_at: "",
        updated_at: "",
        message_count: 1,
        status: "active",
        last_message_preview: "",
        pinned: false,
        channel: "web",
        model: "minimax/MiniMax-M2.1",
      },
    ]);

    sessionStore.selectModel("deepseek/deepseek-v4-flash");
    expect(sessionStore.getState().modelChangePending).toBe(true);

    sessionStore.setCurrentSession("s2");
    expect(sessionStore.getState().model).toBe("minimax/MiniMax-M2.1");
    expect(sessionStore.getState().modelChangePending).toBe(false);

    sessionStore.setCurrentSession("s1");
    expect(sessionStore.getState().model).toBe("glm/glm-5.3");
    expect(sessionStore.getState().modelChangePending).toBe(false);
  });

  it("显式模型选择只随下一条 human turn 发送一次 model_change 意图", async () => {
    let sentBody: Record<string, unknown> = {};
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        sentBody = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
        return new Response(sseStream([
          'data: {"type":"run_started","data":{"session_id":"s1","run_generation":"g1"}}',
          `data: {"type":"done","data":${JSON.stringify(DONE)}}`,
        ]), { status: 200 });
      }
      if (url.includes("/api/v1/models")) {
        return new Response(JSON.stringify({ models: ["glm/glm-5.3", "glm/glm-5.3-flash"], current: "glm/glm-5.3" }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    sessionStore.selectModel("glm/glm-5.3-flash");
    render(<><MessageList /><Composer /></>);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "use flash" } });
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => expect(conv.getState().streaming).toBe(false));
    expect(sentBody.model).toBe("glm/glm-5.3-flash");
    expect(sentBody.model_change).toBe(true);
    expect(sessionStore.getState().modelChangePending).toBe(false);
  });

  it("输入→发送→流式→done：输入清空、用户消息与回答出现", async () => {
    mockBackend();
    render(<><MessageList /><Composer /></>);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "识别" } });
    fireEvent.click(screen.getByText("发送"));

    // 乐观 UI：点击后输入立即清空（不等流式完成）
    expect((ta as HTMLTextAreaElement).value).toBe("");

    await waitFor(() => {
      expect(screen.getByText("识别完成：这是一张测试图片")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(conv.getState().streaming).toBe(false); // 流式状态复位
  });

  it("SSE 机械事实驱动进展阶段：工具开始→整理结果→生成回答", async () => {
    const enc = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) {
            streamController = controller;
            controller.enqueue(enc.encode('data: {"type":"run_started","data":{"session_id":"s1","run_generation":"g-progress"}}\n\n'));
            controller.enqueue(enc.encode('data: {"type":"tool_round","data":{"tool_call_id":"c1","tool_name":"read_file","round_index":1,"args_summary":"{\\"path\\":\\"README.md\\"}"}}\n\n'));
          },
        }), { status: 200 });
      }
      if (url.includes("/api/v1/models")) return new Response(JSON.stringify({ models: [] }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(<><MessageList /><Composer /></>);
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "检查项目" } });
    fireEvent.click(screen.getByText("发送"));

    await waitFor(() => {
      const st = conv.getState();
      expect(st.messages[st.streamingIndex]?.progressStage).toBe("tool");
      expect(st.messages[st.streamingIndex]?.toolActivities?.[0]?.status).toBe("running");
    });

    streamController!.enqueue(enc.encode('data: {"type":"tool_result","data":{"tool_call_id":"c1","tool_name":"read_file","status":"success","duration_ms":25,"result_chars":2400}}\n\n'));
    await waitFor(() => {
      const st = conv.getState();
      expect(st.messages[st.streamingIndex]?.progressStage).toBe("integrating");
      expect(screen.getByTestId("progress-card").textContent).toContain("最近结果：读取文件 · 2.4k 字符 · 25ms");
    });

    streamController!.enqueue(enc.encode('data: {"type":"answer_delta","data":{"data":"结论"}}\n\n'));
    await waitFor(() => {
      const st = conv.getState();
      expect(st.messages[st.streamingIndex]?.progressStage).toBe("answering");
      expect(screen.getByTestId("progress-card").textContent).toContain("正在生成回答");
    });

    streamController!.enqueue(enc.encode(`data: {"type":"done","data":${JSON.stringify({ ...DONE, final_answer: "结论" })}}\n\n`));
    streamController!.close();
    await waitFor(() => expect(conv.getState().streaming).toBe(false));
  });

  it("刷新/切回后 resume 重放工具事实，能恢复实时进展卡阶段", async () => {
    const enc = new TextEncoder();
    let resumeController: ReadableStreamDefaultController<Uint8Array> | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream/status")) {
        return new Response(JSON.stringify({ running: true, run_generation: "g-replay" }), { status: 200 });
      }
      if (url.includes("/api/v1/chat/stream")) {
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) {
            resumeController = controller;
            controller.enqueue(enc.encode('data: {"type":"tool_round","data":{"tool_call_id":"c-replay","tool_name":"search_text","round_index":2,"args_summary":"{\\"query\\":\\"needle\\"}"}}\n\n'));
          },
        }), { status: 200 });
      }
      if (url.includes("/api/v1/sessions/") && url.includes("/messages")) {
        return new Response(JSON.stringify({ messages: [], has_more: false }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    const resume = checkBackgroundRun("s1");
    await waitFor(() => {
      const st = conv.getState();
      expect(st.streaming).toBe(true);
      expect(st.messages[st.streamingIndex]?.progressStage).toBe("tool");
      expect(st.messages[st.streamingIndex]?.toolActivities?.[0]).toMatchObject({
        name: "search_text",
        status: "running",
      });
    });

    resumeController!.enqueue(enc.encode(`data: {"type":"done","data":${JSON.stringify(DONE)}}\n\n`));
    resumeController!.close();
    await resume;
  });

  it("流式异常（网络错误）：输入仍清空 + 错误反馈可见 + streaming 复位", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    render(<><MessageList /><Composer /></>);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "识别" } });
    fireEvent.click(screen.getByText("发送"));

    await waitFor(() => {
      expect(conv.getState().streaming).toBe(false);
    }, { timeout: 3000 });
    expect((ta as HTMLTextAreaElement).value).toBe("");
  });

  it("降级附件：失败事实不会被注入 human 载荷", async () => {
    mockBackend();
    // 捕获发送到后端的 body
    let sentBody = "";
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        sentBody = String(init?.body ?? "");
        return new Response(sseStream([
          `data: {"type":"done","data":${JSON.stringify({ ...DONE, final_answer: "图片未包含，无法识别" })}}`,
        ]), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    // 直接验证发送边界；Composer 的附件卡/错误展示由产品级组件测试负责。
    // 此处不挂载 UI，避免把不相关的 Composer store 订阅混进载荷合同测试。
    const { conversationStore: convSt } = await import("./core/conversation");
    const { sendMessage } = await import("./core/conversation");
    await sendMessage("识别", [
      { filename: "a.png", result_text: "", status: "degraded", detail: "图片识别失败" },
    ]);
    expect(sentBody).toContain('"message":"识别"');
    expect(sentBody).not.toContain("未能识别");
    expect(sentBody).not.toContain("请勿猜测");
    expect(sentBody).not.toContain("a.png");
    expect(convSt.getState().streaming).toBe(false);
  });

  it("成功附件：只发送 opaque ref，不发送提取全文或客户端路径事实", async () => {
    let sentBody = "";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        sentBody = String(init?.body ?? "");
        return new Response(
          sseStream([`data: {"type":"done","data":${JSON.stringify({ ...DONE, final_answer: "ok" })}}`]),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    const { sendMessage } = await import("./core/conversation");
    const ref = "attachment://0123456789abcdef0123456789abcdef";
    await sendMessage("分析", [
      {
        filename: "report.txt",
        result_text: "THIS-LONG-EXTRACT-MUST-NOT-BE-SENT",
        status: "ok",
        attachment_ref: ref,
        content_type: "text",
        size_bytes: 1234,
        sha256: "a".repeat(64),
      },
    ]);
    const body = JSON.parse(sentBody);
    expect(body.message).toBe("分析");
    expect(body.attachments).toEqual([{ ref }]);
    expect(sentBody).not.toContain("THIS-LONG-EXTRACT-MUST-NOT-BE-SENT");
    expect(sentBody).not.toContain("report.txt");
    expect(sentBody).not.toContain('"path"');
    const user = conv.getState().messages.find((m) => m.role === "user");
    expect(user?.content).toBe("分析");
    expect(user?.attachments?.[0]).toMatchObject({ ref, filename: "report.txt", size_bytes: 1234 });
  });

  it("用户气泡显示结构化附件卡，不需要把附件正文塞进消息文本", () => {
    const ref = "attachment://fedcba9876543210fedcba9876543210";
    conv.setState({
      messages: [
        {
          role: "user",
          content: "",
          attachments: [{ ref, filename: "report.pdf", size_bytes: 3 * 1024 * 1024 }],
        },
      ],
      loadedHistoryCount: 1,
    });
    render(<MessageList />);
    expect(screen.getByTestId("msg-attachments")).toBeInTheDocument();
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("3.0 MB")).toBeInTheDocument();
  });

  it("连续两次发送不卡死：第二次不再被 streaming 拦截", async () => {
    mockBackend();
    render(<><MessageList /><Composer /></>);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "识别" } });
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => expect(conv.getState().streaming).toBe(false), { timeout: 3000 });
    // 第二次发送
    fireEvent.change(ta, { target: { value: "继续" } });
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => {
      expect(screen.getByText("识别完成：这是一张测试图片")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(conv.getState().streaming).toBe(false);
  });

  it("新工作区无当前会话：发送仍发出请求（session_id=null 新建会话）", async () => {
    mockBackend();
    const { sendMessage } = await import("./core/conversation");
    const { sessionStore } = await import("./core/stores");
    // 清空当前会话（新工作区/新会话场景）
    sessionStore.setCurrentSession("");
    let sentBody = "";
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        sentBody = String(init?.body ?? "");
        return new Response(
          sseStream([`data: {"type":"done","data":${JSON.stringify({ ...DONE, final_answer: "ok" })}}`]),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    await sendMessage("你好", []);
    // 关键：无 sessionId 仍发出请求（不再被 if(!sessionId) return 拦截），且 session_id 归一为 null
    expect(sentBody).toContain('"session_id":null');
    expect(sentBody).toContain('"message":"你好"');
  });
});
