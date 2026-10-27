import { describe, expect, it } from "vitest";
import { projectToolActivityMessages } from "./core/toolActivity";
import { errorRecoveryHint } from "./core/errorRecovery";
import type { ChatMessage } from "./core/types";

describe("long history projection identity", () => {
  it("reuses unchanged tool rows across streaming deltas and invalidates changed receipts", () => {
    const assistant = { role: "assistant", content: "", toolCalls: [{ id: "t1", name: "read_file", arguments: { path: "a" } }] } as ChatMessage;
    const receipt = { role: "tool", content: "original", toolCallId: "t1" } as ChatMessage;
    const live = { role: "assistant", content: "a" } as ChatMessage;
    const first = projectToolActivityMessages([assistant, receipt, live]);
    const next = projectToolActivityMessages([assistant, receipt, { ...live, content: "ab" }]);
    expect(next[0].msg).toBe(first[0].msg);
    expect(next[1].msg.content).toBe("ab");
    const changed = projectToolActivityMessages([assistant, { ...receipt, content: "updated" }, live]);
    expect(changed[0].msg).not.toBe(first[0].msg);
    expect(changed[0].msg.toolActivities?.[0].resultContent).toBe("updated");
    expect(receipt.content).toBe("original");
  });
});

describe("actionable error advice", () => {
  it("does not recommend blind continuation for authentication or protocol failures", () => {
    expect(errorRecoveryHint("HTTP 401")).toContain("不能修复认证");
    expect(errorRecoveryHint("HTTP 400 reasoning_content missing")).toContain("可能仍会失败");
    expect(errorRecoveryHint("HTTP 429")).toContain("避免连续重复发送");
    expect(errorRecoveryHint("LLMTimeoutError 超时")).toContain("确认任务已结束后");
  });
});
