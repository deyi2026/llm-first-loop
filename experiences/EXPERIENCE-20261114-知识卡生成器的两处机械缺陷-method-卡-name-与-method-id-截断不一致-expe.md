---
title: 知识卡生成器的两处机械缺陷：method 卡 name 与 method_id 截断不一致、experiences 卡缺末尾换行
scenario: 知识卡生成链存在两处机械缺陷：①method 卡 frontmatter 的 name 与 method_id/目录名不一致（name 末尾多出被 ID 长度截断丢掉的后缀，如 ...-command-lacks-tool vs ...-command-lacks-<hash>）；②experiences 卡生成后文件末尾无换行符
root_cause: "name 由可读名截断生成时未与 method_id 重新对齐；experiences 落盘路径未保证末字节换行"
solution: "两处都被独立审查抓出（review_admission 判 REVISE，P2=3）。修复口径：name 一律取 method_id 去掉末尾哈希（与同批卡片惯例一致）；入库前用 `tail -c 1 | xxd -p` 批量核末字节是否为 0a，不为则 printf '\n' 补齐。缺陷在生成侧而非单卡，故应修生成器而非逐卡手改。当前性验证：复现 —— 在仓库根执行 `grep -m1 '^name:' data/methods/*/METHOD.md` 并把 name 末尾 12 位哈希剥掉与所在目录名比对，不一致者即命中该缺陷；末字节核验执行 `for f in experiences/*.md; do tail -c 1 \"$f\" | xxd -p; done | grep -vc '^0a$'`，返回值即缺末尾换行的卡数，应为 0"
evidence: "evidence://v1/195856f953363e7abfac0fda2635e0d59dc93f51cb35b2d13a8ea91ce1d52f22; evidence://v1/933b18799ab1eb6b69700d3a2b8be653339e898a537b115978ce45b0cac30c98"
tags: [knowledge-pipeline, review-gate, consistency-check]
source: {}
status: superseded
superseded_by: 知识卡生成器两处机械缺陷：method 卡 name 与 method_id 截断不一致、experiences 卡缺末尾换行
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T13:44:34.881589+08:00"
updated_at: "2026-11-14T13:44:34.881589+08:00"
---
