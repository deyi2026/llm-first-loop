---
title: ForeignKey.deconstruct 字符串分支全小写 app_label 导致混合大小写 lazy reference 崩溃
scenario: "SWE-bench django-13112：混合大小写 app_label（如 'DJ_RegLogin'）的 ForeignKey 在 makemigrations/migrate 崩溃 \"app 'dj_reglogin' isn't installed\"。调试要点：直接模型类操作 deconstruct 输出正常（label_lower 保留 app_label），但经 ModelState.from_model+render 后 lazy reference 全小写——差异在字符串分支 .lower()。"
root_cause: "ForeignKey.deconstruct 字符串分支 `kwargs['to'] = self.remote_field.model.lower()` 把整个引用（含混合大小写 app_label）全小写；ModelState 渲染链第二次 clone 走字符串分支生成小写 lazy reference，与注册 key（app_label 原样）不匹配，残留 pending 触发 E307。"
solution: "deconstruct 字符串分支改为只小写 model_name、保留 app_label：`app_label, model_name = model_ref.rsplit('.', 1); kwargs['to'] = '%s.%s' % (app_label, model_name.lower())`，无点字符串（'self' 递归引用）保持原 lower 行为。与 make_model_tuple 语义一致（app_label 原样 + model_name.lower()），常规小写 app_label 场景零回归（autodetector 236 tests OK）。"
evidence: django-13112 回访：debug 打印 lazy_model_operation keys 大小写正确但 E307 报错全小写，定位到 ForeignKey.deconstruct 字符串分支；修复后 64 tests OK + 容器终验 OK
tags: [django, app_label, mixed-case, deconstruct, lazy-reference, E307]
source: {}
status: active
created_at: "2026-08-20T03:22:08.429108+08:00"
updated_at: "2026-08-20T03:22:08.429108+08:00"
---