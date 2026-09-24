---
method_id: effective-config-composition-before-version-attribution-7dcc17b75d47
name: effective-config-composition-before-version-attribution
description: 工具输出异常只在特定调用形态（flag 组合）下出现时，先在同一环境解析『本地配置⊕显式 flag』的有效叠加（如 addopts 内嵌 -q 与命令行 -q 叠成 -qq），并用同环境单变量切换验证；只有本地配置与插件被实验排除后，才做跨环境版本对照。禁止依据同时改变解释器与版本的双变量对照直接宣布根因并 pin 依赖版本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:1077:84503470abd6a8494117
evidence_refs: learning:learn:a6fd4ee7f136
created_at: 2026-09-24T01:53:10.362729+00:00
updated_at: 2026-09-24T01:53:10.362729+00:00
---
## Trigger
根因定位阶段：某工具行为异常只在特定 flag/调用组合下复现，且候选原因同时存在本地插件、本地配置、工具版本等多个假设时的分叉点。

## Discriminator
触发异常的调用所显式携带的 flag 自己已知（命令是本会话敲的），且本地配置文件（pyproject/ini 的 addopts 等）已在此前 grep 结果中被指到、一步可读可叠加；定向 grep 已排除本地 terminal/sessionfinish 钩子。此时『有效选项 = 本地配置 ⊕ 显式 flag』是比『版本差异』更窄、更可检验的未知量，应优先消解。

## Short path
- 用最小用例在同环境复现异常，记录确切输出形态（作为后续对照基线）
- 定向 grep 本地插件/钩子（terminal/sessionfinish 等），排除或确认本地插件假设
- 读本地配置（addopts/ini/env），计算有效选项叠加，寻找与显式 flag 的重复或冲突
- 同环境单变量切换复跑（去掉显式 flag 或 -o 覆盖配置）：异常消失即锁定配置叠加为根因，落最小配置修复
- 仅当配置叠加被同环境实验证伪时，才进入跨环境版本定位，且对照必须一次只变一个变量（仅版本或仅环境）
- 用最初失败的原始命令原样复跑验证恢复后停止，不再枚举其他环境

## Stop conditions
- 同环境单变量切换使异常消失，且原始失败命令不变更任何 flag 即恢复 -> 停止发现，落最小修复
- 本地配置与本地插件均被同环境实验彻底排除 -> 停止本方法，转入版本/环境维度定位
- 异常与调用 flag/形态无关（任何形态都复现）-> 本方法不适用，转输入/数据维度排查

## Verification
- 修复后用最初失败的原始命令（不改任何 flag）复跑，确认输出行为恢复
- 检查最终 diff 只含最小配置改动，未残留依赖版本 pin 等中间误判产物
- 跨环境对照结果只有在单变量（仅版本不同、解释器与环境一致）时才可作为根因证据

## Counterexamples
- 用 -o addopts='' 等方式清空配置后同环境复跑异常仍在：配置叠加假设被证伪，应直接做版本二分，不应继续翻配置
- 异常由环境专属插件集差异引起且本地配置干净：跨环境 diff 本身就是因果路径，先查配置反而绕远
- 异常由特定输入/数据触发而与 flag 组合无关：配置/版本归因框架均不适用
- 任务目标本身就是版本兼容性验证（版本矩阵）：版本对照是目标而非弯路
