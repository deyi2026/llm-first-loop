---
method_id: verify-deploy-liveness-by-content-identity-chain-ed6f80764adf
name: verify-deploy-liveness-by-content-identity-chain
description: 重启/发布后核验修复是否真正上线时，不要停留在重启回执 success 或组合命令的退出码上：沿 入口HTML→显式引用的hashed asset→本地dist同名文件 的 content-addressed 边做字节级身份比对（sha256+修复标识grep），后端改动再由源码新字段定位暴露端点并实测返回。入口返回307/3xx时必须先跟随重定向再提取引用；退出码0但某对比段输出为空属于空验证，应回诊该段上游fetch而非记为通过。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d0721026-9d2f-493f-ad09-a5560e92b589:1062:3a13b06bff884692fc98
evidence_refs: learning:learn:50ad48407d73
created_at: 2026-10-13T21:00:54.097471+08:00
updated_at: 2026-10-13T21:00:54.097471+08:00
---
## Trigger
服务重启/发布动作完成后，需要核验前端构建产物与后端 API 改动是否真正生效上线（而非只看重启是否成功）

## Discriminator
入口 HTML 显式引用带内容 hash 的资源文件名（如 index-*.js），且本地 dist 存在同名构建产物——这条边可一步完成线上内容身份判定，无需逐文件枚举；同时，重启回执 success 只证明进程换新，组合验证命令退出码 0 但对比段为空 = 什么都没验证，两者都不构成上线证据

## Short path
- 读 restart/状态回执：确认 succeeded、matches_desired_generation=true、无 admission barrier → 重启已落地（未知量：进程是否换新）
- 重定向感知地取入口（如 curl -sL 并打印最终状态码）：307→跟随→拿到真实 HTML；未知量：线上入口实际引用哪个资源文件
- 对 HTML 显式引用的 hashed asset：线上 sha256 对比本地 dist 同名文件，并在响应字节中 grep 修复标识字符串；未知量：线上前端是否为新构建
- 后端改动：在源码中 grep 新字段/新路由名定位暴露端点（限定 --include 与 src/ 目录范围防全库递归超时），curl 该端点实测字段存在；未知量：线上 API 是否含修复
- 全部命中即停止并输出核验表；任一验证段输出为空时停止推进，先诊断该段上游（状态码/重定向/命令范围）

## Stop conditions
- 线上 asset 与本地 dist 同名文件 sha256 一致，且修复标识字符串确实出现在线上响应字节中
- 被改动的 API 实测返回新字段/新行为
- 任一对比段输出为空：视为失败诊断点，不得继续叠加新验证或记为通过

## Verification
- 对 3xx 入口显式跟随重定向后再提取资源引用，避免把空响应当作『无引用』
- 组合命令退出码 0 但某输出段为空 → 判空验证失败，检查该段上游 fetch（状态码、重定向、路径）
- 本地比对基线必须是本次修复后刚构建出的 dist，否则先重建再比
- 源码检索限定目录与 --include，防止 60s 级全库递归超时后被迫重试

## Counterexamples
- 纯后端发布、无静态产物变更：跳过 hash 链，直接实测 API 即可
- 资源经 CDN/缓存分发：hash 不一致可能是缓存滞后而非发布失败，需 cache-bust 或版本端点裁决，不能直接判失败
- 重定向落到登录/auth 页：跟随 -L 得到的是 auth HTML、无目标 asset 引用，需先解决凭证再验证
- 本地 dist 未随本次修复重新构建：同名文件 hash 是旧基线，比对一致也不能证明新修复已上线
