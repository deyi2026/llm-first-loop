---
title: A.5 清单过 push 闸的两个硬坑：内嵌自身 SHA（自指）+ changed path 覆盖不全
scenario: A.5 架构清单（docs/governance/submissions/*.json）随分支走 push 闸（review_admission kind=git_push）时，因清单内容与冻结候选不自洽被连续判 REVISE，每轮浪费约 4 分钟。
root_cause: ""
solution: |
  1) 清单里绝不内嵌自身提交 SHA 或「本清单修订的候选 SHA」：清单一旦被 amend/重写，该 SHA 立即失效，审查者会判「checker 结果不覆盖实际冻结树」。改为写「由 CI 以 --base <base> --head <PR head> 实跑 checker」，并用代码候选 SHA（不含清单自身）记录实跑证据。
  2) changed path 必须精确全覆盖：A.5 机械审查按 base..head 的 diff 逐路径要求 component 覆盖；新增任何 src/tests 文件（哪怕只是 docs 提交之外的第三个提交）都要同步补 component + declaration，否则 CI 的 A.5 步骤 fail（本次 run 43836767239 即此因）。
  3) 已知不属本次范围的收紧/同步项（如基线里 3 条历史漂移）在 disposition 里显式写明「可拆单列」，避免审查者把它当 scope creep。
  4) 提交前本地先跑 `scripts/check_architecture_submission.py --base <base> --head <commit>` 自查（本次正是靠它把 changed_paths=5 一次跑通）。
evidence: 2026-11-16 push 闸连续 REVISE：subagent_db4d91d2f4e9（P1：清单 rollback 表述与 base 登记值不符）、subagent_9640051aa869（P1：清单把冻结候选写成 d121bcd71，而实际 head 已 amend 为 69aa1089b → checker 结果不覆盖实际树）。最终删除全部自身 SHA 引用、改为「由 CI 以 --base/--head 实跑」后 subagent_0bf994e96d70 PASS。
tags: [review_admission, A.5, governance, git_push, 自指SHA, coverage]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T17:32:51.904606+08:00"
updated_at: "2026-11-16T17:32:51.904606+08:00"
supersedes: [EXPERIENCE-20261102-审查闸自引用时存在引导悖论-先部署再补全量-并保留离线对账通道, EXPERIENCE-20261112-review-host-admission-py-改动会撞-function-size-棘轮守卫-s, EXPERIENCE-20261103-git-push-独立审查材料超预算时-用-commit-refspec-把推送拆成逐段-push]
---