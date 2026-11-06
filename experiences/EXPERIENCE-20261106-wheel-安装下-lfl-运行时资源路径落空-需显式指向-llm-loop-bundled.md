---
title: wheel 安装下 LFL 运行时资源路径落空，需显式指向 llm_loop/_bundled
scenario: "LFL 以 wheel/发行版方式安装在 Linux 用户级（~/.local/share/lfl/releases/LFL-<ver>/venv），doctor 报「上下文资产：未找到规则/经验/技能资产，会话只加载通用提示」，实际资源打包在 site-packages/llm_loop/_bundled/{docs,methods,skills}。"
root_cause: ""
solution: 根因：resolve_runtime_paths 把 docs/methods/skills 默认解析到 <code_root>/docs|methods|skills，wheel 安装的 code_root 是 site-packages/llm_loop，资源实际在 _bundled/ 下 → 规则索引、方法、技能、经验全部落空（会话裸跑通用提示，非误报）。修法（运维层，无需改代码）：建软链 ~/.local/share/lfl/assets → releases/LFL-<ver>/venv/lib/python3.13/site-packages/llm_loop/_bundled，并在 .env 显式设 DOCS_DIR=$HOME/.local/share/lfl/assets/docs、METHODS_DIR=$HOME/.local/share/lfl/data/methods、METHOD_SEED_DIR=$HOME/.local/share/lfl/assets/methods、SKILLS_DIR=$HOME/.local/share/lfl/assets/skills、EXPERIENCES_DIR=$HOME/.local/share/lfl/experiences，然后重启。升级发行版后需重建 assets 软链（版本目录名会变）。
evidence: 主机 192.168.3.x 修前：briefing._paths() → site-packages/docs|methods|skills 均 exists=False，doctor 报 0 规则/0 方法/0 技能；修后重启：doctor「上下文资产：可加载：规则索引 8 条、方法 13 条、经验 2 条、技能 37 个」，整体状态 ready。
tags: [linux, wheel-install, resource-path, doctor, runtime-paths]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T18:54:15.031368+08:00"
updated_at: "2026-11-06T18:54:15.031368+08:00"
---

当前性验证：ssh <user>@192.168.3.x 'export PATH=$HOME/.local/bin:$PATH; timeout 45 lfl doctor --online' 应显示「上下文资产：…规则索引 N 条、方法 N 条、经验 N 条、技能 N 个」且 N>0、整体「状态：ready」；若回到 0，先检查 assets 软链是否失效（升级后 releases/LFL-<新版本> 目录名变化）→ ls -l ~/.local/share/lfl/assets 并按新版本重建软链。