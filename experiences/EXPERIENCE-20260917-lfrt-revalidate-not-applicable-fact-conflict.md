---
title: lfrt 权限下 revalidate 对云目标 NOT_APPLICABLE 误判 fact_conflict——学习面云模型部署结构性饿死
scenario: 学习作业（execution_class=BACKGROUND_LEARNING）在 admission_authority=lfrt 的运行线上部署云模型（glm/glm-5.3，非 loopback base_url）时，journal 100%（6350/6350）以 resource_authority_changed requeue，静默饿死、零产出。
root_cause: ""
solution: 根因：build_request_for_client 对 NOT_APPLICABLE（非受管云目标）返回 None→调用方走 RG-1 兜底租约并 ADMITTED；revalidate_request_for_client 缺同分支，非 OBSERVED 一律 fact_conflict。修复：revalidate 对 NOT_APPLICABLE 直接 return（LFRT 对非 loopback 目标无权限事实，RG-1 租约成立，与 build 语义对齐）。
evidence: 复现矩阵修复前后对照（execute_command 回执）；pytest test_lfrt_runtime_authority.py 38 pass + settlement/governor/learning_journal 53 pass；gen11 manifest 与 HTTP 冒烟回执
tags: [resources, admission, lfrt, learning-plane, cloud-provider, root-cause]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-17T22:58:25.840413+08:00"
updated_at: "2026-09-17T22:58:25.840413+08:00"
---

受控复现：ProviderCallCoordinator(gov, admission_authority="lfrt", lfrt_runtime=StubLFRT→NOT_APPLICABLE) + 云 client（provider="glm", model="glm-5.3", base_url="https://open.bigmodel.cn/..."）→ build 返回 None（调用方建 RG-1 兜底租约，try_acquire=ADMITTED）→ revalidate_request_for_client 抛 fact_conflict。生产对照：学习 journal 6350/6350 条 resource_authority_changed requeue。修复：src/llm_loop/resources/provider_calls.py revalidate 在 observe_target 后增加 `if target.state is LocalRuntimeTargetState.NOT_APPLICABLE: return`——LFRT 对非 loopback 目标无权限事实，与 build 的 NOT_APPLICABLE→None→RG-1 兜底语义对齐；legacy 权限路径零变化（no-op 不受影响）。测试锁定：tests/unit/test_lfrt_runtime_authority.py::test_lfrt_revalidation_cloud_target_rg1_lease_is_not_a_conflict（修复前红）。部署：gen11 = 9bfb7cd5648249a9515c387bc0fc8a6de1efcfea，web pid 7996 / feishu pid 8126，/auth/status 200、/login 200、/ui/v2/ 303→login 200、heartbeat idle。回滚：gen10 worktree deploy-docs-gen8-20260917（head d3f6b150）+ 审计快照 data/restart-audit/20260917-225450-7675。