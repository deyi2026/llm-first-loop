import { describe, expect, it } from "vitest";
import { buildAssistantNote } from "./core/chat";

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
});
