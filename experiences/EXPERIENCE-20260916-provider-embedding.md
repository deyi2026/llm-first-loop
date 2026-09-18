---
title: 多 provider 共享单 embedding 缓存文件会被后写者整文件覆盖——缓存身份必须在文件名层面隔离
scenario: SemanticRetriever 的 embedding 缓存（embeddings.json）在多个 provider 间共享同一文件路径：一个进程用 bge（APIEmbedder）预热 1487 条向量后，另一进程（web/feishu 服务重启后按 .env 以 HashEmbedder 运行）重新计算并整文件持久化，bge 缓存被清空覆盖（实测从 1487 条变 70 条，版本键为空串）
root_cause: ""
solution: 缓存文件身份与 vector_version 绑定（文件名内嵌版本 tag，如 embeddings-api-v1_<endpoint>_bge.json），不同算法版本天然写不同文件；embedder 侧补齐 APIEmbedder.vector_version（含端点+模型，确保算法或模型变更自动换文件）；旧无 tag 文件保留为只读回退。验证：重启后生产装配核实新 tag 文件预热 1490 条、旧文件不再被写、A/B 金标查询 4/6 hit mode=semantic。
evidence: "commit 55e53458（embedder vector_version + retriever tag 缓存文件）；commit eb525fef（resolver 治理+预热）；2026-09-16 会话实测：重启后 data/memory/embeddings.json 从 1487 条 bge (v=api-v1:...) 变为 70 条 (v='')；pytest 全绿 + 生产装配核实（load_env_file→load_settings→factory 同款路径）"
tags: [embedding, cache, vector_version, retriever, file-isolation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T15:06:08.824472+08:00"
updated_at: "2026-09-16T15:06:08.824472+08:00"
---

同一 embeddings.json 缓存文件被不同 provider 的 retriever 先后持久化时，后写者整文件覆盖（_persist_emb_cache 全量写），且旧 APIEmbedder 无 vector_version 属性导致版本键为空串，_load_emb_cache 的版本校验完全失效。生产影响：1487 条 bge 向量缓存被重启的 hash 服务清成 70 条。修复：embedder.py 为 APIEmbedder 增加 vector_version（含端点+模型 tag）；retriever.py 缓存文件名内嵌 vector_version（per-version tag 文件），旧文件降级为只读回退。教训：多算法/多来源共享单文件缓存，必须在文件身份（文件名）层面隔离版本，不能只靠文件内版本键校验（后写覆盖会先摧毁校验依据）。