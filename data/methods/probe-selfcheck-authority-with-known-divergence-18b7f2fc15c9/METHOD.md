---
method_id: probe-selfcheck-authority-with-known-divergence-18b7f2fc15c9
name: probe-selfcheck-authority-with-known-divergence
description: 继承『按建议执行』类计划、且计划假设既有新鲜度/一致性检查能看见某类偏差（未提交改动、HEAD 漂移）、或据此要新建标记机制时，先别动手实现：①用机制语义关键词检索既有实现，命中死代码（定义完整但零调用方）则任务形态是『接线』不是『新建』；②直读该检查的身份解析处——参考 git/文件身份若经 CWD 或 workspace 根环境变量解析，release 部署下会读部署副本自带的 .git，恒报一致：这是结构性自证失明，不是缺功能；③用已知分歧探针定谳：会话早期 git log/status 已给出真值（仓库 HEAD、dirty 状态），一次运行检查并对照其报告值即可暴露恒等。判定成立后修身份推导（如从 .releases/<sha>/ 路径结构反推源仓根，或进程 import 期快照指纹）、接上死代码入口而非新建平行机制；修复有效性必须由同一探针翻转（分歧能被点名检出）证明，判不出的输出 unknown，绝不退化成『一致』。
aliases: 检查说一致但代码没生效, 恒报一致的新鲜度检查, 部署副本 git 身份读错对象, 假一致自证, 守卫代码漂移检测不到, 用已知 HEAD 分歧试探自检
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:1850:2703dc727575e0fc6d4c
evidence_refs: learning:learn:a3e6f792a038
created_at: 2026-11-01T13:36:23.493749+08:00
updated_at: 2026-11-01T13:36:23.493749+08:00
---
## Trigger
继承的建议/计划假设既有新鲜度或一致性检查能看见某类偏差（如未提交改动、HEAD 漂移），或据此要新建标记/闸门；而该检查的参考身份由自身运行位置（CWD 或 workspace 根环境变量）解析

## Discriminator
会话早期 git log/status 已给出权威身份真值（仓库 HEAD、dirty 状态）；一次运行该检查并把报告的 git_head/dirty 与真值对照——报告 HEAD≠仓库 HEAD、且 dirty=false 而仓库实际有改动 ⇒ 检查读的是部署副本自带 .git，恒等一致，属结构性失明而非缺功能

## Short path
- 先用机制语义关键词检索既有实现，分三种态：不存在 / 死代码（定义在、零调用方、零测试）/ 已接线；死代码则任务形态是接上，不是新建
- 直读该检查的身份解析处：参考身份是否经 CWD 或 workspace 环境变量解析？若是，release 部署下会指向副本自身
- 做已知分歧探针：检查报告值 vs 本会话已知的仓库 HEAD/dirty 真值
- 探针显示恒一致而真值有分歧 ⇒ 修身份推导（.releases/<sha>/ 反推源仓根，或 import 期指纹快照），并接上死代码入口
- 修复有效性由同一探针翻转证明（能点名具体漂移文件）；判不出的输出 unknown，不退化成一致

## Stop conditions
- 探针能检出人为制造的分歧 ⇒ 检查权威，按原计划做功能增强即可
- 检索确认仓库无任何同语义机制 ⇒ 新建合理，死代码接线步骤不适用
- 已按探针翻转验证修复并接好入口 ⇒ 停止，不顺手加新闸门或新数据源

## Verification
- 端到端模拟部署形态：副本放旧码、工作树放新码，检查应点名具体漂移文件
- 真实部署对照：运行中服务报告的身份 vs 权威仓 HEAD 与工作树差异
- 全量单测与改动前基线逐条对照，失败差集零新增

## Counterexamples
- 检查直接读权威仓且能正确报出 HEAD 漂移：计划假设成立，直接增强即可，无需身份推导改造
- 运行环境永远从仓工作树启动、无 release 副本：workspace 环境变量即权威仓，不存在恒等问题
- 关心的偏差与身份无关（纯运行时配置、网络态）：HEAD/dirty 探针不适用
- 只需向用户解释上次修复为何『看着生效』：证明恒等机制即可停，不必当场重写整套检查
