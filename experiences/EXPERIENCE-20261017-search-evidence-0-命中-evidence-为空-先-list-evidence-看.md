---
title: search_evidence 0 命中 ≠ evidence 为空：先 list_evidence 看清单，查询词必须用 evidence 里的字面
scenario: "我在 2026-10-17 07:51 用 search_evidence 查\"cordis.patch.yml dump-config preset 合成 90 bots\"这类自己概括出来的描述词，0 命中，于是对用户宣称\"当前会话 evidence 是空的\"。实际 list_evidence 显示同一会话有 29 条 evidence（07:35:12–07:49:22），包含五线扫描原始输出。"
root_cause: "两个独立原因叠加：(1) evidence 存储的是工具原始回显（命令 echo + grep 标题如 \"=== 'hidden instruction' 唯一命中上下文 ===\"），与我自造的概括描述词无词面/语义重叠，语义检索必然 0 命中；(2) 我把\"检索未命中\"这一未证实信号直接升级为\"存储为空\"的事实断言，未做清单级核验。"
solution: "规则一：断言\"某类数据不存在/为空\"之前，必须先用 list_evidence（枚举型工具）或等价清单接口确认，而不是靠一次检索的负结果。检索失败只证明\"我的查询没命中\"，不证明\"数据不存在\"。规则二：写 search_evidence 的 query 时，词必须来自 evidence 里实际存在的字面（命令回显里的路径、echo 标题、grep 模式名），不要用我自己对内容的概括。规则三：区分 prompt 侧上下文与 evidence 存储——run.prefix_stability=prefix_broken / context_usage.breakdown.history 骤降只说明塞进 prompt 的对话历史被压缩，不代表 evidence 被清；判断\"重启有没有影响\"要看 process_versions 的 pid/started_at 与 session_id 是否变化，不能凭体感。"
evidence: "list_evidence 回执\"最近 20/29 条\"（acquired_at 2026-10-17T07:35:12–07:49:22）；read_evidence evidence://v1/fc737a91093e2be5876a000a1508a7c853495870f99ceacdff5350c8bb9063d6 正文为\"=== 'hidden instruction' 唯一命中上下文 ===\"即五线扫描输出；event_stream 07:51:24 run.prefix_stability prefix_broken final_lcp=1/3 cached_chars=1117；architecture_status process_versions web pid=78743 started_at=2026-10-17T07:07:51 会话 881d9c3f 全程未变。"
tags: [evidence, search_evidence, verification-discipline, honesty, context-compression]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T07:54:50.320051+08:00"
updated_at: "2026-10-17T07:54:50.320051+08:00"
---