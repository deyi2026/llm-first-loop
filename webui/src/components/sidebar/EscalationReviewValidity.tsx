// EVO-20261127-dd37be50: 审批卡上的「独立审查剩余有效期」。
//
// 数据来自申请记录 host_request.host_review_expires_at——Host 在审查发起时写入的
// 墙钟截止时刻（审查发起 + 3600 秒），**仅用于展示**：能否签发只由 Host 在人工
// 批准时按自己的时钟判定。这里不做任何门控，也不禁用「批准」按钮；剩余时间按
// 浏览器本机时钟估算，时钟偏差只影响提示早晚，不影响签发结果。
const WARN_MINUTES = 10;

export interface ReviewValidityView {
  kind: "expired" | "short" | "ok";
  /** 本地化后的截止时刻（时分秒）。 */
  deadline: string;
  /** 剩余整分钟（向上取整；已过期为 0）。 */
  minutes: number;
}

/** 没有可信截止时刻（改动前的旧记录 / 字段缺失 / 不可解析）时返回 null：不展示、不猜测。 */
export function reviewValidity(
  expiresAt: string | null | undefined,
  now: number = Date.now(),
): ReviewValidityView | null {
  if (!expiresAt) return null;
  const deadlineMs = Date.parse(expiresAt);
  if (!Number.isFinite(deadlineMs)) return null;
  const remainingMs = deadlineMs - now;
  const deadline = new Date(deadlineMs).toLocaleTimeString("zh-CN", { hour12: false });
  if (remainingMs <= 0) return { kind: "expired", deadline, minutes: 0 };
  const minutes = Math.ceil(remainingMs / 60_000);
  return { kind: minutes <= WARN_MINUTES ? "short" : "ok", deadline, minutes };
}

export function EscalationReviewValidity({ expiresAt }: { expiresAt?: string }) {
  const view = reviewValidity(expiresAt);
  if (!view) return null;
  if (view.kind === "expired") {
    return (
      <div className="v2-esc-hash warn" role="alert" data-testid="esc-review-expired">
        ⚠️ 独立审查已于 {view.deadline} 过期：现在批准也无法签发，该申请会被标记为「签发失败」。
        请先让来源会话重做审查（merge_review_start）并重新发起申请，再批准新的申请。
      </div>
    );
  }
  if (view.kind === "short") {
    return (
      <div className="v2-esc-hash warn" role="alert" data-testid="esc-review-short">
        ⚠️ 独立审查将于 {view.deadline} 过期（剩余约 {view.minutes} 分钟）：请尽快批准；
        过期后只能重做审查再重新申请。
      </div>
    );
  }
  return (
    <div className="v2-esc-hash" data-testid="esc-review-validity">
      独立审查有效期至 {view.deadline}（剩余约 {view.minutes} 分钟）；过期后批准无法签发。
    </div>
  );
}

// Host 在人工批准时给出的原因码 → 给人看的说明。镜像自 Python 侧的单一来源
// tools/escalation.py 的 ISSUE_FAIL_REASON_HINTS（AI 侧 wait 工具与审批路由用同一份）。
// 原因码本身是稳定标识，这里只在它后面补一句人读说明；未知的码不给说明、不猜测。
const ISSUE_FAIL_REASON_HINTS: Record<string, string> = {
  review_not_host_owned_or_expired: "独立审查已超过有效期（自审查发起起 60 分钟），或不属于当前 Host 进程（服务可能已重启）",
  lane_not_verifying: "lane 已不在 verifying/merging 状态",
  lane_changed_after_review: "审查之后 lane 的 base/head/分支/工作树已变化",
  lane_base_or_head_stale: "main 已前进，或 lane 的 base/head 与审查时不一致（需先基于当前 main 更新 lane）",
};

/** 已知原因码 → 人读说明；未知码返回空串（调用方自行给通用说明）。 */
export function issueFailureHint(code: string): string {
  return ISSUE_FAIL_REASON_HINTS[code] ?? "";
}
