---
title: "\"读操作无副作用\"是把保密性当成完整性——越域读+域内写=外泄通道"
scenario: "判断\"读工作区外被拒\"是否为过度限制时，我用\"读无副作用\"作为放宽理由，把它记为应放开的过度限制。"
root_cause: "把\"没有本地副作用\"当成\"没有安全影响\"，漏掉跨能力组合（读+写）构成的外泄通道；同时忽略代码里已有的显式设计记录，用外部直觉覆盖了仓内真值。"
solution: |
  先分清两类安全属性再判定：读操作对**完整性**无影响，但对**保密性**有影响——越域读本身只是把字节搬进上下文，真正的外泄发生在"读外边 + 写自己域内"的组合上（被注入的 child 可读 ~/.ssh/id_rsa 再写进自己可写目录）。因此正确形态不是改默认值，而是**授权来自宿主配置**的显式只读根（与 LFL_BROWSER_UPLOAD_ALLOW_ROOTS 同构），因为模型可控的开关等于没有开关。判据落点：判断"是否过度"之前，先问该限制保护的是哪一类安全属性，以及放宽后是否存在"两个各自无害的能力组合成一条通道"。
  
  当前性验证：`grep -n "uniform read/write" src/llm_loop/workspace/file_service.py` 应仍命中 observe() 附近注释；若该段已被改写，先读当前实现再引用，不以本条记忆代替源码。
evidence: "src/llm_loop/workspace/file_service.py 中 observe() 的注释写明 \"the same scope constrains reads here (uniform read/write fail-closed decision documented in the module docstring)\"（本轮读到约 377-380 行）；我上轮判定漏读该依据，本轮在 REPORT §10.4 回改并保留纠正记录"
tags: [判断纠正, 完整性vs保密性, 权限模型, 读侧放行]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-31T15:45:48.280930+08:00"
updated_at: "2026-10-31T15:45:48.280930+08:00"
---