---
method_id: variant-boundary-scrub-not-keyword-sweep-0c9b82fcafc5
name: variant-boundary-scrub-not-keyword-sweep
description: 当要从代码库/文档产物中剔除某个“实验性变体”，而同一 vendor 关键词在产物中同时存在合法产品用法时：不要按裸关键词做全量命中清单再逐个回退分类。先用用户决策语句解析出剔除类/保留类，以变体专属命名模式与 gated 注册块为结构边界圈定剔除闭包；内容级清洗与最终残留验证都使用变体标识符而非 vendor 裸词。泄漏基准取“真正已公开的远端树”，白名单基准取旧公开面+产品新增；不可逆删除操作先查工具权限，缺 scope 即移交用户。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1335:b7b78793feffdaf62c79
evidence_refs: learning:learn:a6c5b285efc4
created_at: 2026-10-12T10:22:13.594413+08:00
updated_at: 2026-10-12T10:22:13.594413+08:00
---
## Trigger
任务目标是剥离/清洗某个实验功能或变体（如“X 的 web provider 算实验项目，新库剥离”），且该 vendor 关键词在产物中同时命中合法产品用法与待剔除变体，用户决策语句已显式限定变体范围。

## Discriminator
两个当时已可见的事实：(1) 用户决策语句已把范围限定到变体（“deepseek web provider”），vendor 裸词命中集（232 文件）从一开始就超采；(2) 首个 chatgpt 命中清单已暴露变体专属命名模式（*_web/*_page/*_surface/*_transport、test_*_web_*）及可定位的注册装配文件，足以直接推出变体文件闭包。

## Short path
- 把用户决策解析成两张清单：剔除类（chatgpt 全部 + deepseek 仅 web 变体）与保留类（deepseek API 产品），未知量=各自具体落点
- 用变体专属标识符定向枚举剔除文件闭包，而非 vendor 裸词全量命中后再人工分类
- 读注册/装配点确认边界（独立 gated 注册块）并摘除对应段，未知量=共享文件中哪些段属于变体
- 内容级（docs/CHANGELOG/experiences/README）用同一变体标识符扫描，逐条分类“删除/改写/无需动”；保留类命中确认后不动
- 白名单基准 = 旧公开树路径集 + 产品类新增文件；内部产物（promotion/methods/poc 等）排除；泄漏现状以远端公开 ref 为准，与本地缓存清单矛盾时先重对权威 ref
- 构建公开快照 → 全量测试 + 前端构建 + 变体标识符残留扫描，全部通过即停止发现动作

## Stop conditions
- 剔除集、注册块摘除、内容清洗三面均与用户决策的剔除/保留分类一致
- 残留扫描仅剩与变体无语义关联的通用名词级引用
- 不可逆删除步骤发现工具缺 scope：停止并给出用户可选执行方式，不代行、不绕过

## Verification
- 剔除后的全量测试与前端构建全绿
- 用变体专属标识符（非 vendor 裸词）对最终产物做残留 grep，并逐条确认剩余命中无语义关联
- 逐类核对新增文件：product（src/tests/scripts）vs 内部产物，白名单外零带入
- 不可逆操作前核对权限/授权链路，确认执行主体

## Counterexamples
- 关键词在产物中只有单一用法（无产品/实验歧义）时：直接关键词全量剔除即可，先划变体边界是多余步骤
- 变体没有专属命名/模块边界，而是散落在共享文件的条件分支里：命名模式推断不安全，必须逐文件内容级审查
- 本方法只界定“变体范围”维度；密钥、内部端点等敏感面不会被变体标识符覆盖，仍需独立 secret 扫描
- 远端公开树与本地缓存清单不一致（存在并发写者，如远端 ref 已被推进）：不能沿用本地盘点动手，须先按权威远端 ref 重算泄漏基准
