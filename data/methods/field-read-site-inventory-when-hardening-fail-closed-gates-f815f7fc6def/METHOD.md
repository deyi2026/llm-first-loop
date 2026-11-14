---
method_id: field-read-site-inventory-when-hardening-fail-closed-gates-f815f7fc6def
name: field-read-site-inventory-when-hardening-fail-closed-gates
description: 修复被打回的 fail-closed 门禁/证据链时，不要只补反例点名的两个字段：反例的共性是『字段缺失/坏类型被 or 0、默认参数、isinstance 宽松、未 isfinite 的 NaN 救成合法值』，这是按读取点分布的系统性 fail-open。做法：在证据链源码里 grep 每个证据字段的全部读取点（主判定、helper、history 逐行、parser），逐点分类严格/宽松，每类字段收敛到共享严格校验器（int 用 type is int 且≥0 拒 bool 子类；时间戳 isfinite；必填字段显式存在且类型对），失败一律 fail-closed 终态，不抛异常、不转默认；契约性 legacy 默认显式豁免并用回归锁定；parent 反例逐字复现为断言，另做不经测试框架的 tempfile 冒烟。上轮只修点名字段导致父侧再复现两条 P1，本方法避免第三轮返工。
aliases: 字段没写也算通过怎么堵, or 0 兜底翻车, NaN 心跳绕过超时判断, True 被当 1 放行, 反例只点名两个字段要不要全查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:90e344ea-39ba-4d37-aba8-a67f1f51ffd5:0:199a6c3331ee96663aee
evidence_refs: learning:learn:10fe371f4011
created_at: 2026-11-13T14:54:17.229160+08:00
updated_at: 2026-11-13T14:54:17.229160+08:00
---
## Trigger
上一轮修复的判定门/证据链被 reviewer 或 parent 用『缺字段或坏类型 → 默认值/宽松转换 → 误判为安全通过』的可复现反例打回（如缺 queue_depth 被补 0、缺 reply_type 被默认 chat_id），需要再次收紧

## Discriminator
两个反例共享同一形态：字段缺失即被 or 0 / 默认参数补成合法值；且 grep 证据链源码可直接枚举每个证据字段的全部读取点——凡 coerce/default、isinstance 宽松（bool 是 int 子类）、未 isfinite（NaN 比较恒 False 绕过 stale 判定）之处即完整堵漏清单，不需要等下一个反例来点名

## Short path
- 把反例抽象为『缺失→默认→通过』形态，grep 证据链相关源文件中每个证据字段名的全部读取点（主判定函数、stale helper、history 逐行、JSONL parser）
- 逐点分类：严格显式校验 vs 宽松（or 0、.get(k,默认)、isinstance、无 isfinite），后者构成堵漏清单
- 每类字段收敛到一个共享严格校验器：int 用 type(v) is int 且>=0（拒 bool/float/str/负数）、时间戳 math.isfinite、必填字段显式存在且类型对；校验失败返回 fail-closed 终态，不抛异常、不补默认
- 显式豁免契约性 legacy 默认（旧格式迁移映射保留不动），并用回归测试锁定该豁免
- 把 parent 反例逐字复现为测试断言 fail-closed；跑定向套件 + lint/type；再做不经测试框架的 tempfile 冒烟，用真实运行代码确认反例翻转

## Stop conditions
- 证据链中每个字段的每个读取点要么严格校验、要么有明示 legacy 兼容豁免且有测试锁定
- 全部 parent 反例在真实运行代码（tempfile 冒烟，不经测试框架）下断言 fail-closed
- 既有 legacy/相邻通道（如 WeCom）/回归测试全绿，定向套件 exit 0

## Verification
- grep 确认门禁相关字段不再残留 or 0 / 静默默认值转换
- type(True) is int 为 False：bool 误放行用例通过
- NaN/±Inf 时间戳各字段用例 fail-closed 通过
- 写侧↔读侧往返测试：生产者序列化输出与严格读侧契约一致，证明收紧不会拒绝唯一合法生产者

## Counterexamples
- legacy 单文件迁移契约要求默认值（历史无 cause 字段→CRASH 映射）时不得收紧，否则破坏迁移兼容
- 字段本就可选且下游 None-safe（如 context_ref），强制存在反而破坏合法语义
- 纯展示/日志路径的宽松解析，下游无安全门，收紧只增加噪音不增加安全
- 唯一真实生产者尚未写入该字段时，先版本化格式或改写侧；读侧单方面收紧会拒绝全部合法数据
