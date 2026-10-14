---
method_id: disambiguate-named-entities-via-config-layers-before-answering-why-6e5b9cc171c3
name: disambiguate-named-entities-via-config-layers-before-answering-why
description: 当用户提出内嵌未验证前提的『为什么用X(中间件那个吗)/为什么不用Y』类配置问题时，先读具名权威配置工件（.env 键与带日期的决策注释、provider 注册表的 base_url/cost 字段、会话模型目录回执），把同名实体拆成唯一映射（API/网页自动化/本地/中转是不同实体），再按需用精确 provider 名 grep 运行日志证实时间性用法；不要先猜源码文件路径或读宽泛源码段找启用条件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:872:07f1060a3d39f7c4fa82
evidence_refs: learning:learn:076f7cdc3d28
created_at: 2026-10-14T10:09:52.535140+08:00
updated_at: 2026-10-14T10:09:52.535140+08:00
---
## Trigger
用户提问内嵌未验证前提，且用不确定限定词指称系统实体（『X通道(是中间件那个吗)』『为什么不用Y』），同时系统存在具名权威配置工件（.env、provider/模型注册表、会话模型回执）可直接查阅。

## Discriminator
同一实体短名在注册表中可能对应多条目（API版/网页订阅版/本地版/中转版）；registry 的 base_url scheme（https:// vs browser:// vs localhost）与 cost 字段、.env 中带日期与决策来源的注释行，这些当时即可见的字段足以把『哪个实体、什么形态、为何如此』缩到一两次读取，无需先定位源码。

## Short path
- grep .env 的模型/provider 相关键：确立生效默认模型、fallback 链、带日期与决策来源的注释（直接提供『为什么』的 provenance）。
- 读 provider 注册表 JSON 与当前会话模型目录回执：枚举全部实体，用 base_url/cost 区分形态，把用户口中每个称呼映射到唯一注册条目。
- 若问题涉及『实际是否/何时在用某通道』，以精确 provider 名 grep 运行日志并限定时间窗，一次定位；不要枚举整个数据目录或读宽泛源码段。
- 逐条判定用户前提真假后作答；仅当注册表缺失某启用条件时才进源码，且以 env/registry 中实际出现的符号名定位文件，而非猜路径。

## Stop conditions
- 用户问题中每个被指称实体已映射到注册表/env 的唯一条目，且每个前提有证据级真/假判定。
- 时间性用法疑问已由带时间戳的日志单点证实或证伪。

## Verification
- 答案中每条配置断言均引用 .env 行号或 registry 字段；同名实体在答案中被显式区分（如 API 版与网页版分列）。
- 日志结论带时间戳并与问题中的现象时间窗对齐，避免把历史调用当作当前占用。

## Counterexamples
- 问题关于代码逻辑而非配置（如『为什么这个函数会重试』）——源码才是第一跳，扫 .env 无益。
- 前提已被先前回执验证为真且实体无歧义——直接回答，配置层扫描是纯开销。
- 陌生仓库无具名配置工件、布局未知——先做发现；此时锚定 .env/registry 路径本身是猜路径，会重演首个失败调用。
