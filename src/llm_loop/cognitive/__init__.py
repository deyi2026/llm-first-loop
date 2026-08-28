"""认知运行时（Cognitive Runtime）v1 子包.

内嵌组件（非独立服务进程），不改动上下游既有契约，只新增
「读 Goal/Evidence/EventLog + 产出决策包与状态」的局部数据流（design 2.1.1）。

模块:
- state: 语义任务状态领域对象 + YAML(JSON) 原子持久化 + 受控重置
- compiler: HOT/WARM/COLD 确定性分级 + 决策包融合
- benchmark: 语义重置 A/B 基准（离线/影子模式）
"""