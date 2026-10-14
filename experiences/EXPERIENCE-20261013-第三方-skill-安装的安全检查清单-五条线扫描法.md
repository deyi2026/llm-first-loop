---
title: 第三方 skill 安装的安全检查清单（五条线扫描法）
scenario: 把外部仓库的 skill（SKILL.md + 本地脚本 + references）装进本仓库 skills/ 目录，会被 skill_load 加载进模型上下文、脚本会被本地 python 执行，需要先做安全审查再启用。
root_cause: ""
solution: "按\"脚本层→文档层→HTML/JS 层→意外文件→外部域名\"五条线扫描，全部用确定性 grep+逐文件定位，而非只跑测试。"
evidence: 2026-10-13 本会话实测回执：gzh 单测 test_validate_gzh_html.py 3 tests OK；component_lint.py 汇总 9/11 干净 ERROR×0；humanizer validate_package.py PASS + check_structure 自测 PASS + tests/test_structure.py 17 tests OK；精确 grep（api_key|paid|付费|billing 及注入模式）脚本层零命中；extract_docx.py L124 os.path.basename 防 zip-slip、wrap_preview 模板 JS 无外联（read_file 全文核过）。
tags: [skill-install, security-review, third-party, supply-chain]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T23:04:51.443064+08:00"
updated_at: "2026-10-13T23:04:51.443064+08:00"
---

安装第三方 skill 到 skills/ 的完整流程（2026-10-13 实测于 gzh-design-skill + humanizer-zh-next 安装）：
1) 浅克隆 → 删嵌套 .git、跑测试后清 __pycache__/.pyc；
2) 功能验证 = 跑仓库自带单测 + SKILL.md 声明的 lint/校验脚本（gate 以其自定门槛为准，如 ERROR×0）；
3) 安全检查五条线：①脚本层 grep 网络(eval/exec/os.system/socket/urllib.request/requests)+危险写；②文档层提示注入模式(ignore previous/忽略之前/system prompt)；③html 层 <script>/onerror/javascript: 逐文件定位用途；④隐藏文件/可执行位/嵌套 .github workflows(GitHub 只执行仓库根 .github，嵌套惰性)；⑤外部 URL 域名盘点区分 README 徽章 vs 会进入产物的域名；
4) 必读关键脚本体：处理 zip 的查 basename 防路径穿越，生成 html 的查其 JS 模板是否外联；
5) 注意 license 差异（AGPL vs MIT）对后续分发的影响。