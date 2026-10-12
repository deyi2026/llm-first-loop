import { describe, expect, it } from "vitest";
import { buildAssistantNote, toChatMessage } from "./core/chat";

describe("completion facts", () => {
  it("history compaction is not output truncation", () => {
    expect(buildAssistantNote({
      history_compacted: true, provider_output_truncated: false, run_incomplete: false,
    })).toBeNull();
  });

  it("incomplete runs do not claim that the provider truncated the answer", () => {
    const note = buildAssistantNote({
      truncated: true, provider_output_truncated: false, run_incomplete: true,
    });
    expect(note).toContain("未完整收口");
    expect(note).not.toContain("回答被截断");
  });

  it("provider truncation and old-server compatibility remain visible", () => {
    expect(buildAssistantNote({ provider_output_truncated: true })).toContain("回答被截断");
    expect(buildAssistantNote({ truncated: true })).toContain("回答被截断");
  });

  it("history runtime receipt rebuilds the same fallback/reasoning note after refresh", () => {
    const msg = toChatMessage({
      role: "assistant",
      content: "回答",
      fallback_receipt: { from: "p/a", to: "p/b", reason: "rate_limit" },
      reasoning_mode: "on",
      reasoning_capable: true,
      reasoning_control: "chat_template",
      reasoning_supported: true,
      reasoning_effective: true,
      reasoning_tokens: 12,
    });
    expect(msg.note).toContain("模型回退：p/a → p/b（rate_limit）");
    expect(msg.note).toContain("mode=on");
    expect(msg.note).toContain("effective=true");
    expect(msg.note).toContain("tokens=12");
  });
});
