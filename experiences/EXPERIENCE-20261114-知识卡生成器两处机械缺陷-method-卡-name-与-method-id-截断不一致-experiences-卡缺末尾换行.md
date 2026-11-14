---
title: 知识卡生成器两处机械缺陷——method 卡 name 与 method_id 截断不一致、experiences 卡缺末尾换行
scenario: 知识卡生成链两处机械缺陷：method 卡 frontmatter 的 name 与 method_id/目录名不一致（name 多出被 ID 截断丢掉的后缀，如 ...-command-lacks-tool vs ...-command-lacks-<hash>）；experiences 卡生成后末尾无换行符。两处均被独立审查抓出（review_admission 判 REVISE，P0=0 P1=0 P2=3）。
root_cause: "name 由可读名截断生成时未与 method_id 重新对齐；experiences 落盘路径未保证末字节换行"
solution: "修复口径：name 一律取 method_id 去掉末尾 12 位哈希（与同批卡片惯例一致）；入库前批量核末字节，tail -c 1 | xxd -p 非 0a 则补一个换行。缺陷在生成侧而非单卡，应修生成器而非逐卡手改。当前性验证：复现 —— 在仓库根执行 grep -m1 '^name:' data/methods/*/METHOD.md，把 name 末尾哈希剥掉后与所在目录名比对，不一致者即命中该缺陷；末字节核验执行 for f in experiences/*.md; do tail -c 1 $f | xxd -p; done | grep -vc '^0a$'，返回值即缺末尾换行的卡数，应为 0"
evidence: "evidence://v1/195856f953363e7abfac0fda2635e0d59dc93f51cb35b2d13a8ea91ce1d52f22"
tags: [knowledge-pipeline, review-gate, consistency-check]
source: {}
status: superseded
superseded_by: 知识卡生成器两处机械缺陷：method 卡 name 与 method_id 截断不一致、experiences 卡缺末尾换行
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T13:44:00+08:00"
updated_at: "2026-11-14T13:44:00+08:00"
---
