---
method_id: requirements-first-three-axis-suitability-triage-88cee8448aea
name: requirements-first-three-axis-suitability-triage
description: 对“我的环境/研究栈适不适合 X（新模型、新工具）”类问题：先抓取用户给出的权威文档，抽取硬性 requirement tokens（内存数值、架构名、运行时、特殊量化特性），据此把结论分解为三个正交轴——硬件容量、栈就绪度、研究目标兼容性；硬件用单条系统命令实测比对，栈就绪度用这些 tokens 对本地关键组件做定向检索（grep/git log）而非全目录枚举，再读最近一份 qualification/evidence 文档评估切换成本与既有证据链约束；最后识别决定性轴（常是目标语义兼容性而非可行性），未验证的加载项明确标注并附最小 falsification 探针（如只下载 GGUF 头部元数据），不臆断可行也不臆断不可行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:09287651-af38-474b-954c-d2e1e665fb8e:7:2b0074dea201132d7dfa
evidence_refs: learning:learn:a7e259a3cdf4
created_at: 2026-09-20T12:53:37.687580+00:00
updated_at: 2026-09-20T12:53:37.687580+00:00
---
## Trigger
用户给出外部工件（新模型/库/工具）的权威文档链接，并问自己的目录、机器或研究栈是否“适合/兼容”它；即多轴兼容性判断题，而非单点事实查询。

## Discriminator
用户消息本身已含权威 requirements 来源（文档 URL），文档必然给出可检索的硬性 tokens（内存数值、架构名、运行时名）；硬件事实可由单条系统命令直接取得。这些当时已知事实把“枚举整个研究目录找线索”缩成三个明确未知量：硬件够不够、栈支不支持、目标合不合——其中第一个未知量完全由文档定义，本地枚举无法推进它。

## Short path
- 1. 先抓权威文档，抽取硬性 requirement tokens（内存下限、架构名、运行时、特殊量化/MTP 依赖），明确三个未知量：硬件容量、栈就绪度、目标兼容性。
- 2. 单条系统命令取硬件事实（如 sysctl 内存/芯片），与文档数值逐项比对，关闭硬件轴。
- 3. 用文档给出的架构/特性名作为搜索词，对本地关键组件做定向检索（源码 grep 架构表、git log 看 commit 是否含该特性），关闭栈就绪轴；不做全目录枚举。
- 4. 读最近一份 qualification/evidence 文档，确认既有证据链的边界（哪些 metadata 是有意不改的），评估换用 X 的切换成本。
- 5. 三轴作答，指出决定性轴；对仍未验证的项（如特殊量化布局能否被当前 commit 加载）给出最小 falsification 探针方案而不是断言。

## Stop conditions
- 三个轴各有直接证据：文档数值与实测硬件对上、架构名在本地源码当前 commit 中命中、qualification 文档约束已读。
- 已识别出决定性轴（例如目标语义不兼容使可行性轴不再关键），继续枚举其他组件不会改变结论。

## Verification
- requirement 数值与实测系统输出逐项一致（如 75GB 下限 vs 实测统一内存）。
- 文档中的架构/特性名在本地源码中有命中，且命中属于当前使用的 commit 而非仅 upstream。
- 回答中每个'未验证'断言都附带一个低成本验证方案（如仅下载元数据/头部），且不与既有 qualification 文档的既定边界矛盾。

## Counterexamples
- 用户只问纯可行性（“这台机器能不能跑”），无研究目标语境——目标兼容轴不适用，前两轴有证据即可停，不必读 qualification 链。
- 文档页只有营销文案、无硬性 requirement tokens（无数值、无架构名）——定向检索失效，须改查模型卡/发布页或直接跑最小加载探针。
- 本地栈是无源码的二进制黑盒——grep 式栈就绪度检查不可行，应改为运行时加载试验而非源码检索。
- 外部工件与本地栈没有任何可对齐的命名锚点（全新范式、非同族架构）——requirement-token 定向检索退化，此时才合理使用 broad discovery。
