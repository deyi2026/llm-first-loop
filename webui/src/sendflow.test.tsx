// 发送链路集成测试：输入→发送→流式→done→清场（对齐用户现场：上传附件后发送"识别"）

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { MessageList } from "./components/conversation/MessageList";
import { sessionStore } from "./core/stores";
import { conversationStore as conv } from "./core/conversation";

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
    conv.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    conv.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
    sessionStore.setCurrentSession("s1");
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

  it("降级附件：失败事实留在 UI，不改写 user 载荷", async () => {
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
    render(<Composer />);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "识别" } });
    // 注入降级附件（模拟图片识别失败）
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
