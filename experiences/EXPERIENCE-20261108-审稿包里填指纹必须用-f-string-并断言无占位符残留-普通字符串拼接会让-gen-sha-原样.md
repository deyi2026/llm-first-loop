---
title: "审稿包里填指纹必须用 f-string 并断言无占位符残留——普通字符串拼接会让 {gen_sha} 原样留在包里"
scenario: "给审稿子代理生成审稿包时，包里需要嵌入若干 sha256 指纹（绘图脚本 / 机检脚本 / 机检回执）。用普通字符串拼接（\"\"\"...\"\"\" + var）而不是 f-string 时，形如 {gen_sha} 的占位符会原样留在产物里，且这类缺陷不会被本地任何脚本发现——它只是看起来像一段正常的说明文字。"
root_cause: ""
solution: |
  生成审稿包/回执时，凡是插入计算值的字段一律用 f-string 或显式 .format()；并在写盘前加一条硬断言：输出文本里不得残留 "{" + 标识符 + "}" 形态的占位符（例如断言 pkg.count("{gen_sha}") == 0 且全文没有未替换的 {xxx} 模式）。审稿包是给人（和子代理）读的文本，占位符残留只能靠人眼发现，成本极高。
  复现：跑 `python3 docs/promotion/_d70_reviewpkg3.py`，回执末行应打印 `placeholders left: 0 0 0`；再用 `grep -c "{gen_sha}" docs/promotion/receipts/d70-review-pkg.md` 应得 0。
evidence: "第六轮审稿 subagent_d00a52c300b2 判 P1：审稿包 receipts/d70-review-pkg.md 第五节残留 {gen_sha}/{capjs_sha} 占位符；修复脚本 docs/promotion/_d70_reviewpkg3.py 改为 f-string 真实计算并加「placeholders left」断言，重生成后输出 placeholders left: 0；第七轮 subagent_164f8e2197c0 判 PASS 并确认三枚指纹为真实 64 位十六进制串"
tags: [审稿包, sha256, 占位符, f-string, 生成脚本, 发布流水线]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-08T08:58:02.867985+08:00"
updated_at: "2026-11-08T08:58:02.867985+08:00"
---