---
method_id: derive-validator-contract-from-pinned-source-dd2083babf34
name: derive-validator-contract-from-pinned-source
description: 构建必须复刻或执行另一组件 fail-closed 验收逻辑的预检/校验/oracle 工具时，工具中的常量与分支必须逐字转录自目标 pinned 版本的真实验证源码——读过同一文件的部分内容不等于读过被测分支；执行型 oracle 子进程必须绑定到早前已验证含有目标依赖的解释器/环境。凭记忆硬编码契约（如编造必填键）会对真实配置产生错误裁决（把合法配置判成内容缺陷），并在报告中留下需要事后公开更正的中间结论。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:457:ee491d6211b9e42e8589
evidence_refs: learning:learn:15f99fe4d7cf
created_at: 2026-10-09T20:00:20.380947+08:00
updated_at: 2026-10-09T20:00:20.380947+08:00
---
## Trigger
事故后编写发布前置校验工具（preflight/validator/oracle），该工具需静态复刻或以子进程执行另一组件的启动/验收逻辑（配置校验、门禁分支），且目标源码路径已定位、版本已 pin（如 .releases/<sha> 工件）。

## Discriminator
写入任何硬编码期望之前，三个事实已在同 episode 中可见：(1) 目标 loader 验证源码文件已被打开并部分显示，被测 schema 分支位于未读的相邻行段；(2) 被测真实配置的完整 JSON 键集已 dump 在案；(3) 含目标依赖的解释器（项目 .venv）已在早前检查输出中确认。三者把『权威契约是什么』从猜测空间缩成一次读取即可确证。

## Short path
- 先完整读取 pinned 目标版本中被测 schema 的验证分支（同文件相邻行段），得到权威键集/窗口/必填项
- 静态检查常量逐字转录该分支；测试夹具从已 dump 的真实配置键集派生，不凭想象增删键
- oracle 子进程绑定到已确认含依赖的解释器（.venv），并断言其导入的是 pinned 工件路径而非旧副本
- 跑测试矩阵；出现不一致时把工具常量与 pinned 源码分支 diff，以源码为真值修正工具而非修正结论
- 真实当前状态返回预期裁决、事故回放夹具按预期 FAIL 后即停止

## Stop conditions
- 预检矩阵对真实当前状态与事故回放夹具均给出预期裁决
- 目标 loader 的每个 fail-closed 分支都映射到一条显式检查
- 静态检查与 loader oracle 的任何不一致均已对照 pinned 源码解决；未解决前不对生产配置输出缺陷结论

## Verification
- 工具常量与 pinned 版本验证分支逐字比对一致
- oracle 子进程在验证过的解释器下导入成功，且加载路径确为 pinned 工件（无静默旧副本回退）
- 矩阵包含事故回放（必须 FAIL）、合法场景（候选版 PASS）与回滚基线行为断言

## Counterexamples
- 目标验收逻辑在 pinned 版本不可读（闭源二进制/远端服务）——此时只能经验探测，不应阻塞在找源码
- 被验证的契约是尚无实现的新设计——假设即规格，应与设计者确认而非读源码
- 无分支逻辑的平凡检查（文件存在/端口可达）——逐字转录源码属过度工程
- 运行时实际加载版本与已读源码不同且无法 pin——此时读取的源码不构成权威契约，需先固定版本再转录
