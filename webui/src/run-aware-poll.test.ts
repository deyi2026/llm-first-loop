import { describe, expect, it } from "vitest";
import { runAwareIntervalMs } from "./core/runAwarePoll";

describe("runAwareIntervalMs", () => {
  it("空闲时保持基准间隔", () => {
    expect(runAwareIntervalMs(5000, false)).toBe(5000);
  });
  it("run 期间降频 ×4（5s→20s）", () => {
    expect(runAwareIntervalMs(5000, true)).toBe(20000);
  });
});
