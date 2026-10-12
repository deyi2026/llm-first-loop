---
method_id: binary-upgrade-risk-probe-hygiene-c0a63cb1a0fa
name: binary-upgrade-risk-probe-hygiene
description: 评估二进制/CLI升级是否引入新行为时，用已装版本、目标版本、官方changelog和本地触发文件三角验证；若需下载目标二进制到临时目录，先创建并验证探测目录，避免跨轮使用已清理的临时路径。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f7469d7b-59d1-494b-955f-c9153320141e:414:61dfd885c00506fea419
evidence_refs: learning:learn:d992a6a9c9d2
created_at: 2026-09-20T21:18:46.258252+00:00
updated_at: 2026-09-20T21:18:46.258252+00:00
---
## Trigger
需要判断升级是否引入新行为或破坏性变更，且需检查二进制字符串、默认值或本地配置触发条件

## Discriminator
存在已装版本与目标版本；功能可能由本地文件/配置触发；探测目录位于临时目录或跨轮复用

## Short path
- 确认当前安装路径、版本和可启动性
- 在已装二进制中检索功能标记或默认值，确认当前是否已有该行为
- 拉取官方changelog，定位功能引入、默认开启、回归修复的版本边界
- 检查本地配置或文件是否满足触发条件，并判断其语义是否会被新版本加载
- 为目标版本建立持久探测目录，先验证目录存在再下载、解包并检索默认值
- 选择避开风险边界的稳定版本，或先设置缓解开关、占位配置

## Stop conditions
- 已确认目标版本默认行为、本地触发条件和回滚路径
- 探测目录失效且重建成本高于直接选择安全版本
- 二进制检查不可行时，以changelog和本地配置证据给出风险边界

## Verification
- 二进制字符串或默认值与changelog版本一致
- 本地触发文件确实存在且无覆盖文件
- 目标版本检查来自预期版本文件，而非旧目录或缺失目录
- 回滚版本可获取且安装方式可恢复

## Counterexamples
- 纯配置或文档升级，无二进制行为差异
- 功能由服务端控制，本地文件不会触发
- 已有覆盖文件或显式配置使新默认不生效
- 目标版本不可下载，或任务只要求当前版本状态
