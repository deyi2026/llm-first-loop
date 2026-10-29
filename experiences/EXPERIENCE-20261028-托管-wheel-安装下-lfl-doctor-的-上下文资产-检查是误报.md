---
title: 托管(wheel)安装下 lfl doctor 的「上下文资产」检查是误报
scenario: Linux 主机用安装器托管安装后运行 lfl doctor，输出「上下文资产：未找到规则/经验/技能资产，会话只加载通用提示」，但 _bundled 下 docs/ai_rules.md、37 个 skills、13 个 methods 均实际存在
root_cause: application_main 中 dispatch_query/_preflight_legacy_command 分支在 prepare_environment 之前返回，doctor 因此读不到 DOCS_DIR/SKILLS_DIR/METHOD_SEED_DIR，资产计数全为 0
solution: 不要据此判定安装失败：运行 prepare_environment 后再查，运行时资产为 rules=8/methods=13/skills=37，真实会话不受影响。修复位置在 src/llm_loop/cli.py：doctor 属于提前返回的预检命令，未经过 prepare_environment（该函数才 apply_to_environ 把 _bundled 路径写进环境），应让 doctor 先绑定环境，或直接用 bundle_root() 解析资产路径。当前性验证：在目标主机执行 `~/.local/bin/lfl doctor`，若该行仍显示「未找到规则/经验/技能资产」而 `lfl paths` 的 DOCS_DIR 指向 _bundled 目录，则误报仍存在；修复后该行应显示「规则索引 N 条、方法 N 条、技能 N 个」。
evidence: 主机实测：默认 lfl doctor 报未找到；导出 DOCS_DIR/SKILLS_DIR/METHOD_SEED_DIR 指向 _bundled 后立即变为「规则索引 8 条、方法 13 条、技能 37 个」；在 venv 内调用 prepare_environment 后 inspect_installation_assets() 返回 rules=8/methods=13/skills=37
tags: [lfl, doctor, bundle, 误报, 打包]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T14:34:21.582774+08:00"
updated_at: "2026-10-28T14:34:21.582774+08:00"
---