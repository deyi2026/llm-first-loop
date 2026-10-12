---
method_id: on-identifier-lookup-miss-search-first-hand-tokens-not-volatile-tokens-0a314b891d5d
name: on-identifier-lookup-miss-search-first-hand-tokens-not-volatile-tokens
description: 复合标识符（名称+日期+主题，如 'DESIGN-20260909 插件生态'）精确查找 miss 时，先把标识符拆成 token 并按 provenance 分级：本任务内第一手核验过的语义 token（标题短语、章节号、独特内容词）vs 第二手听来的易变 token（日期、版本号、序数）。对易变 token 做文件名枚举会把搜索面放大到大量同前缀文件且仍不含目标；对第一手语义 token 做一次定向内容/文件名搜索通常直接命中。核心纪律：用你知道为真的部分去搜，不要用你只是听说过的部分去枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8edca76a-022e-442c-9819-960bcdff7f8a:1:cd17056ec8c254287cb4
evidence_refs: learning:learn:0d904cc0c66b
created_at: 2026-10-10T06:58:24.072720+08:00
updated_at: 2026-10-10T06:58:24.072720+08:00
---
## Trigger
按复合标识符精确查找 artifact 首次 miss，且该标识符中至少一个 token 是第二手来源（用户转述、记忆）从未在库内核验过，同时手里已持有至少一个第一手核验过的语义 token（上一轮亲自读到的标题短语/章节结构/独特措辞）。

## Discriminator
token 来源分级 + 低判别力回执：本集中 '20260909' 仅来自用户转述，此前从未与库内任何文件对上；而 '插件生态' 标题与 §11 七阶段/§12 验收矩阵结构来自上一轮一手阅读、确定存在于目标文档中。首次按日期 glob 即命中 14 条、复查 61 条且全部不含 DESIGN 文档——这条回执本身就是'该日期 token 判别力≈0'的机械证据，应在第二次枚举前切换 token。

## Short path
- 首查 miss 后立即拆 token 标注来源：哪些是本任务第一手核验过的（标题短语/章节号），哪些只是听说的（日期/版本/序数）。
- 选判别力最高的第一手语义 token 做一次定向搜索（grep -rl '<独特短语>' 目标目录/ 或文件名子串），不按易变 token 做全树 glob 枚举。
- 命中后用第一手事实交叉验证：确认文件包含已知结构（如 §11 分期表、§12 验收矩阵）再读取，防同名误中。
- 目标章节读毕、未知量（本集为 P2-A 验收口径与既有 extensions/ 代码契约）解决后立即停止发现，进入实施。

## Stop conditions
- 目标 artifact 已定位且其内容与第一手已知事实互相印证——停止发现。
- 若没有任何第一手语义 token 可用：只允许一次受控枚举（限定目录或单个 glob），不得对同一 token 换花样重复枚举。
- 同一 token 类（日期/版本）连续两次 miss：该 token 判定为不可靠，禁止再以它发起第三次查找。

## Verification
- 机械检查：miss 后的第一个查找动作所用 token 的搜索确实命中目标文件（本集应为 grep 标题短语直接命中 DESIGN-20261009-plugin-ecosystem-integration.md）。
- 定位到的文件包含先前记住的一手事实（章节号/独特短语），证明不是同名误中。
- 发现阶段成本上界：初始 miss + ≤1 次定向搜索 + ≤1 次交叉验证读；出现第二次全量文件名枚举即违规。

## Counterexamples
- 日期/版本本身是第一手核验过的（上一轮刚亲眼读过确切文件名）：精确名直查就是最短路径，拆 token 反而绕路。
- 对目标内容毫无一手信息、只有文件名：目录枚举是唯一手段，本方法不适用。
- 任务目标本身就是枚举（如'审计所有 2026-09-09 的文件'）：枚举即交付物，不是摩擦。
- 标识符是无可拆语义的不透明 token（完整 commit hash、随机 ID）：直接查权威索引，勿套用本方法。
