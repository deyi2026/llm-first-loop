---
method_id: named-producer-fact-fetch-canonical-source-not-generic-search-09db57a70349
name: named-producer-fact-fetch-canonical-source-not-generic-search
description: 当待核实事实（定价/限额/版本/规格）的权威生产者已被点名（文章列出厂商与模型名、任务要求“与官方API比较”）时，直接抓取该生产者的规范文档/定价页（URL 来自先验知识或 docs.<vendor>、<vendor>/pricing 等惯例），而不是对事实关键词做全网搜索。本集证据：6 次 bing 关键词搜索中 4 次返回首页/百科/字典纯噪声（“智谱 GLM-5.3-Flash”被拆词成“智”），而 api-docs.deepseek.com/quick_start/pricing 与 opencode.ai/go 的直接抓取一次成功；最终决定性交叉验证（隐含单次成本 vs 官方牌价，±1%）只依赖这两页，其余搜索是零产出绕路。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:de99d31c-b7ae-424d-a054-8cf1dbce3cd4:0:2b60852eda8cf8841531
evidence_refs: learning:learn:694d5940873b
created_at: 2026-09-29T01:36:05.000607+08:00
updated_at: 2026-09-29T01:36:05.000607+08:00
---
## Trigger
需要核实一批具体事实用于比较/计算，且每条事实的权威生产者在当前上下文中已被点名，生产者拥有可直达（服务端渲染）的官方文档站；或首个通用关键词搜索已回执品牌首页/百科/词典类噪声。

## Discriminator
目标事实有唯一权威生产者且其文档域名/路径已知或可按惯例构造 → 属窄 provenance 情形，直接取规范页；只有生产者未知、多方竞争报价、或规范页证实不可达时才需宽发现。搜索回执若为首页/百科/词典噪声，说明该 query 类与目标文档类型错配，不得换措辞重复同类查询（本集 CJK 模型名+定价词稳定劣化）。

## Short path
- 从当前 artifact 列出待核实事实→被点名生产者的映射（本集：DeepSeek/月之暗面/智谱/阿里 ← 文章额度表）。
- 对每个生产者按先验知识或 docs.<vendor>/pricing 惯例直接抓取规范定价页；路径未知时做站点限定查询，不做多模型名拼接的泛关键词查询。
- 拿到两端数据后立即做可计算交叉验证：月额度÷5h请求数=隐含单次成本，与官方单价代入典型回合（约3.6万token）的估算比对，±~5% 内即确认额度按官方牌价计量并导出回本点（$40÷隐含成本≈1.7万回合）。
- 对抓取失败或抽空的生产者（JS 壳/空表）在答案中标注“未独立核实”，不为其继续泛搜。
- 关键比较数字全部有权威回执后停止发现，转入分析作答。

## Stop conditions
- 决定性交叉验证所需的两端数据（官方单价 + 官方额度表）均已到手且可计算比对。
- 同一生产者规范页两次尝试仍失败（JS 壳/空表/404）→ 标注未验证并停止对其搜索。
- 搜索回执连续为品牌首页/百科/词典噪声 → 停用该 query 类，改为直接抓取或站点限定查询。

## Verification
- 每个引用数字可溯源到被点名生产者自有域名的抓取回执，而非第三方转载或搜索摘要。
- extract 非空且含目标表格/数字（防 JS 壳假成功：本集 open.bigmodel.cn/pricing 返回壳、Moonshot 定价页表格抽取为空，status 仍是 success）。
- 交叉验证计算成立：隐含成本与官方价差在数个百分比内，或差异可被解释并披露。

## Counterexamples
- 比价聚合类任务本身：生产者未知或需发现多方报价，全网搜索才是正确的发现机制，不应先验地直连某一家。
- 目标事实生产者不会官方发布（传闻、区域限制、公平使用条款）→ 必须用独立信源，不能只信生产者自述。
- 规范页已知为纯 JS 渲染且无服务端渲染镜像时，须退回第三方聚合/新闻源，而非反复直连。
- 当前 artifact 已直接含完整目标数据 → 直接分析，零取数动作。
