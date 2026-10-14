---
method_id: truncated-receipt-switch-to-underlying-source-record-7ebe34ada3ff
name: truncated-receipt-switch-to-underlying-source-record
description: 大体积结构化工具回执被截断时，不要在 Evidence 库换措辞反复检索同一截断投影，也不要用微小 range 分页读同一 blob；截断片段通常已暴露其投影的底层权威记录（per-entity manifest 文件名、git_head/pid/started_at 等字段）。对源记录做一次窄读即可取得干净字段并求出 delta。本集一次 manifest 读取替代多次 hydration/检索，再单次 restart 即达成更新+重启。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e729d08f-6ec8-459b-b3be-a3eb65be8025:1707:7287fee960feb6c78db3
evidence_refs: learning:learn:633046052bb1
created_at: 2026-10-13T22:52:11.659352+08:00
updated_at: 2026-10-13T22:52:11.659352+08:00
---
## Trigger
结构化工具回执（status/snapshot/dump 类）因体积被截断，且片段中可见其数据的底层权威记录线索（manifest/record 文件名、provenance 标签、per-entity 键），同时工具 schema 已说明动作语义（如按 desired-state 精确生效）

## Discriminator
对截断 blob 的 evidence 分页读返回 range 元数据（count≈40、complete:false、next_start 很小），证明 Evidence 副本就是同一整块 blob——继续检索或分页只能得到碎片，不可能得到干净区段；而片段中 manifest_present/git_head/pid_alive 等字段直接指明权威源记录可独立一次读取

## Short path
- 读工具 schema 与首个截断回执，确认动作语义（restart 按 desired-state 精确 code_root 生效，期望代可缺省），把问题缩为唯一未知量：目标进程当前代 vs desired 代
- 检查工具是否有过滤参数（target/action_id）可缩小回执；有则先做过滤查询
- 无过滤或仍截断时，从片段暴露的源记录（per-target runtime manifest 文件等）做一次窄读，取得干净字段求出 delta；不要对同一 blob 做变体关键词检索或逐段 hydration
- 执行单一动作（restart/update）；受理≠完成，等待后查终态 status 至 succeeded/failed
- 以 verify 回执加独立进程/源记录复核新状态，停止

## Stop conditions
- 源记录一次读取已给出干净的目标字段（当前 head 与 desired head 的差异已确定）
- 动作终态 succeeded/failed 已核验，且与源记录/进程证据双源一致

## Verification
- 确认所读源记录与工具回执投影口径一致（同一 generation/git_head 字段族）
- 终态以工具 status 的 verify_evidence 加独立进程/manifest 复核，双源一致才宣布完成

## Counterexamples
- 底层源记录不可直接访问（纯远端工具、无本地镜像）→ 对原回执做 range 分页读才是正路，不适用本方法
- 所需事实只存在于工具实时视图（lease/屏障/内存态），磁盘记录可能滞后 → 必须重查工具而非读文件
- 工具本身提供 target/id 过滤参数且过滤后回执完整 → 直接用过滤查询，不必绕到文件
- 片段未暴露任何源记录线索且无过滤参数 → 对 Evidence 库的关键词检索属合理手段，本方法不适用
