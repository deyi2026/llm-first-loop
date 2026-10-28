---
method_id: positioning-by-explicitly-excluded-scope-820e9acfd7f4
name: positioning-by-explicitly-excluded-scope
description: 对标外部大系统时，先读它"明确声明不包含/不负责"的边界——那通常正是本地差异化位置；再按规模差把可迁移项分成"方法"与"机制"两档
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:4:b732016ee4384ffcad2d
evidence_refs: evidence://v1/4a2153e757396f9bafa859c9ac951a023488ef2a824c8a6d06642987dbd9a695,evidence://v1/db0a36442959e34e220d3201fbfd3a5d6acad774c77b717c37d28b90db45fd6d
created_at: 2026-10-21T23:11:34.427597+08:00
updated_at: 2026-10-21T23:11:34.427597+08:00
---
来源：2026-10-21 DeepInfer × research 对照任务（已产出可核文档 analysis/DEEPINFER_X_RESEARCH_COMPARISON_2026-10-21.md）。

## 触发
需要回答"外部某开源/闭源系统对我们的研究有什么启发、借鉴、结合"。

## 判别事实（discriminator）
外部系统**自己声明的边界**：README 的 "not included in this release" / "out of scope" / "required for a complete service" 段落。DeepInfer 明确列出三项不包含：KV cache 系统、VE/Prefill/Decode 分离服务层、DP 副本负载均衡——这三项恰好是本地 StateBraid + cognitive-cache 的主战场。

## 短路径
1) clone 仓库并读 README + FAQ/部署文档（**不要**只读二手报道）；
2) 摘出它的"明确排除清单"与"硬件/规模前提"；
3) 盘点本地资产，把每一项映射到"它有 / 它没有 / 双方都有但我方更强"；
4) 按规模差把外部机制分成：**方法可迁移**（如批不变/确定性作为契约、SWA 两级命中判据、moe_lb 可测标量、cost 模型反解）与**机制不可迁移**（3FS/100PiB、EP64 超节点、NVLink symm_mem、GDR/400G）；
5) 产出显式"不借鉴清单"并写明理由，避免把"看起来能用"的东西误当借鉴；
6) 外部二手报道的数字单独列"未核实"表，逐条标出仓库内是否可证。

## 分支
- 外部系统的边界文档缺失 → 先找 FAQ/部署文档/issue，再退到源码与默认配置；
- 外部只给二手报道 → 报道数字一律进"未核实"表，不进结论。

## 反例
- 外部系统没有明确边界声明（如无 README/无 FAQ）→ 本方法失效，退回按功能逐项对照；
- 目标不是定位而是复现（要跑起来）→ 应直接走部署路径，本方法只回答"做什么/不做什么"。

## 压缩卡
```yaml
name: positioning-by-explicitly-excluded-scope
status: candidate
trigger: 评估外部系统对本地研究的启发/借鉴/结合
discriminator: 外部系统是否有明确的"不包含/不负责"边界声明
short_path: 读一手仓库 → 摘排除清单与规模前提 → 本地资产逐项映射 → 方法/机制分档 → 显式不借鉴清单 → 二手数字单列未核实表
branch_on_evidence:
  - observation: 有明确排除清单
    next: 直接把排除项当差异化候选，逐条验证是否对应本地资产
  - observation: 无排除清单
    next: 退回按功能逐项对照
stop_conditions: 已产出可执行的分档清单 + 不借鉴清单 + 未核实表
verification: 结论中的每条外部事实都能指到仓库文件/行
anti_patterns: 只读二手报道就下结论；把规模机制当方法借鉴
counterexamples: 目标是复现而非定位；外部无边界文档
programizable: 抄取 README 中 not-included/required 段落作为固定第一步
model_owned: 判断本地资产与外部排除项的对应关系是否成立
why_shorter: 用一手边界声明把"功能大全对照"缩成"排除项 × 本地资产"两个小矩阵。
```
