---
title: 误跑 ruff format 后的可机验回滚：用 token 流等价性筛出「纯重排版 hunk」再 git apply -R
scenario: 对含未提交改动的 Python 文件误跑 formatter，需要在不丢语义改动的前提下清掉重排噪声
root_cause: ruff format 只看语法树，会把任何风格不一致的行重排；它幂等但不可逆，而「未提交的其它改动」使 git 级回滚不可用——只能在 hunk 粒度上用「语义是否变化」的机械判据做外科式回滚。
solution: "1) `git diff -U0 -- <file>` 导出；按 hunk 切分；2) 对每个 hunk 把 `-` 行与 `+` 行分别用 `tokenize` 取 token 流，丢弃 NL/NEWLINE/INDENT/DEDENT/COMMENT/ENCODING/ENDMARKER（可选再丢弃 `( ) [ ] , :` 与逗号），若两流相等 ⇒ 该 hunk 是纯重排版；3) 只把这类 hunk 组成 patch，`git apply -R --unidiff-zero` 反向应用，语义改动全部保留。4) 单靠 token 相等会漏掉「隐式字符串拼接被合并」「return 语句加括号」两类，需再跑一次放宽版（丢括号/逗号）并人工抽看 patch 头部确认全是折行。5) 用「前后 numstat」与「测试 + ruff check」双向确认未伤语义。实测：runner 70 hunk → 44 纯格式被回滚，diff 从 170/95 降到 73/32，1158 条相关测试仍全绿。"
evidence: "evidence://v1/3d187386b7d014429a5d6ae99d77bc9ab95dcc0a9fab15744bd48eb9edc4a6b0 （hunks/format_only 计数与反向应用回执）、evidence://v1/3af91aeb0321aa4d11b9df63b68eb08fe7fad5eaa273c1a7ac126f6c5cb5eae2 （分类脚本）、回滚后 1158 passed + ruff 仅剩既有 UP032"
tags: [ruff, formatter-churn, diff-hygiene, git-apply-reverse, tokenize]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T20:42:35.141158+08:00"
updated_at: "2026-11-03T20:42:35.141158+08:00"
---