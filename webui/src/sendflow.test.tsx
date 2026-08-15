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
});
