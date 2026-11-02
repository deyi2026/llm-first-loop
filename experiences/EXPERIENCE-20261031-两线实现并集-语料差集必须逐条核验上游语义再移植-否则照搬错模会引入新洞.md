---
title: 两线实现并集：语料差集必须逐条核验上游语义再移植，否则照搬错模会引入新洞
scenario: "两套守卫/解析实现互非超集时，把对方语料里\"失败\"的向量当缺口补齐"
root_cause: ""
solution: 按四类处置：①真漏放（越界写可逃逸）→补防护+锚点；②仅拒因不同（两边都拦）→不动；③过度拦截（本地更严）→保留本地口径；④对方模型与上游语义相反→不移植，并留锚说明依据。反例（实测）：另一条线按「find -fprintf 格式在前」建模，期望 `find . -fprintf '%p' /outside/x` 越界；GNU findutils 手册 find(1) 明示 `-fprintf file format`（文件在前）⇒ 真正危险形态是 `find . -fprintf /outside/x '%p'`（本地线已拦），照搬会放行它。验证手段：查上游手册/man page 定案参数序，再双向实测两种参数序。
evidence: "evidence://v1/d6c5e5592aa1a11dba0f05102570729f435f6193f86641151c68307c107e72cd（GNU find(1) 手册：-fprintf file format）；/tmp/probe_find.py 实测两实现判定相反；提交 ce520bf92 锚点注释留证"
tags: [write-scope, guard, merge, upstream-semantics, find]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T07:47:52.338062+08:00"
updated_at: "2026-10-31T07:47:52.338062+08:00"
---