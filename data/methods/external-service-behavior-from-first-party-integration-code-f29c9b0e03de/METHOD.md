---
method_id: external-service-behavior-from-first-party-integration-code-f29c9b0e03de
name: external-service-behavior-from-first-party-integration-code
description: 当用户问题询问某外部服务/产品的自身行为机制（如 ChatGPT 网页版是否有自己的上下文管理），而本地仓库初始文件检索已命中以该服务命名的成套第一方集成实现时，把该集成代码当作服务可观察行为的首要证据源：集成层为适配服务侧行为而生，其设计注释与阈值常量（如 rollover 上限、conversation_id 恢复依赖）直接记录'服务端有历史/有状态'这一事实，验证成本远低于开放网检索。若第一次通用 web 搜索整页为 SEO/镜像/聚合噪音，不要对同一渠道换词重查，直接转向集成代码；外部核验至多一次精确尝试，失败则把产品层细节诚实标注为训练知识未核验，不与代码证据混写。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:899:cd8c6987219598e26469
evidence_refs: learning:learn:3e16de037b41
created_at: 2026-10-11T14:34:00.915697+08:00
updated_at: 2026-10-11T14:34:00.915697+08:00
---
## Trigger
问题询问外部服务/产品自身的行为机制，且第一步本地检索已显示仓库存在该服务的成套第一方集成文件（如 *web*.py、surface、transport、page、session binding/rollover/health 等命名群）。

## Discriminator
两个当时已可见的事实：(1) 仓库存在成套的会话绑定/滚动/恢复机制文件名，提示集成方必须管理服务端会话状态——这构成一条可廉价证实/证伪的窄证据边（读指定文件即可）；(2) 第一次 web 搜索 8 条结果全部为 SEO/镜像/聚合站、零技术内容，说明该渠道对此热门商业话题已被淹没，换词重试同渠道的期望收益≈0；而参数知识已能回答 yes/no 核心，只缺可引用证据。

## Short path
- 未知量：该服务是否自带会话/上下文状态？从初始文件清单选定集成主文件（provider/web 实现及 binding/rollover 伴随文件），形成'读代码验证'假设。
- 对集成层做一次关键词内容搜索（rollover/history/accumulate/window/segment 等）定位设计注释与阈值；本集该步一次命中 'bounded rollover accounting' 与 'provider-owned history'。
- 读取命中区域，提取服务侧行为证据：provider-owned history 的存在、依赖 conversation_id/URL 恢复线程、为防 provider 历史无界膨胀而设的 segment_max_* 阈值。
- 至多一次直接抓取权威一手文档补充产品层细节；403 或噪音即停止外部核验。
- 成稿并分层标注证据来源：代码引证=已核实；产品细节=训练知识+本次核验未成功；停止。

## Stop conditions
- 集成层注释/常量已给出与问题直接对应的行为证据并写入答案。
- 外部核验渠道（一次精确搜索或一次直接抓取）失败后，不再对同一渠道换词重试，答案改用'训练知识+未核验'标注收尾。
- 内容搜索未命中任何与问题相关的机制关键词，说明该判别边断裂，转入常规文档/搜索路径。

## Verification
- 每条服务侧行为断言可指到具体文件:行号的注释原文，或明确标注为训练知识/未核验，二者不混。
- 引用的机制与所问行为语义对应（如 rollover 阈值确实针对 provider 历史累积，而非无关机制）。
- 答案明确区分'代码已核实层'与'产品知识未核验层'，并给出一手文档指引。

## Counterexamples
- 问题问外部服务当前/最新能力（如刚发布的特性或具体数值）：本地集成代码可能滞后，必须以实时一手文档为准，代码只作旁证。
- 仓库中不存在该服务的第一方集成代码，或仅为未触及所问行为的第三方依赖：判别边不存在，应走常规搜索/文档路径。
- 第一次 web 搜索已返回官方一手来源（help center/CHANGELOG/规格文档）：直接读它，无需转向集成代码。
- 通用搜索对该话题首查即有权威结果（非 SEO 噪音）：渠道未被淹没，'禁止同渠道换词重试'的约束不成立。
