---
title: 准入闸的修复若在被审提交内部：闸先于修复生效，须执行宿主升级后才可审
scenario: "在 /tmp/lfl-integrate 推送 squash 提交 62939c22a（该提交内含 EVO-20261031-8f3c1d92 vendored 资产分级上限修复）时，review_admission(kind=full_test) 与 review_admission(kind=git_push) 均确定性返回 accepted=false / git_state_too_large:material_diff>400000。三个 skills/ui-ux-pro-max/data 文件相对推送基线 55b53ab81 的 diff 分别为 453,571B / 749,407B / 856,783B，超过旧码 400,000B 单路径上限。"
root_cause: 执行宿主的 llm_loop 解析自 b008c9fa release，早于被审提交 62939c22a 内的 vendored 资产分级上限修复，闸以旧上限确定性拒绝本应可审的物料。
solution: "排查顺序：(1) 先读运行时源码确认闸的 per-path 上限与例外类，再看强制执行的到底是哪一份代码（本会话 PYTHONPATH 指向 .releases/b008c9fa.../src，而被审提交 62939c22a 已含 vendored 例外，cap=8,000,000，三文件均在其下）；(2) 确认 permit 表 HostReviewAdmission._records 是进程内存态（\"Volatile Host authority\"，64 槽 + TTL），故审查必须由将执行被审命令的同一宿主签发——换新进程、换已升级的服务代审都无法被本会话 action=status 核到，也无法被执行层消费；(3) 未取得官方 PASS 前不要先跑全量测试（可能改写已跟踪 reports/ 污染待审物料），更不得 push；(4) 解封条件是把执行宿主升级到含该修复的 release 后重跑准入，不能靠改基线/改内容/缩小 diff 绕过。"
evidence: "两次 review_admission start 回执：accepted=false, reason=git_state_too_large:material_diff>400000（full_test 与 git_push 同码）；HEAD 模块直读：_diff_acquire_cap('skills/ui-ux-pro-max/data/google-fonts.csv')=8_000_000、_diff_material_code=material_acquire>8000000；三文件 diff 字节 453571/749407/856783；service_control(status) services.web.live.git_head=62939c22a、restart_required=false；源码 HostReviewAdmission 自述 Volatile Host authority 且 _records 为进程内 OrderedDict；git ls-remote origin refs/heads/main=55b53ab81（未推达）。"
tags: [review_admission, RULE-AI-28, git_state_too_large, vendored, deployment-order, permit-scope]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T21:51:48.070834+08:00"
updated_at: "2026-10-31T21:51:48.070834+08:00"
supersedes: [EXPERIENCE-20261015-审查闸漏闸复发-已检索经验库仍重复踩同一坑-流程型义务须按-动作类型-而非-任务主题-检索]
---