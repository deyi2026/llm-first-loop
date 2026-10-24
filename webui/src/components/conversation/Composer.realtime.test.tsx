import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Composer } from "./Composer";
import { sessionStore } from "../../core/stores";

const voiceMock = vi.hoisted(() => ({
  onFinal: null as null | ((text: string) => Promise<string | null>),
}));

vi.mock("../../core/realtime/useRealtimeVoice", () => ({
  useRealtimeVoice: (_sessionId: string, onFinal?: (text: string) => Promise<string | null>) => {
    voiceMock.onFinal = onFinal ?? null;
    return {
      enabled: false,
      connectionState: "closed",
      micEnabled: false,
      micStarting: false,
      modality: "voice_full",
      chainLabel: "ASR → LLM → TTS",
      transcript: "",
      error: "",
      enable: vi.fn(async () => true),
      disable: vi.fn(),
      press: vi.fn(),
      release: vi.fn(),
      interrupt: vi.fn(),
    };
  },
}));

beforeEach(() => {
  voiceMock.onFinal = null;
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/v1/chat/stream") {
      const body = JSON.parse(String(init?.body)) as { message: string; session_id: string | null; new_session?: boolean };
      expect(body.message).toBe("recognized speech");
      expect(body.session_id).toBeNull();
      expect(body.new_session).toBe(true);
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
  await waitFor(() => expect(voiceMock.onFinal).toBeTypeOf("function"));
  let answer: string | null = null;
  await act(async () => {
    answer = await voiceMock.onFinal!("recognized speech");
  });
  expect(answer).toBe("spoken answer");
  expect(sessionStore.getState().currentSessionId).toBe("created-by-voice");
  expect(sessionStore.getState().newSessionPending).toBe(false);
});
