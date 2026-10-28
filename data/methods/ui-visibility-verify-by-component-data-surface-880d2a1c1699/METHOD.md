---
method_id: ui-visibility-verify-by-component-data-surface-880d2a1c1699
name: ui-visibility-verify-by-component-data-surface
description: 回答『页面/面板 X 是否展示数据 Y』类可见性问题时，先读组件文件头部（imports/类型/state/页签定义）枚举该页面的数据面，再用一次限定范围（组件或该 UI 源码树）的标识符内容检索的零命中来证明『不展示』；scope 已收窄后不要再做全库相似指标字符串搜索或读无关组件。本集在 KnowledgePanel 数据面已枚举（仅经验/方法两类 API）且 webui 内 self_eval 零命中之后，仍全库搜索相似指标字符串、命中无关会话面板，属多余扩散。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:546:69b7d6cc49c6efd9c340
evidence_refs: learning:learn:506f024bf9b2
created_at: 2026-10-16T22:06:41.348392+08:00
updated_at: 2026-10-16T22:06:41.348392+08:00
---
## Trigger
用户询问某个具体页面/面板是否展示某类数据或指标（如『打分在知识管理页面看得到吗』），且该页面组件可通过页面名/组件名在代码中定位。

## Discriminator
组件文件头部的 import 列表、类型与 state 定义已枚举该页面全部数据源（本集为 fetchExperienceCatalog/fetchMethodInventory，页签仅 experiences|methods）；同时限定范围检索目标数据标识符（self_eval 于 *.tsx）返回零命中——两条当时已知事实合并即可确定性回答『该页面不展示此数据』，无需扩大搜索。

## Short path
- search_records(kind=数据类别) 取得既有打分与趋势；如需最新值现跑一次评估（未知量：现在有哪些分）
- search_files(页面名/组件名) 定位渲染该页面的组件（未知量：页面由谁渲染）
- read_file 组件头部 imports/types/state/页签定义，枚举其数据面=它能展示什么（未知量：页面可展示的数据类别集合）
- 对目标数据标识符做一次限定范围内容检索（组件或 webui 树）；零命中即在范围内证明不展示
- 汇总数值+可见性结论即停止；不向全库相似指标字符串或其他无关组件扩展

## Stop conditions
- 组件数据面已枚举且目标标识符在限定范围内零命中——可见性结论已定
- 用户所需数值已由权威记录或现跑评估给出

## Verification
- 用页面名出现在测试/路由/注释中的引用确认所读组件确为用户所指页面
- 确认用户口语词（『打分』）与代码规范标识（self_eval）的映射，避免查错标识符造成假阴性

## Counterexamples
- 组件通过通用 key-loop 渲染 API 返回的任意指标（标识符不字面出现在代码中）：枚举 imports+字面 grep 会误判『不展示』，应改查该 API 的 payload schema
- 用户问『产品任何地方是否可见』：全库搜索本身就是正确 scope，不应收窄到单组件
- 页面由多个懒加载子组件拼装，父组件头部 imports 不代表全部数据面，需沿子组件引用继续枚举后才可下结论
