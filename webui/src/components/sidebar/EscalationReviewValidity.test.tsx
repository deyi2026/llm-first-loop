// EVO-20261127-dd37be50: 审查剩余有效期只做展示——三种状态 + 不可信数据不展示 + 不控制任何按钮。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { EscalationReviewValidity, issueFailureHint, reviewValidity } from "./EscalationReviewValidity";

const NOW = Date.parse("2026-11-27T05:00:00+08:00");
const at = (minutesFromNow: number) => new Date(NOW + minutesFromNow * 60_000).toISOString();

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("reviewValidity（纯函数）", () => {
  it("剩余充足：ok，分钟向上取整", () => {
    expect(reviewValidity(at(30.4), NOW)).toMatchObject({ kind: "ok", minutes: 31 });
    expect(reviewValidity(at(59), NOW)).toMatchObject({ kind: "ok", minutes: 59 });
  });

  it("进入告警窗口（≤10 分钟）：short", () => {
    expect(reviewValidity(at(10), NOW)).toMatchObject({ kind: "short", minutes: 10 });
    expect(reviewValidity(at(0.5), NOW)).toMatchObject({ kind: "short", minutes: 1 });
  });

  it("到点即 expired，分钟归零而不是负数", () => {
    expect(reviewValidity(at(0), NOW)).toMatchObject({ kind: "expired", minutes: 0 });
    expect(reviewValidity(at(-90), NOW)).toMatchObject({ kind: "expired", minutes: 0 });
  });

  it("没有可信截止时刻就不展示：缺失 / 空串 / 不可解析", () => {
    expect(reviewValidity(undefined, NOW)).toBeNull();
    expect(reviewValidity("", NOW)).toBeNull();
    expect(reviewValidity("not-a-timestamp", NOW)).toBeNull();
  });
});

describe("EscalationReviewValidity（展示）", () => {
  it.each([
    [45, "esc-review-validity", /有效期至 \d{2}:\d{2}:\d{2}（剩余约 45 分钟）/],
    [6, "esc-review-short", /将于 \d{2}:\d{2}:\d{2} 过期（剩余约 6 分钟）/],
    [-3, "esc-review-expired", /已于 \d{2}:\d{2}:\d{2} 过期/],
  ] as const)("距截止 %s 分钟 → %s", (minutes, testId, text) => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const { container } = render(<EscalationReviewValidity expiresAt={at(minutes)} />);
    expect(screen.getByTestId(testId)).toHaveTextContent(text);
    // 仅提示：组件不渲染、也不控制任何按钮（批不批准仍由人工决定，能否签发由 Host 判定）
    expect(container.querySelectorAll("button, input, [disabled]")).toHaveLength(0);
  });

  it("过期与临期用 alert 角色提醒；充足时只是普通说明", () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    const first = render(<EscalationReviewValidity expiresAt={at(-1)} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/无法签发/);
    first.unmount();
    render(<EscalationReviewValidity expiresAt={at(40)} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("记录没有可信截止时刻（改动前创建的申请 / 不可解析）→ 不渲染任何内容", () => {
    const legacy = render(<EscalationReviewValidity />);
    expect(legacy.container).toBeEmptyDOMElement();
    cleanup();
    const broken = render(<EscalationReviewValidity expiresAt="not-a-timestamp" />);
    expect(broken.container).toBeEmptyDOMElement();
  });
});

describe("issueFailureHint（原因码 → 人读说明）", () => {
  it("已知原因码给出说明；未知原因码返回空串，不猜测", () => {
    expect(issueFailureHint("review_not_host_owned_or_expired")).toMatch(/独立审查已超过有效期/);
    expect(issueFailureHint("lane_not_verifying")).toBe("lane 已不在 verifying/merging 状态");
    expect(issueFailureHint("lane_changed_after_review")).not.toBe("");
    expect(issueFailureHint("lane_base_or_head_stale")).toMatch(/main 已前进/);
    expect(issueFailureHint("some_new_code")).toBe("");
  });
});
