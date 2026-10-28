---
method_id: verify-deploy-liveness-by-content-identity-chain-f2d4bc532d53
name: verify-deploy-liveness-by-content-identity-chain
description: 重启/发布后判断修复是否真的上线：取入口跟随重定向后的 hashed asset、比字节与修复标识、实测后端端点字段；三段全非空才算上线。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:77:18e956509caf4904c181
evidence_refs: learning:learn:50ad48407d73
parent_ref: method:verify-deploy-liveness-by-content-identity-chain-ed6f80764adf
created_at: 2026-10-20T00:06:34.023993+08:00
updated_at: 2026-10-20T00:06:34.023993+08:00
---
## Trigger
重启/发布刚完成，需要判断本次修复的构建产物与接口改动是否真正上线。

## Discriminator
入口 HTML 显式引用带内容 hash 的资源名，且本地有本次构建的 dist 同名文件——这条边用一次字节比对就能给出线上内容身份；而重启回执 success 只证明进程换新，不证明新构建在位。

## Short path
1. 入口：curl -sL 取最终状态码与 HTML，再从中提取显式引用的 hashed 资源名（不要在 3xx 原始响应体上提取）。
2. 前端：线上该资源字节的 sha256 对比本地 dist 同名文件，并在响应字节里 grep 修复标识字符串。
3. 后端：在 src/ 限定范围内定位新字段暴露的端点，curl 实测该字段存在。

## Stop conditions
任一段输出为空（命令退出码 0 但该段无内容）→ 停在该段回诊上游（状态码/重定向/路径），不得记为通过。

## Verification
- 比对基线必须是本次修复后重新构建的 dist；拿旧 dist 比对，一致也不构成上线证据。
- 三段全部有非空命中才判上线，输出核验表（asset hash、修复标识、接口字段）。

## Counterexamples
资源经 CDN/缓存分发：hash 不一致可能是缓存滞后而非发布失败，需 cache-bust 或版本端点裁决后再判。
