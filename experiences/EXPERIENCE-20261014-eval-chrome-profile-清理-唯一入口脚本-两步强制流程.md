---
title: eval chrome-profile 清理：唯一入口脚本 + 两步强制流程
scenario: eval run 迭代后磁盘累积大量 chrome-profile 目录需清理；触发时机为 eval 收官、结论数据固化之后。
root_cause: ""
solution: 只用 scripts/clean_eval_chrome_profiles.py：先 dry-run 审查清单，再 --apply；apply 后复跑 dry-run 验证待删数=0。保护边界：data/runtime/ 永不清理；被占用 profile 自动跳过；mount-test 需显式 --include-mount-test；结论 JSON 一律不碰。禁止手动 rm -rf。
evidence: 2026-10-14 实测：脚本防护/占用检查/apply 在自造目录上验证通过；evals/ 基线 0 个 chrome-profile（脚本 rglob 与 find 双向一致）；规则文档落盘 46 行。
tags: [eval, cleanup, chrome-profile, ops-rule, disk-hygiene]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T12:32:45.074583+08:00"
updated_at: "2026-10-14T12:32:45.074583+08:00"
---

browser_smc 系 eval 每个 run 物化独立 chrome-profile/ 目录（几十~几百 MB），多次迭代累积可观。清理必须走唯一入口：python scripts/clean_eval_chrome_profiles.py。两步强制：① 默认 dry-run 审查待删清单与体积；② 确认后 --apply 执行；可选 --min-age-hours N 排除活跃/新建 run。保护边界不可绕过：data/runtime/ 下一律不清理（不因参数改变）；只删 chrome-profile 本身，结论 JSON 不碰；被 pgrep 命中的 profile 自动跳过；data/browser_mount_test/ 默认不清理，需显式 --include-mount-test。apply 后必须复跑 dry-run 确认待删数=0，并抽查结论 JSON 完好。禁止手动 rm -rf 任何 chrome-profile 目录。完整规则：docs/OPS-RULE-eval-chrome-profile-cleanup-v1.md（46 行）。触发时机：eval 收官、结论数据固化后；durable 任务挂在 GOAL-20261014-adb4ed20。