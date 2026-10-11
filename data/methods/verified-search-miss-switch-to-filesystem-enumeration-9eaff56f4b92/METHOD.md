---
method_id: verified-search-miss-switch-to-filesystem-enumeration-9eaff56f4b92
name: verified-search-miss-switch-to-filesystem-enumeration
description: 当内容/文件名搜索对目标域连续空命中，且至少一次空命中构成『在手反例』——你已读过的文件包含该查询词、其文件名匹配该 pattern，工具仍报无匹配——应把空命中读作索引覆盖缺口（本集检索对 2026-10-11/12 当日新文档系统性失明），停止生成关键词变体，切换为确定性枚举：按在手文件的路径与命名主干 ls/glob 一跳定位版本前代/同族文档。本集前段（约 8 次换词搜索定位 v2 文档）属 resume-continuation-via-named-provenance 的领域，本卡只覆盖索引被证伪之后的检索机制切换。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:436:9bae5542226e5a162ca0
evidence_refs: learning:learn:72f6222e0bad
created_at: 2026-10-12T06:49:50.339638+08:00
updated_at: 2026-10-12T06:49:50.339638+08:00
---
## Trigger
连续 search_files/search_docs 空命中后，其中至少一次可被当时在手事实证伪：目标文件名匹配所用 pattern、且你已读过的正文含该查询词，回执仍报无匹配；或需要定位在手文档的版本前代/同族文件（如 v2 需 v1、同前缀系列文档）。

## Discriminator
已读文件本身即反例：docs/DESIGN-20261012-persistent-bot-team-v2.md 文件名匹配 DESIGN-2026101*.md 且第 10 行含『阶段 1』，而对应 content 搜索仍返回无匹配（『Mode-B』『管家』对已证实存在的 v1/v2 文档同样空命中）⇒ 空命中反映索引未覆盖该批文件，而非词不达意。判别词必须是当时已见过的词，不得用事后才读到的内容构造。

## Short path
- 空命中中出现『在手反例』时，冻结关键词派生路线，不再对同一索引换措辞重试
- 用在手文件的路径+命名主干做一次确定性枚举：ls <dir> | grep -iE '<stem|team|version>'，定位版本前代/同族文件名
- 命中后沿用已验证模式：wc -l + grep -n '^#' 拿章节行号，按行段读取所需小节（如 v1 §7/§9），不整读不盲扫
- 取得目标事实（阶段 0/1/2 定义）即停止发现，转入综合/执行

## Stop conditions
- 枚举命中目标文件并读得所需章节事实
- 枚举也为空：覆盖缺口假设被证伪，转回命名 provenance（被引文档、git 面），而非继续换词搜索

## Verification
- 核对命中文件与在手 provenance 一致（v2 header『依据 v1/v1.1、取代 v1 §6.3/§7』与文件名/日期吻合）
- 把『索引缺口』结论建立在至少一条可复现正例上：已读内容含查询词仍空命中；无正例则不得断言索引失效

## Counterexamples
- 查询词只是猜测、无在先证据表明存在于语料：一两次空命中只说明词不对，应换词或走命名 provenance，不应立即改枚举
- 超大仓库且命名规则未知、目录枚举代价高：索引搜索仍是首选，本卡不适用
- 工具回执显式声明索引范围或未索引路径：空命中按声明解释，勿推断缺口
- 搜索正常命中时（如本集首次搜索命中 10 条）勿泛化为不信任索引，本卡仅在反例出现后启用
