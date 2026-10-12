---
method_id: probe-real-routes-from-local-source-not-guessed-paths-796113098ac1
name: probe-real-routes-from-local-source-not-guessed-paths
description: 对自有/自托管 HTTP 服务做端点验证时，若部署回执已给出 code_root 且路由定义可在本地一条 grep 枚举，应先读路由装饰器拿到真实端点集，再只探测真实路径。盲猜路径的 404 无法区分『猜错路径』与『服务缺功能/异常』，产生归因歧义；而权威路由枚举一次就把候选空间缩到真值。仅当无本地源码（外部第三方 API）或只需判定进程存活时，才退回单点探测或官方文档。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:502:1990d4ceee4b383e9461
evidence_refs: learning:learn:c1ef46856253
created_at: 2026-09-19T02:34:35.438247+00:00
updated_at: 2026-09-19T02:34:35.438247+00:00
---
## Trigger
需要验证自托管服务的健康/业务端点，准备对若干猜测的 API 路径发起探测，且该服务源码在本地已知路径（code_root/仓库内 web 路由模块）可读

## Discriminator
最早的 status 回执已含 code_root（本地仓库可读），且路由定义（如 @router.get/post 装饰器）可一条 grep 完整枚举真实端点；此时猜测路径得到的 404 只反映猜测本身，不能作为服务异常证据，属于可避免的枚举扩散

## Short path
- 从 runtime 配置（toml/.env）确定端口与 host，未知量：服务地址
- 在本地仓库 grep 路由装饰器，一次性枚举真实端点（含 /health 与目标业务路由），未知量：真实路径集合
- 只探测 / 或 /health（活性+鉴权语义）与目标业务路由各一次，未知量：端点是否在线且行为符合预期
- 将观测状态码按语义对齐（303 重定向、401 鉴权质询=在线且鉴权生效，非故障），并与路由定义比对一致后停止

## Stop conditions
- 活性已由 / 或 /health 的语义化响应证明，且关心的业务路由在路由定义中存在并返回预期状态码
- 本地 checkout 与线上部署 git_head 不一致时，停止用本地路由表代表线上表面，改以实测或部署方文档为准

## Verification
- 每个被探测的 API 路径都出现在路由定义 grep 的输出中，无凭空猜测路径
- 401/303 等状态码按鉴权/重定向语义解释为服务在线，与配置预期一致后即闭合，不再追加新的猜测路径探测

## Counterexamples
- 第三方外部 API 无本地源码：只能依赖官方文档/OpenAPI/发现端点，本方法不可用
- 仅需判定进程是否监听端口：单次 /health 探测即可证明，先做全量路由枚举属过度准备
- 本地代码与线上部署版本不一致（git_head 不匹配）：本地路由枚举可能不反映真实表面，须以实测或部署侧真值为准
