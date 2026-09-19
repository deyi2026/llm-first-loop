---
method_id: exact-token-nomatch-means-switch-source-class-17cc20f513e8
name: exact_token_nomatch_means_switch_source_class
description: 在语义对象快照/evidence 层寻找 UI 渲染的正文文本时，先用一个由独立权威来源保证必然渲染的精确 token（如控制面返回的 git head 短前缀）做单次探测：若零命中、而 heading/button 等命名对象可命中，则判定为传感器文本覆盖缺口而非关键词不当，立即切换提取机制（直读 DOM innerText/控制台），不再枚举关键词变体，也不再重取全量快照。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1303:e56d388fada6afa139cb
evidence_refs: learning:learn:80eb75a45b5f
created_at: 2026-09-18T19:24:07.652722+00:00
updated_at: 2026-09-18T19:24:07.652722+00:00
---
## Trigger
需要在语义对象快照/evidence 检索层获取页面正文文本（面板卡片内容、段落说明等），且存在另一权威来源（控制面状态、部署清单、源码/构建产物）保证某精确 token 当前正被渲染。

## Discriminator
对保证存在的短精确 token（如已部署 git head 前缀）的一次查询返回零命中，同时面板 heading 等命名对象在同一 evidence 中可命中：这说明该层只索引命名语义对象、不含正文文本节点，继续换关键词不会产生新信息（尽管个别 button name 含长文本，不能据此假定正文可搜）。

## Short path
- 登录/导航后：按可见标签做一次 evidence 检索定位面板入口，取 exact grounding_ref 点击（未知量：入口在哪）。
- 展开面板后，未知量是渲染出的具体值：用独立来源已知的精确 token（git head 前缀）对 evidence 做单次探测查询。
- 命中则留在 evidence 内提取并停止；零命中且 heading 可命中则判定文本覆盖缺口。
- 缺口成立则立即换源类：直读面板区域 DOM innerText，不再枚举关键词变体、不再重取全量快照。
- 将直读值与控制面 evidence 交叉核对一致后停止。

## Stop conditions
- 目标值已由与控制面/权威来源交叉一致的直读文本取得
- 精确 token 在 evidence 中命中，说明该层可检索，留在原层提取即可
- 无独立来源保证 token 正被渲染时不得判定传感器缺口，回到重新观察

## Verification
- 确认直读到的每个字段（desired/live/stable、generation、head）与 service_control/部署 evidence 一致
- 确认零命中 token 确由独立来源保证正在渲染（时间戳/版本对齐），排除'值已变化'解释
- 确认换源后一次提取拿到全部所需字段，无后续重复关键词查询

## Counterexamples
- 无独立来源保证 token 正在渲染：零命中可能表示页面真的显示别的值，应重新观察而非假设传感器缺口
- evidence 层显式索引完整文本节点：零命中指向关键词/范围错误，应精化查询而非换源
- 目标信息本就以命名对象存在（heading/button 名）：按可见标签检索并直接停在该层，不要提前跳去 DOM 抓取
