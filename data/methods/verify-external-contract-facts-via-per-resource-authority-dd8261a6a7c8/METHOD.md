---
method_id: verify-external-contract-facts-via-per-resource-authority-dd8261a6a7c8
name: verify-external-contract-facts-via-per-resource-authority
description: 把外部服务契约事实（模型 id、端点、定价、wire 形态、预检端点）冻结进预注册前，按字段类型选定权威来源逐项复核：聚合列表缺失≠资源不存在，用 per-resource 权威端点一次拿到存在性/快照/定价；示例代码块是客户端渲染就改从静态 guide/tutorial 取等价事实；预检端点用无凭据状态码判定（401=存在且需鉴权，404=不存在）；凭据只验格式不暴露值。可修正上一轮基于聚合列表或渲染页面得出的过期认知。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:584:949ca9c7e21c8cffc413
evidence_refs: learning:learn:6cdafa011e0c
created_at: 2026-10-15T12:17:58.092034+08:00
updated_at: 2026-10-15T12:17:58.092034+08:00
---
## Trigger
准备把外部服务的契约字段冻结进预注册/设计文档，或聚合列表、既有文档断言与预期出现矛盾（如目标模型不在公共列表但文档称已上架）时。

## Discriminator
列表口径与资源口径的差别在当时即可见：聚合列表的缺失只说明列表收录范围（可能只收路由/主推变体），per-resource 权威端点（如 GET /models/{id}/endpoints）才是存在性+快照+定价的单一权威回执；示例代码块外层若为 BAILOUT_TO_CLIENT_SIDE_RENDERING 模板，静态抓取永远为空，等价事实在页面链接的静态 guide/tutorial 正文；无凭据请求返回 401/403 证明端点存在、404 证明不存在。

## Short path
- 先用 awk 只验凭据格式（条数/长度/前缀/无引号空格），值零暴露
- 对每个要钉的模型 id 直接调 per-resource 权威端点，一次调用同时解决存在性、快照后缀、定价、context/modality 四个未知量
- 聚合列表与文档矛盾时以该回执为准裁决，不扫全站页面或换关键词重查；资源页仅用于确认 200 与 surface 线索
- wire 形态与鉴权头从官方静态 guide/tutorial 的 curl 示例提取；遇到渲染 bailout 块立即改道静态来源，不重试抓该块；含重转义的提取脚本写临时 .py 文件而非 heredoc
- 预检端点以无凭据状态码探测：401→钉它，404→排除；按最小变更原则选定 surface 后冻结四字段（endpoint/凭据名/模型 id/resolved 合法集）
- 冻结后跑 drift 规则验证语义（别名精确=非漂移、别名+快照后缀=非漂移、其他版本=漂移）

## Stop conditions
- 四类契约字段均已由各自权威来源回执验证，且关键值在至少 2 个一手来源交叉一致
- per-resource 端点本身也 404 时停止按原 id 冻结，转版本页/更名排查

## Verification
- 权威端点回执的 id/快照后缀与冻结别名规则一致，drift 三例测试全对
- 端点路径、鉴权头、body 字段能同时被权威 API 回执与静态文档示例印证
- 凭据值未出现在任何输出/Evidence（仅 count/len/prefix）

## Counterexamples
- 内部代码库 API 契约核验走 method-repo-api-discovery（定义面/调用点一次查证），不适用外部服务探测阶梯
- 静态文档已直接包含全部所需事实时直接引用并停止，无需逐字段探测
- per-resource 端点也 404 时，聚合列表缺失转为存在性反证，应转向更名/版本排查而非坚持原 id
- 资源存在并发写者、要对共享记录下终局断言时用 fresh-read-authoritative-record-before-finality-claim（问题是重读时机而非来源选择）
- 实验设计与预注册结构本身归 method-ab-experiment 管，本方法只管外部事实的来源选择与验证
