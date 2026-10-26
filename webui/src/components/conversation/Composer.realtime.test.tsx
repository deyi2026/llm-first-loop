import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Composer } from "./Composer";
import { sessionStore } from "../../core/stores";

const voiceMock = vi.hoisted(() => ({
  onCommittedTranscript: null as null | ((transcript: string) => void),
  onNotice: null as null | ((message: string) => void),
}));

vi.mock("../../core/realtime/useRealtimeVoice", () => ({
  useRealtimeVoice: (options: {
    onCommittedTranscript?: (transcript: string) => void;
    onNotice?: (message: string) => void;
  }) => {
    // 合并线语义：对象参数 + 终稿经 onCommittedTranscript 直接提交
    voiceMock.onCommittedTranscript = options.onCommittedTranscript ?? null;
    voiceMock.onNotice = options.onNotice ?? null;
    return {
      enabled: false,
      connectionState: "closed",
      micEnabled: false,
      micStarting: false,
      modality: "voice_full",
      chainLabel: "ASR → LLM → TTS",
      transcript: "",
      playbackState: "idle",
      error: "",
      visual: undefined,
      enable: vi.fn(async () => true),
      disable: vi.fn(),
      press: vi.fn(),
      release: vi.fn(),
      interrupt: vi.fn(),
      retryPlayback: vi.fn(),
      startShare: vi.fn(),
      stopShare: vi.fn(),
      setVisualKind: vi.fn(),
    };
  },
}));

beforeEach(() => {
  voiceMock.onCommittedTranscript = null;
  voiceMock.onNotice = null;
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v1/chat/stream") {
      const body = JSON.parse(String(init?.body)) as { message: string; session_id: string | null; new_session?: boolean };
      expect(body.message).toBe("recognized speech");
      expect(body.session_id).toBeNull();
      // 合并线契约：空工作区首条消息由 session_id=null 表达新会话；
      // new_session 仅显式“新会话”按钮场景置 true，此处应为 undefined。
      expect(body.new_session).toBeUndefined();
      return new Response([
        'data: {"type":"run_started","data":{"session_id":"created-by-voice","run_generation":"g1"}}\n\n',
        'data: {"type":"answer_delta","data":{"data":"spoken answer"}}\n\n',
        'data: {"type":"done","data":{"session_id":"created-by-voice","final_answer":"spoken answer"}}\n\n',
      ].join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } });
    }
    if (url === "/api/v1/models") {
      return new Response(JSON.stringify({ models: [], current: null }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("creates the first chat session from recognized speech instead of requiring a text turn", async () => {
  render(<Composer />);
  await waitFor(() => expect(voiceMock.onCommittedTranscript).toBeTypeOf("function"));
  act(() => {
    voiceMock.onCommittedTranscript!("recognized speech");
  });
  // 终稿提交异步建会话：等待 SSE 流回执
  await waitFor(() => expect(sessionStore.getState().currentSessionId).toBe("created-by-voice"));
  expect(sessionStore.getState().newSessionPending).toBe(false);
});
