---
title: Embedding provider 切换必须走系统路径影子验证（裸模型对比漏掉 2 个真实 bug）
scenario: "验证\"记忆检索缺的是语义不是系统\"判断：切换 embedding provider（hash→api/本地 bge 服务）前的影子测试。裸模型对比显示 bge 6/7 vs hash 1/7，但走真实 SemanticRetriever 系统路径复测后结论被修正且发现 2 个真实 bug。"
root_cause: ""
solution: 影子测试必须走生产代码路径（真实 SemanticRetriever + 生产 timeout/缓存参数 + 真实语料 + 候选预热），不能只跑裸 embedder 对比。裸模型对比会漏掉：①缓存版本键缺失导致的模型混用风险 ②scope 路由 bug ③超时预算校准（1.0s 按 128 维 hash 校准，api 模式冷启动必降级）。配套修复：APIEmbedder.vector_version、_embed_cached 按 cand kind 路由、批量预热脚本（服务端批量 1487 条仅 1.5s）。
evidence: "① scripts/embedding_server.py + embedding_warmup.py 落盘，1487 条预热 1.5s；② pytest tests/unit/test_embedder_retriever.py test_embedder_v2.py test_memory_concurrent_write.py test_memory_extract.py 全过；③ 生产模拟 scope=memory 69ms mode=semantic（evidence://v1/1d9e380d…、evidence://v1/a3d3f8a1… 系列回执）；④ .env 已切 EMBEDDING_PROVIDER=api（备份 .env.bak-20260916-pre-api-embedding）"
tags: [embedding, shadow-test, semantic-retrieval, phase-1, system-path-verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T13:05:38.379484+08:00"
updated_at: "2026-09-16T13:05:38.379484+08:00"
---

## 方法
1. 先裸模型对比（bge-small-zh-v1.5 vs HashEmbedder n-gram）确认语义差距方向
2. 再把两种 embedder 分别注入生产类 SemanticRetriever，语料=真实 MemoryStore（1487 条），测试集=7 条人工同义改写、gold 锚定真实条目 ID
3. 候选向量批量预热进 retriever 缓存（key 格式必须复刻 _candidates() 的 "memory:{id}"）
4. 生产真实探针：生产默认 timeout_s=1.0 + 冷缓存，观察 mode/note 降级路径
5. top-5 相关性人工审计修正指标（命中唯一 gold ID 会低估——同主题多条记忆时邻条目也是正确答案）

## 结果
- hash 系统路径 gold 0/7、top-5 可用结果≈0；bge gold 1/7 但 top-5 主题相关 5/7
- 探针暴露两个裸模型测试完全看不到的系统 bug：
  ① APIEmbedder 无 vector_version → 缓存 "v":""，换模型静默复用旧向量（补 f"api-v1:{base_url}:{model}"）
  ② _embed_cached 按 scope 字符串路由缓存，scope="all"（search 默认值）误走 archive 缓存 → memory 候选逐条重嵌入+缓存文件交叉污染（改为按 cand["kind"] 路由）
- 修复后生产路径（scope="memory"）69ms mode=semantic，预算 20 倍余量

## 教训
裸模型指标对比只验证"语义能力"，看不到超时预算/缓存路由/预热依赖这些接线层问题。切换 embedding provider 类变更，必须走真实系统路径 + 生产超时参数做影子验证。