import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RuntimeConvergenceStrip } from "./RuntimeConvergenceStrip";

afterEach(cleanup);
it("shows each service and distinguishes inferred artifact match from CLI generation", () => {
  render(<RuntimeConvergenceStrip stale snapshot={{
    desired_generation: 7, desired_git_head: "aaaaaaaaaaaaaaaa", desired_version: null,
    services: { web: { state: "artifact_matches", inferred: true }, feishu: { state: "update_required", inferred: true },
      learning: { state: "artifact_matches", inferred: true }, wecom: { state: "not_running", inferred: true } },
    cli: { state: "update_required", uncertain: 0, processes: [{ pid: 123, generation: 6, git_head: "bbbbbbbbbb", state: "update_required" }] },
  }} />);
  expect(screen.getByText(/gen 7/)).toBeTruthy();
  expect(screen.getByText(/数据待刷新/)).toBeTruthy();
  expect(screen.getByText("web 工件匹配")).toBeTruthy();
  expect(screen.getByText("feishu 待切换")).toBeTruthy();
  expect(screen.getByText("wecom 未运行")).toBeTruthy();
  expect(screen.getByText(/CLI 待切换/)).toBeTruthy();
});
