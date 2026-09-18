---
title: r9 门禁双断点分离处置：外部链带入红（registry 登记销号）vs 门禁脚本自失配（探针标记对准实际格式）
scenario: "r9 提交门禁在双链合并后的 HEAD 上反复\"基建失败\"中止或暴露未知测试红（外部演进链 f1ae293 带入 working_set receipts 4 红且不在 registry；同时 ci_gate 步进格式升级为 5 步而 r9_commit.sh 探针仍 grep 旧 \"[4/4]\" 标记永不匹配）"
root_cause: "外部演进链只改 src/ci_gate 不改测试配套与 r9 探针；r9 hermetic 探针在 HEAD 态跑全量必然暴露这些缺口——门禁失败时先分\"基建失败\"（脚本/标记失配）与\"测试红\"（配对面缺口），后者再分\"我的改动\"与\"外部带入\"（merge-base 时序 + registry 登记态），不混为一谈"
solution: "三步分离法：(1) 全量跑一次收集精确红集（grep FAILED sort -u），与 registry 比对差集=新红；(2) 对新红逐项 git merge-base --is-ancestor 判断合入时点在 Gate0 重建（registry 上次全量复核时点）前后，Gate0 后合入的外部链提交=配对面缺口，按先例登记 registry（86→90，_meta 写归因与销号路径沿 C 裁决），不代修（修错方向比不修糟，src 行为语义归外部演进链）；(3) 对\"基建失败\"类中止，检查门禁脚本自身：探针标记（步进格式 [x/5]）与实际输出格式（grep -n \"═══ \[\" 对照）、mktemp 无参模板是否被沙盒拒（显式 /tmp/ 前缀）、fixture manifest 哈希漂移（git diff 定位变更源头同步）。三项修复合并一笔 guard(r9) 提交，豁免放行后 r9_commit_check PASS 确认。"
evidence: "/tmp/r9probe.* hermetic 探针实测 4 红；git merge-base --is-ancestor f1ae293 b4de819 = false（Gate0 后合入）；r9_out2.log \"未达 [4/4] 测试步\" vs ci_gate.sh:94 \"═══ [5/5]\"；r9_out3.log \"4 项失败全部属 external_red_registry 登记项——放行提交 + R9 提交完成\" @ e5df518"
tags: [r9门禁, external_red_registry, 配对面缺口, 门禁探针失配, hermetic探针, 外部演进链]
source: {}
status: active
created_at: "2026-09-10T04:42:38.782208+08:00"
updated_at: "2026-09-10T04:42:38.782208+08:00"
---