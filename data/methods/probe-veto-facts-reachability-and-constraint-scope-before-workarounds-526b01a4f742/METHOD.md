---
method_id: probe-veto-facts-reachability-and-constraint-scope-before-workarounds-526b01a4f742
name: probe-veto-facts-reachability-and-constraint-scope-before-workarounds
description: 抓取失败后不要立刻改用更重的替代工具：先按失败特征分流。零字节超时使『网络层不可达』与『页面慢/需渲染』两个假设并列，用一次廉价有界探测（短超时 curl 或对照主机 fetch）二选一；确认不可达则所有本地工具（渲染、沙箱、重试）都无效，直接收口向用户索取内容。若改用受门控工具且拒绝消息已点名其约束（如 URL 白名单），下一个待解未知量是该约束的实际范围（允许哪些 host），而非先学该工具用法或枚举其他替代；目标不在范围内即整支剪掉。核心：在投入 workaround 前，先解析能一票否决整条路径的事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a962d90b-199e-4a0c-af2f-3ce28b719bfb:50:48c085c325d1b508186d
evidence_refs: learning:learn:c0a9d4db4aec
created_at: 2026-09-23T00:55:46.090861+00:00
updated_at: 2026-09-23T00:55:46.090861+00:00
---
## Trigger
外部内容抓取失败（零字节超时）或受门控工具被拒且报错已点名约束原因之后，准备改用更重替代工具（浏览器渲染、沙箱 helper、换工具枚举）之前

## Discriminator
当时已可见两条事实：① web_fetch 是 60s 零字节超时而非快速返回空壳——该特征下『网络不可达』与『需渲染』同为活假设，一次廉价探测即可裁决；② 门禁拒绝消息本身写明『防裸 API 绕过 URL 白名单』——浏览器路径成立与否取决于目标 host 是否在白名单内，与 helper 用法无关，此范围当时即可查

## Short path
- web_fetch 零字节超时 → 待解未知量：远端不可达还是页面慢/重？执行一次有界探测（短超时 curl 直连，或 fetch 一个已知可达的对照 host）
- 探测得到连接层失败（如 curl 连接超时退出码）→ 判定网络层不可达：渲染、沙箱、重试 web_fetch 全部无效，剪掉整棵 workaround 分支
- 向用户呈现证据表并请求粘贴/导出内容，停止工具尝试
- 分支（探测可达且响应快但内容缺失）→ 才考虑渲染/provenance 路线；若需受门控浏览器工具，先读其白名单/约束定义确认目标 host 被允许，再学 helper 用法

## Stop conditions
- 已有独立于原工具的传输层证据确认目标不可达（curl 连接失败/超时退出码）→ 停止一切本地 workaround，转入向用户索取内容
- 已读到约束定义且目标 host 不在允许范围 → 放弃该工具路径，不投入用法学习
- 已从可达且被允许的来源取得用户所需内容 → 停止发现

## Verification
- 『不可达』结论须有至少一条独立传输层证据（curl 退出码/连接错误）支撑，不凭单次 web_fetch 超时定论
- 『白名单不含目标』结论须来自约束定义本身（源码/配置中的允许集合），而非对报错文本的猜测
- 最终答复中每条『路径不可行』断言都能对应一条已观察到的工具回执

## Counterexamples
- web_fetch 快速返回 HTML 空壳并引用 hydration script → 网络显然可达，不做可达性探测，直接沿 provenance 追内容生产者
- 门禁点名的约束范围已知包含目标 host（白名单明确允许该域）→ 直接学习 helper 用法并执行，无需范围核查
- 超时对象是已知缓慢但合法的大资源（大文件/慢 API），超时≠不可达 → 应改分段请求/加长超时/断点续传，而非判定不可达而收口
