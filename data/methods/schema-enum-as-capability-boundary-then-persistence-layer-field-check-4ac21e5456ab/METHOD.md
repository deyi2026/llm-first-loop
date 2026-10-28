---
method_id: schema-enum-as-capability-boundary-then-persistence-layer-field-check-4ac21e5456ab
name: schema-enum-as-capability-boundary-then-persistence-layer-field-check
description: 判断「是否存在对存量记录某字段的受控改写通道」时，已取得的全量工具 schema（action/enum 穷尽）本身就是工具层能力边界：如 refine_experience 明示「不修改原卡」且 action 枚举无该字段操作、save_experience 为新建语义（冲突即 FileExistsError），则工具层结论已定，不要再跨 tools/、handlers、builtin/ 反复 hunt handler 实现位置；剩余唯一未知量收敛为「持久层是否暴露该字段 setter」，用字段名定向 grep + 读 mutation 方法体一次确认。确无通道后直改时复用 store 完整性原语（flock+原子替换+fsync），而非通用 edit_file 旁路。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:973:266025b2e89bcb30a4ca
evidence_refs: learning:learn:d61d723ddafa
created_at: 2026-10-15T06:22:52.769500+08:00
updated_at: 2026-10-15T06:22:52.769500+08:00
---
## Trigger
需要确定是否存在修改已有记录特定字段（如 verification_state）的合法/受控通道，且相关工具的完整 schema 已在本会话取得

## Discriminator
schema 的 action/enum 是否穷尽动作面且描述明示边界（「不修改原卡」「成功返回新 experience:<id>」）——枚举穷尽即工具层结论，不再需要定位 handler 实现来重复验证工具层；未知量只剩持久层是否有 setter

## Short path
- 从已取得 schema 判定：action 枚举无该字段操作、描述明示不修改原卡 ⇒ 工具层无改写通道
- 对持久层做字段名定向检查：grep -n <字段> store.py + 读全部 mutation 方法（save/update_*）体，确认命中行是序列化还是 setter
- 两层均确认无通道 ⇒ 走 store 层直改，复用与 update_status 相同的完整性原语（flock+原子替换+fsync），不用通用编辑旁路
- 直改前读治理文档确定证据标准（本集：老格式卡无核验点段，改用事实轴机械复核）
- readback + front-matter diff 验证后停止

## Stop conditions
- 工具层（schema 枚举穷尽）与持久层（mutation 方法体已读）均确认该字段无受控写入路径
- 或任一层找到显式通道，即改走该通道并停止通道搜寻

## Verification
- 读 update_status 等方法体确认只写 status 不写目标字段，grep 命中行逐条确认非 setter
- 直改后 readback：front-matter diff 仅目标字段变化，前后计数分布（verified/legacy）与预期一致

## Counterexamples
- schema 非穷尽（描述含「等」、底层为通用文档编辑工具或存在 update_document 类入口）时，枚举不是能力边界，必须定位 handler 实现
- 多写者/多存储区场景（如本集 split-brain 卡所述双区 EvolutionStore）：单一 store 模块无通道不能推出全局无通道，需先枚举全部写者
- 工具层 schema 与运行时代码漂移（registry 缓存旧定义）时，以 live schema 为准并抽验 handler，不能只信已取快照
