---
title: DSH 内置插件装上≠生效：在插件详情页开 Enable 开关，否则模型不进选择器
scenario: DSH 0.2.0-rc.2 + dsh-workbuddy-connect@0.7.3。安装成功、Plugins 面板 Installed 且无 Problem、CLI `status` 返回 signed-in/有积分，但 Web 模型选择器只有 DeepSeek，无 WorkBuddy 分组。
root_cause: "插件默认处于未启用状态。Components 区显示 \"1 total · 1 off\"、组件行 X_..._rowState 显示 Off。设置→内置插件那一栏是只读运行状态清单（插件 README 明确写\"无配置入口，别找错地方\"），真正的开关在 主界面→插件→<plugin>→查看 详情页顶部，是一个 role=switch 的 button（aria-label 形如 \"Enable <plugin>\"），data-state=false。"
solution: "在插件详情页点开该 role=switch 开关 → Components 变为 \"1 total · 1 running\"、组件行 Running → 聊天模型选择器立即出现该 provider 分组。验证判据用\"模型选择器里是否出现该 provider 分组\"，不要用 CLI status（它只读凭据，与组件启用状态无关，会给出假阳性）。"
evidence: "实际观测：启用前选择器 = \"DeepSeek | DeepSeek-V41-Flash | DeepSeek-V4-Pro\"，HAS WorkBuddy=False；启用后同一路径 = 上述 17 个 WorkBuddy 模型，HAS WorkBuddy=True。"
tags: [dsh, plugin, workbuddy-connect, enable-switch, browser-verification, playwright]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T08:22:36.093735+08:00"
updated_at: "2026-10-13T08:22:36.093735+08:00"
supersedes: [EXPERIENCE-20261011-dsh-profile-装-peer-为-的插件会让-0-1-x-实体沉入-profile-node]
---