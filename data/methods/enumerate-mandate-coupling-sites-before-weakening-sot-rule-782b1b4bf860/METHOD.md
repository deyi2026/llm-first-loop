---
method_id: enumerate-mandate-coupling-sites-before-weakening-sot-rule-782b1b4bf860
name: enumerate-mandate-coupling-sites-before-weakening-sot-rule
description: 削弱/豁免 SoT 规则文档中的强制义务时，编辑面不是用户引用的那一段，而是与该义务特征 token（工具名/义务短语）耦合的全部站点：其他条款交叉引用、governance 文档、按精确短语断言文档措辞的同步测试、以及残留副本。改前用一次跨 docs/ 与 tests/ 的 token grep 枚举耦合面，把被测试断言的短语当承重结构（保留或与测试同批改），单次通过完成全部修改，再以同步测试+残留 grep 收口。本集教训：自由改写丢掉被断言短语"模型收益自评"，改后 test_ai_rules_sync.py 断言失败才返工补回。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:533:917e1fdc4bef256f9386
evidence_refs: learning:learn:f04d04fd627d
created_at: 2026-10-18T00:11:21.028002+08:00
updated_at: 2026-10-18T00:11:21.028002+08:00
---
## Trigger
用户要求削弱、豁免或移除一条记录在仓库 SoT 规则/政策文档中的强制义务（如"所有实际使用必须 record_use"），且该义务以其特征 token 被文档内其他条款或测试引用。

## Discriminator
改前已可见两类耦合事实：(1) 对义务 token 的 grep 已显示其出现在跨文档多处规范性行（规则正文 + governance 交叉引用条款，如 record_use 在 ai_rules.md 与 card-lifecycle.md 共 13 处命中）；(2) 仓库存在以"文档同步"命名的测试（tests/unit/test_ai_rules_sync.py）——此类测试按精确短语断言文档措辞，被断言短语是承重结构。任一事实出现即证明编辑面大于被引用的那一段。

## Short path
- git status 确认工作区基线（上一轮改动确已保存）。
- 直接对权威 SoT 路径 grep 规则 ID 定位条款行号并读取正文；已知权威路径时跳过全库文件名枚举（.releases/ 不可变快照是噪音）。
- 改前耦合面枚举：对义务 token 同时 grep docs/ 与 tests/，并读同步测试的断言清单，产出"必须保留或必须同批修改"的短语与站点列表。
- 尽早触发异步副作用（重启），让两阶段等待与文档编辑工作重叠。
- 单次编辑通过更新全部枚举站点：被测试断言的短语要么保留、要么与测试同批修改；交叉引用条款同步改写，避免留矛盾条款。
- 跑文档同步测试+定向单测；对工作树（排除 .releases 快照）grep 旧强制措辞确认无残留；按回执如实报告异步重启终态（受理≠生效）。

## Stop conditions
- 枚举出的全部耦合站点已一致更新，文档内无相互矛盾的条款表述。
- 文档同步测试与定向单测通过，无因措辞丢失导致的断言失败。
- 工作树（排除不可变发布快照）中旧强制义务措辞仅剩有意保留的历史说明。

## Verification
- 重跑文档同步测试（如 test_ai_rules_sync.py）确认全绿。
- grep 义务 token 与旧强制短语于 docs/ 与 src/，逐条确认其语义角色（定义/交叉引用/测试断言/无关工具文档）均已处置。
- 异步动作以 status 查询终态，不得以"已受理"冒充"已生效"。

## Counterexamples
- 无交叉引用、无文档同步测试的一次性散文文档：直接编辑即可，枚举耦合面是纯开销。
- 义务 token 同时是通用工具名：grep 命中会包含无关能力文档，须语义过滤，并非每处命中都是义务站点。
- 新增/加强规则而非削弱旧义务：不存在需要调和的旧措辞站点（仍需补交叉引用，但失败模式不同）。
- .releases/ 等不可变历史快照中的旧措辞不应也无法修改，须从编辑集中显式排除。
