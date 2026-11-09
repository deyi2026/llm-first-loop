---
title: full_test 审查资格在共享 runtime 数据目录下存在哈希竞态：PASS 后须秒级衔接执行
scenario: 在共享 runtime 数据目录（data/ 未跟踪、多会话并发写 method store/audit）下执行 RULE-AI-28 full_test 审查闸流程
root_cause: ""
solution: "PASS 回执到手后零延迟发起受闸命令；若遭 sha_mismatch 不重试旧资格、直接重开审查并保持\"PASS→execute\"秒级衔接；本会话两次实测 v2 失败/v3 成功均由此间隔差异决定"
evidence: "v2 拒绝回执 sha_mismatch(frozen=4c5001cb85a4, recomputed=91c5b4aa4cb5)；22:27 data/methods/embeddings-*.json(23MB) 重写与 live-foreign-writer-mtime-check-*-cc890aee4e8a/ 新建（ls -lat 与 find -newer 实证）；v3 PASS(697eb098) 后即时执行成功 job-8fdb761867e743859df2"
tags: [review_admission, RULE-AI-28, sha_mismatch, shared-data-dir, race]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T22:51:43.746110+08:00"
updated_at: "2026-11-08T22:51:43.746110+08:00"
---

review_admission 的资格把"切片外 tracked/未跟踪文件内容摘要"绑进 candidate_sha256，且 shared runtime 的 data/methods、data/audit 是活跃写入面：任何会话（含审查 child 自身）写方法卡/embeddings 缓存都会改变未跟踪摘要。两次实测：v2 PASS 后 26 秒内 data/methods 出现外来写入（22:27 embeddings 重写+新卡目录）→ execute 时 sha_mismatch 直接拒绝；v3 PASS 后立即发起 execute 即成功。防复发姿势：PASS 到 execute 的间隔压到秒级；遭遇 mismatch 直接重开审查（previous_child_id 会 previous_review_not_owned，不能复用）；不要为绕竞态去改基线或暂停共享目录——那是其他会话的合法写入面。