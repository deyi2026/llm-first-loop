---
title: JSONField KeyTransform 缺 In lookup：SQLite 上 key__in 返回空
scenario: "SWE-bench django-13346：JSONField 的 value__key__in=[14] 在 SQLite 返回空结果，而 value__key=14 正常。KeyTransform 注册了 KeyTransformExact 但无 KeyTransformIn，__in 走通用 lookups.In——lhs 是 JSON_EXTRACT(col,'$.key')（JSON 数字），rhs 是普通字符串 '14'，类型不匹配。"
root_cause: KeyTransform 未注册 In lookup，通用 In 的 rhs 未做 JSON 类型包装，SQLite 上 JSON_EXTRACT 返回的 JSON 数字与字符串参数比较不相等。
solution: "新增 class KeyTransformIn(lookups.In)，仿 KeyTransformExact.process_rhs：sqlite 分支对每个 rhs 值用 JSON_EXTRACT(%s, '$') 包裹（null 值除外），oracle 分支用 JSON_QUERY/JSON_VALUE；注册 KeyTransform.register_lookup(KeyTransformIn)。注意 MRO：不能继承 KeyTransformExact（其父类 JSONExact→lookups.Exact 与 In 冲突），直接继承 lookups.In 并复制 process_rhs。"
evidence: "django-13346 本地 75 tests OK + 容器终验 OK；patch: django__django-13346.patch"
tags: [django, jsonfield, keytransform, sqlite, lookup]
source: {}
status: active
created_at: "2026-08-20T03:21:52.985893+08:00"
updated_at: "2026-08-20T03:21:52.985893+08:00"
---