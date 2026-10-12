---
method_id: mine-canonical-ids-and-role-notes-before-search-or-attempt-8f7fffa1d71b
name: mine-canonical-ids-and-role-notes-before-search-or-attempt
description: 受管环境里查某机制（发布/重启/升级）的确切命令与权限时，最新回执往往已含规范标识符（schema 名、模块路径、generation/CAS 词汇），权威文档也常标注动作执行角色。先用这些已出现的字面量做主键直查 docs/src 命中权威小节，并在发起可变更动作前消费角色注记（如'由 operator 发布'）；边界存疑时用只读源码核对，而不是靠一次被 fence 拦截的尝试来发现权限。本次可省去语义词宽搜、旧指南全文通读、被拦截尝试及其事后确认约 6 次调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:862:0017742fefd9c835849a
evidence_refs: learning:learn:df7ef5b9d70f
created_at: 2026-09-19T11:00:37.612830+00:00
updated_at: 2026-09-19T11:00:37.612830+00:00
---
## Trigger
在已有控制面回执（部署 status/show、运行时记录）的背景下，需要查明某受管操作的确切执行命令或权限边界，且尚未定位到权威文档/实现时的机制发现阶段。

## Discriminator
回执中是否出现能唯一命名目标子系统的规范字面量（如 schema 'managed-service-deployment/v1'、模块 'runtime.service_control'、generation/CAS 词汇），以及候选权威文本是否含角色限定语（operator/管理员/调用方）标注动作执行者。本例前置核验回执已含 schema 字面量，且 grep 权威指南时第 159 行已明示'必须先由 operator 发布'——两者均在任何宽搜索或 publish 尝试之前就可观测。

## Short path
- 读最新回执，提取规范标识符与角色限定词；明确本次未知量=确切命令+谁有权执行
- 用标识符字面量 grep docs/ 与 src/，直接命中权威文档相关小节（如 restart-guide 的 publish/§控制面节）与实现文件
- 只读命中小节，同时抽取两件事：命令签名（含 expected-generation 等 CAS 参数）与执行角色边界
- 做执行前检查（目标区间影响面 diff、venv、服务空闲度）后推进可自主部分：ff-only 前移 main、show 确认当前代数
- 对角色专属动作直接产出委托包：operator 终端命令 + 我方后续 service_control(restart) 计划；仅当怀疑文档与运行时不一致时，用只读源码核对 fence，而非发起变更尝试

## Stop conditions
- 已从与回执标识符互证一致的权威来源取得确切命令与执行角色
- 自主/委托分工明确，且委托指令参数与当前 show 观测逐项对齐
- 标识符 grep 无命中或命中与回执矛盾（文档滞后/改名）→ 退出本方法，退回标题级/目录级发现

## Verification
- 命中的文档/源码与回执中同一规范字面量（schema 名/模块名）互相印证
- 委托命令的 expected-generation、roots、data-dir 与刚观测的 show 输出一致
- 角色判断有双重证据（文档角色注记 + 源码 fence 或只读 CLI 探测），不以被拦截尝试作为唯一证据

## Counterexamples
- 回执标识符在 docs/src 已无命中（子系统改名、文档滞后）：字面量主键失效，应改走标题级枚举，不要反复换同义关键字死磕
- 文档角色注记过时（新版已放开 fence）：仅凭旧文档放弃执行会把本可自主完成的动作误判为需委托，此时应以只读源码或 --help 核对边界
- 没有任何回执可携带标识符的全新环境：宽发现本就是正确第一步，本方法不适用
- 动作本身只读、幂等且廉价时，直接尝试以确认能力边界可能更短；本方法仅约束控制面变更类动作
