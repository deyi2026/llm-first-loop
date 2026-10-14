---
method_id: verify-canonical-path-before-absence-claim-then-probe-runtime-eeb820e54a31
name: verify-canonical-path-before-absence-claim-then-probe-runtime
description: 用户报『功能不见了』时，不要用被 .releases/ 等快照目录刷屏且明示截断的宽搜索 miss 去推断『主树没有』：先用一次对 canonical 位置的确定性检查（ls 目录、精确 grep 挂载/路由）裁决『代码是否存在』；存在则立刻分叉到运行时层（定位进程端口→curl 功能 API 与入口页→核对所发构建），把『看不见』收敛到 UI 可见性层。本集曾据一次大小写敏感的 glob miss 得出『主树似乎找不到 knowledge 文件』的错误中途结论，之后 26 次工具调用才完成本可 5~6 步完成的分层验证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8a4d82d5-d7f7-4945-a6b0-99ad4faadaff:1:6e172584b246c3af6487
evidence_refs: learning:learn:cb9259721fc6
created_at: 2026-10-13T21:12:41.646883+08:00
updated_at: 2026-10-13T21:12:41.646883+08:00
---
## Trigger
用户/系统报告某功能、面板或内容『不见了』，需要判定存在性与所在层（代码/构建/运行时）；或宽搜索回执明示截断、命中被快照/副本目录刷屏后出现 miss，且正要据此下『不存在』的结论。

## Discriminator
搜索回执是否明示『截断显示前 N 条』；命中是否集中于 .releases/、node_modules 等副本路径，而 canonical 主树路径（无副本前缀的 src/、tests/ 命中）其实已出现在结果中；glob miss 是否可能源于大小写敏感或模式语法而非真实缺失——任一成立则该 miss 不构成存在性证据。

## Short path
- 对报告对象的 canonical 位置做一次直接确定性检查：ls 组件目录、精确 grep 路由/挂载点，裁决『代码是否存在』
- 存在 → 排除『被删』假设，未知量转为『运行中的服务是否提供该功能』
- 定位运行进程与监听端口，一次 curl 功能 API 与入口页，核对服务端返回数据与所发构建版本
- 运行时正常 → 结论收敛到 UI 可见性层（布局/导航/滚动/缓存），按该层继续而非再扫代码
- 仅当直接检查证实对象确实不在时才转入 git 历史/回滚记录；任一层被证伪才扩大搜索范围

## Stop conditions
- canonical 检查 + 一次运行时探测已把『不见了』定位到具体一层且有直接证据支撑
- 直接检查证实对象不存在 → 转查 git log/分支差异，停止继续宽搜索

## Verification
- 结论中每个『存在/正常』断言都有对应直接证据：目录项、curl 响应体、所发资源的 hash/时间戳
- 复查全程：不存在任何仅凭截断或被副本刷屏的搜索 miss 得出的负断言

## Counterexamples
- 对象确实被删除（revert/分支切换）：canonical ls 同样 miss，正确下一跳是 git log/diff，而非按本卡推定『存在』
- 报告的是数据/记录消失而非 UI 功能：应先查 store/API 数据面，检查前端代码没有信息量
- 干净的搜索 miss（无截断、无副本刷屏、已排除大小写因素）：搜索本身就是可信的存在性证据，无需再补直接检查
