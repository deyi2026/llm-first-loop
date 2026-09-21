---
method_id: config-mismatch-resolution-chain-before-repo-search-e57b1fdeb8f9
name: config-mismatch-resolution-chain-before-repo-search
description: 诊断"生效配置值与文档推荐不一致（是否没设置好）"类问题时，先查运行时配置 dump：若偏差已在 dump 中可见（本例全局 reasoning_effort=high，文档推荐 max），剩余未知量只剩"有无模型级覆盖与解析优先级"，应沿 命名配置文件→唯一 live 模型注册表→解析代码优先级段 这条解析链闭合结论；不要拿配置键做全仓库内容搜索——那只会命中 evals/结果目录里的几十条过期副本。本 episode 15 次调用中，workspace 路径猜测（1 次失败）与两次全仓库宽搜索（约 60 条噪声命中）均属可省摩擦。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:0:ab52eb568e7b2f9f7308
evidence_refs: learning:learn:e54b84646acc
created_at: 2026-09-20T14:04:41.006875+00:00
updated_at: 2026-09-20T14:04:41.006875+00:00
---
## Trigger
用户报告某模型/组件的实际行为参数与官方文档推荐不一致（如"没打开 max，是否没设置好"），且环境中存在可查询的运行时配置 dump 或命名的配置文件（runtime.toml/.env/模型注册表）

## Discriminator
第 4 步的运行时配置 dump 已直接显示全局 reasoning_effort="high"（与 llm_model、base_url 同列），与第 1 步文档推荐 max 的偏差点此时已定位；且第 3 步模型目录输出已表明存在按 provider/model 键控的注册表。这两个当时已知事实把问题从"系统哪里没设好"缩为"模型级覆盖是否存在+优先级顺序"，可由命名文件（runtime.toml/.env、data/providers.json、client.py 解析段）直接验证；全仓库关键词搜索只会命中 evals/**/results/ 下的过期 providers.json 副本。

## Short path
- 抓取用户引用的官方文档，确定推荐值（reasoning_effort: max、thinking 仅 enabled）——未知量：应然值是什么
- 查询运行时配置 dump 或直读 runtime.toml/.env，确认全局生效 effort=high——偏差已在全局层定位，未知量收窄为"有无模型级覆盖"
- 经项目根目录列举或定向 find 定位唯一 live 注册表 data/providers.json，检查目标模型是否配置 reasoning_default_effort/reasoning_efforts（本例：无）
- 只读 client.py 中 effort 解析优先级段（请求级→模型默认→legacy），闭合"为什么发的是 high"的证据链
- 与文档及代码注释（provider 默认 max）交叉验证后停止，给出修复选项并向用户确认影响范围

## Stop conditions
- 全局值、模型级覆盖有无、解析优先级三者证据齐备，能完整解释生效值来源
- 所有结论均来自 live 配置文件与解析代码，未依赖 eval/结果目录中的历史副本
- 已给出可执行修复选项（全局改档 vs 仅给目标模型钉档）并说明代价

## Verification
- 确认所读注册表位于 live 数据目录（data/providers.json），而非 evals/**/results/** 拷贝
- 对照解析代码行号复述优先级链，确认全局 high 确实压过 provider 默认 max
- 结论同时覆盖当前会话模型与 fallback 链上的目标模型两条生效路径

## Counterexamples
- 相关键在全局配置中缺省（未设置/null）→ 生效值来自 provider 默认或模型注册表，应先查注册表与解析代码，从全局文件入手读不出答案
- 存在更高优先级的会话/请求级覆盖层（如本例会话覆盖 llm_model）→ 静态文件值不代表实际生效值，需查运行时请求 payload 或日志
- 仓库不含生成物/历史副本时，关键词搜索不会命中过期配置 → "避开宽搜索"的收益消失，定向路径与宽搜成本相当
