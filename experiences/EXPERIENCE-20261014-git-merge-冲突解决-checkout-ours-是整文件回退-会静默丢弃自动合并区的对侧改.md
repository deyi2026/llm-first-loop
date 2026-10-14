---
title: git merge 冲突解决：checkout --ours 是整文件回退，会静默丢弃自动合并区的对侧改动
scenario: "git merge / merge --squash 多文件冲突解决，其中冲突文件同时含有大量可自动合并的对方改动（典型：长 CSS/配置文件，两侧都改了不同区域）。计划是\"冲突 hunk 取 main 侧语义、其余全量保留\"。"
root_cause: "git checkout --ours <file> 是 resolve 阶段的整文件级操作（= HEAD 版本），语义是\"该文件全部以 ours 为准\"，不是\"仅冲突 hunk 取 ours\"；多 hunk 文件中冲突区之外的自动合并内容会全部丢失。vitest 单元测试面未覆盖被丢的 CSS 规则，只有下游浏览器资格断言命中。"
solution: "1) 解决冲突标记而非整文件：对工作区带冲突标记的文件用脚本把每个冲突标记块替换为 HEAD 侧内容（re.S 非贪婪），自动合并结果原样保留；2) 解决后必须做\"差异审计\"：git diff --cached <对方分支> -- <文件>，确认差异只含预期对齐项；3) 有下游行为验证（资格脚本/E2E）时优先跑它而非只跑单元测试——单元测试不覆盖被丢弃的样式规则；4) vite dev 无后端时 API 全 500，资格脚本可用源码注入式 wrapper 补最小 GET fixture（精确 glob；注意尾部 * 吞 query 参数、注意 playwright route LIFO 顺序避免吞掉更精确的 fixture pattern），其余断言保持原样。"
evidence: "vitest 299/299 回执 evidence://v1/bc378c20f0e567ed52d8bd17ac9f13005b58d912fe5e89eb1691e8304d11ce1f；滚动资格全过 /tmp/scroll-qual-full.log（WEB_V2_SCROLL_QUALIFICATION_PASS）；失误暴露与修复过程见会话 evidence://v1/c429b8aaac92263b01bf722e75dbfd12b2b82044225669c858f8ac79190b9e5（证实丢失）与 evidence://v1/aa358063a33e986013c524cf2ca9950b07d7b959948d721c83b33108fa3ed5fa（修复后保留验证）"
tags: [git, merge-conflict, checkout-ours, css, qualification, playwright]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-14T17:51:20.706531+08:00"
updated_at: "2026-10-14T17:51:20.706531+08:00"
---

在 /tmp/webv2-port 对 fix/web-v2-ux-hardening-20261013 做 squash 移植时，对 webui/src/tokens/{app,conversation}.css 两个 UU 文件执行 git checkout --ours，把分支在自动合并区的全部改动（services 卡栅格/topbar-view/modal-box overflow 等）一并回退。首跑 vitest 299 中 1 失败（冷启动 flaky，复跑全绿未暴露问题），真正暴露问题的是随分支引入的浏览器资格脚本：.v2-evo-modal-box overflow:auto 断言失败（该规则在被丢弃的 conversation.css 自动合并区）。修复：git reset --hard 回基点重新 merge --squash，用正则仅将 <<<<<<< HEAD ... ======= ... >>>>>>> 标记块替换为 HEAD 侧内容（保留全部自动合并结果），再按方案追加 scope 块。修复后 diff --cached <branch> 差异只含预期对齐项；vitest 299/299 + 滚动资格 11 检查×5 视口全过。