---
method_id: exact-identifier-first-search-with-subsystem-split-b2d923262868
name: exact-identifier-first-search-with-subsystem-split
description: 需求文本已逐字给出目标标识符（如 stable_prefix_sha256）时，先用该精确串做工作区内容搜索，再按命中分布分流：src/运行路径命中=producer 线索，直读实现；命中集中在 tools/analytics 目录且字段名是变体（fp/tokens vs sha256）=离线分析子系统，不沿走；零命中=全新代码，转找最近似 sibling。避免先用宽子串搜索引入无关子系统噪声，再连环猜名重搜。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:986:2ed4016db54807ddfe61
evidence_refs: learning:learn:2630b9e180a9
created_at: 2026-10-11T14:55:49.373742+08:00
updated_at: 2026-10-11T14:55:49.373742+08:00
---
## Trigger
实现/修改一个需求声明中逐字给出确切标识符（字段名、符号、常量、key）的代码任务，需要定位该标识符的生产/定义处或确定挂载点，且首读主文件中未直接命中该串。

## Discriminator
knowledge-at-time：任务声明自带的精确字面量 stable_prefix_sha256 本身就是最强判别器；本例中宽搜 `stable_prefix` 得 30 条，几乎全是 tools/cache_attribution/ 的 `stable_prefix_fp` 离线分析字段（后缀变体+分析目录双信号），而 exact 串搜索仅 5 条、精确落在 chatgpt_transport.py 与 deepseek_transport.py 的 sha256 计算处——命中分布（目录前缀+字段名是否逐字一致）当时即可区分 producer 与不同子系统。

## Short path
- 从任务声明提取精确标识符，第一步就做 exact 内容搜索（未知量：producer 在哪）
- 按命中分布分流：src/transport 层逐字命中→直接读其实现（_prefix_diagnostics 与 sha 计算处）
- 结合首读已得的主文件类结构（_SurfaceOwnedTransport 生命周期/rollover）确定挂载层（未知量：跨轮基线挂在哪层）
- 读 sibling transport（deepseek 同名诊断）对应段，保证语义与实现模式一致
- 实现+定向测试（tests -k <target>）通过即停

## Stop conditions
- 已读到标识符的计算/赋值处（producer）并能确定挂载层，进入实现
- exact 搜索零命中且已排除改名/别名，转为 sibling 模式定位

## Verification
- 定位到的文件必须包含标识符的计算/赋值处，而非仅消费或离线分析读取
- 该文件位于目标功能的运行路径（如传输层），不属于离线 analytics 工具目录
- 定向测试通过，且提交文件集合与声明的改动范围一致

## Counterexamples
- 需求只描述行为目标、无任何字面标识符（如'让前缀缓存更稳'）→ 必须语义宽搜，本方法不适用
- 标识符可能跨版本改名或有别名 → exact 零命中不代表不存在，需补别名/旧名搜索
- exact 串唯一命中就在 tools/ 且目标本身就是改该分析工具 → 此时该命中即目标，不存在子系统分流
