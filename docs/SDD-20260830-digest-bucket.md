# SDD-20260830：桶结构+档案尾部槽——需求与实现设计规划

> 依据：DESIGN-20260830-digest-bucket-architecture.md / EVO-20260829-06c96021
> 方法：Spec-Driven Development——需求 spec 先行，实现按 spec 验收，测试即契约

## Part A：需求 Spec（验收即测试）

### FR-1 档案槽增量注入（P1）
- FR-1.1 每次工具 SUCCESS 后，档案槽尾部追加该调用的 L1 摘要块（≤600c：工具名+参数关键项+extract_key_info 要点+结论行）
- FR-1.2 档案块 append-only：已注入块的字节在后续轮次 payload 中零改动
- FR-1.3 档案槽位于 payload 尾部区（工具摘要历史之后、当前注入之前）
- FR-1.4 **验收测试**：构造 3 轮工具调用序列，断言轮 N 的 payload 中轮 N-1 档案块字节完全一致（前缀不变式）；断言档案块位置恒定
- FR-1.5 工具 FAILURE/BLOCKED 不产生档案块（终局推理不需要失败回执细节，历史层已有）

### FR-2 终局全量在场（P1）
- FR-2.1 终局轮（loop→final answer）payload 含全部档案块（不截断，除非触顶策略 2.6 触发）
- FR-2.2 终局轮前缀与上一工具轮的公共前缀 = 除终局指令外的全部内容
- FR-2.3 **验收测试**：模拟 5 轮工具+终局，断言终局轮理论前缀命中 ≥ 上一轮 payload 长度 - 终局指令长度

### FR-3 指标埋点（P1）
- FR-3.1 每轮计算：理论前缀命中字节（与上轮 payload 公共前缀长度，字节级）+ 实测 cached_tokens（从 usage）→ cognitive_telemetry
- FR-3.2 偏离告警：|理论-实测×tokens系数| / 理论 > 15% 时记录 prefix_anomaly 事件
- FR-3.3 **验收测试**：离线双 payload 计算公共前缀，与埋点值一致；构造中段插入场景断言告警触发

### FR-4 弹性预算（P2）
- FR-4.1 预算 = max(基础, 活跃档案需求+历史最小集)，上限窗口×0.7
- FR-4.2 扩容只作用于尾部槽（回执/注入），不动历史字节
- FR-4.3 **验收测试**：档案需求 40k 时预算自动 40k+；断言历史区字节不变

### FR-5 桶结构与切换（P2）
- FR-5.1 桶边界：新用户真实指令链/create_goal→新桶；AI 可经消息 metadata 显式声明切桶
- FR-5.2 切回旧桶：桶历史原样回归（与离开时字节一致）→ 理论前缀全命中
- FR-5.3 桶目录：尾部追加，含非活跃桶锚点（标题+终局结论+档案指针）
- FR-5.4 **验收测试**：桶 A→B→A 序列，断言第二次进 A 的 payload 前缀与离开 A 时一致（字节级）

### FR-6 并发与留存（P2）
- FR-6.1 档案文件 O_APPEND 原子追加+fcntl 文件锁；子代理回传同管道
- FR-6.2 档案留存与 archives 同生命周期
- FR-6.3 **验收测试**：并发 8 线程追加 100 块，断言无丢失无交错损坏

### NFR
- NFR-1 档案构建零 LLM 成本（纯规则：extract_key_info 复用）
- NFR-2 埋点开销 <1ms/轮（前缀计算是 O(payload) 字节比较，可增量缓存上轮 payload 指针）
- NFR-3 全部开关可关（DIGEST_ENABLED=0 回落现状，零回归）

## Part B：实现设计

### B.1 模块拆分（新增 2 + 修改 4）
```
新  src/llm_loop/core/session_digest.py     # 档案构建器：block_for(tool_result)→L1块
新  src/llm_loop/core/bucket_registry.py    # 桶注册表：桶生命周期/边界检测/目录视图（P2）
改  src/llm_loop/core/history.py            # 组装层挂档案槽（复用尾部槽机制）
改  src/llm_loop/core/loop/build.py         # 工具 SUCCESS 回调→digest.append；弹性预算计算
改  src/llm_loop/config.py                  # DIGEST_ENABLED/DIGEST_BLOCK_MAX/DIGEST_BUDGET_BASE/ELASTIC_CAP_RATIO
改  src/llm_loop/core/run_context.py 或 telemetry # 前缀命中埋点
```

### B.2 关键接口
```python
class SessionDigest:
    def append(self, call: ToolCall, result: ToolResult) -> DigestBlock | None
        # 规则摘要：name + 关键参数(≤80c) + extract_key_info 要点(≤400c) + 结论行(≤120c)
        # 返回 None 表示不产生块（失败回执/空结果/重复调用同一 tool_call_id）
    def render(self) -> str            # 档案槽全量视图（append 序）
    def bytes_of(self, block_id) -> int  # 供指标计算

def compute_prefix_hit(prev_payload: bytes, cur_payload: bytes) -> int
    # 字节级公共前缀长度（增量缓存优化见 NFR-2）
```

### B.3 数据流
```
工具 SUCCESS → build.py on_tool_success → digest.append() → 块落 data/digests/<sid>.jsonl（持久）
组装轮 → history.py → [历史折叠] + [档案槽= digest.render()] + [注入] （尾部槽注入）
终局轮 → 同组装（档案已在场，无特殊分支）→ L3 升级钩子（P2：预算允许→追加原文块）
每轮 → 前缀埋点 → cognitive_telemetry（prev/cur payload 哈希+公共前缀字节+usage.cached_tokens）
```

### B.4 测试计划（与 FR 对齐）
| 测试文件 | 覆盖 | 类型 |
|---|---|---|
| tests/unit/test_session_digest.py | FR-1.1/1.5 摘要块生成/失败不生成 | 单元 |
| tests/unit/test_digest_prefix_invariance.py | FR-1.2/2.2/2.3 前缀不变式（3轮+终局序列） | 单元（核心） |
| tests/unit/test_prefix_hit_metric.py | FR-3 埋点正确性+偏离告警 | 单元 |
| tests/unit/test_elastic_budget.py | FR-4 弹性预算 | 单元 |
| tests/unit/test_bucket_registry.py | FR-5 桶切换字节一致 | 单元 |
| tests/integration/test_digest_e2e.py | 全链路：真实工具序列→payload 断言 | 集成 |
| tests/unit/test_digest_off.py | NFR-3 关闭回落 | 回归 |

### B.5 实施顺序（TDD：每步红→绿→重构）
1. config 开关 + SessionDigest.append/render（FR-1.1，纯新代码）
2. history.py 尾部槽挂接（FR-1.3）+ 前缀不变式测试（FR-1.4——此测试是整个架构的契约核心，先写红）
3. 终局轮断言（FR-2.3）
4. 前缀埋点+告警（FR-3）
5. P2：弹性预算→桶注册表→并发→L3 升级
6. 镜像行为实测（本地模型真实任务跑通+指标①②对比）→ diff 提审 → 主区应用

### B.6 风险与回退
- 风险1：档案块内容质量差（extract_key_info 对技术文档弱）→ 终局质量不升反降 → 缓解：P1 试点先看指标⑧⑨；L2/L3 兜底
- 风险2：桶边界误判（闲聊被当新桶/任务被合并）→ 缓解：MVP 手动声明优先，自动检测 P3 再说
- 风险3：与压缩引擎交互（档案槽在预算内被折叠）→ 缓解：槽豁免压缩硬规则+测试锁定（FR-1.2 隐含）
- 回退：DIGEST_ENABLED=0 一键回落现状
