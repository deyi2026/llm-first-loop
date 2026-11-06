---
title: 安装器不维护 assets 软链，版本切换后需手工重指向活动版本的 _bundled
scenario: Linux 主机用 wheel/候选版安装的 LFL，版本升级后 doctor 报的规则/方法/技能计数仍是旧版本，或会话提示词退化为通用提示
root_cause: ""
solution: 官方安装器不维护 ~/.local/share/lfl/assets 软链（实测 install_linux.sh 无相关逻辑），而 wheel 安装缺这条软链时 runtime/paths.py 找不到随包 bundle，规则索引/方法/技能/经验会退化为 0（会话裸跑通用提示）。每次版本切换后手工重指向活动版本：ln -sfn ~/.local/share/lfl/releases/LFL-$(cat ~/.local/share/lfl/.LFL-active-version)/venv/lib/python3.13/site-packages/llm_loop/_bundled ~/.local/share/lfl/assets，然后 systemctl --user restart lfl.service，并用 lfl doctor 的「上下文资产」计数核对。本条是上游修复落地前的临时绕过。
evidence: 主机实测 2026-11-06：grep install_linux.sh 无 assets/_bundled/ln -s 相关逻辑（仅 GitHub release assets 字典）；0.6.38 安装后 doctor 报「规则索引 36 条、方法 13 条、经验 4 条、技能 42 个」，而 assets 软链重指向前指向 0.6.37 bundle 时仅 8 条规则/37 技能。当前性验证：ls -l ~/.local/share/lfl/assets 应指向活动版本目录；复现：ln -sfn ~/.local/share/lfl/releases/LFL-$(cat ~/.local/share/lfl/.LFL-active-version)/venv/lib/python3.13/site-packages/llm_loop/_bundled ~/.local/share/lfl/assets 后 systemctl --user restart lfl.service，lfl doctor 的资产计数应变化。
tags: [wheel, assets, 软链, bundle, 升级]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T20:03:30.710652+08:00"
updated_at: "2026-11-06T20:03:30.710652+08:00"
supersedes: [EXPERIENCE-20261106-wheel-安装下-lfl-运行时资源路径落空-需显式指向-llm-loop-bundled]
---