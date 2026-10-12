---
method_id: classify-dep-missing-errors-by-interpreter-differential-probe-28934bce0162
name: classify-dep-missing-errors-by-interpreter-differential-probe
description: 对『某类错误是否需要另立专项/是否预存』这类升级裁决问题：若错误签名是缺三方依赖（ModuleNotFoundError/ImportError 指名外部包），用两条当时可见事实收窄——①检索首波即命中该错误类的既有分类 memory（如『干净 HEAD 同样失败、根因缺 X、勿重复排查』）；②项目 manifest 已声明这些依赖。两者齐备时唯一未知量是『哪个解释器/环境跑了收集』而非代码缺陷，用一次差分探针（同一 import 检查分别在仓库 .venv 与默认 python 执行）即可裁决，随后回答『不立项、用正确解释器复跑收口』。这是已知签名下的最小分类探针+升级闸，不是完整根因分析（后者由 method-root-cause 覆盖）；探针给出对照表后停止一切变体关键词检索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:de7f7e47-443e-42f9-9513-57ee99c8a21e:3:b29f9710268b8c51f68b
evidence_refs: learning:learn:204c974c8aa5
created_at: 2026-10-13T03:31:22.557475+08:00
updated_at: 2026-10-13T03:31:22.557475+08:00
---
## Trigger
用户询问某类收集/运行错误是否需要另立专项、是否预存/是否本轮引入，且错误签名是缺三方依赖（ModuleNotFoundError/ImportError 指名外部包名）；诉求是升级 go/no-go 裁决而非修代码。

## Discriminator
①检索第一波已返回预存分类 memory：干净 HEAD 同样失败，根因 ModuleNotFoundError 缺 'Crypto'，显式标注『非本轮引入，勿重复排查』；②文件检索命中 pyproject 声明这些依赖（如 reportlab>=4.0、『pyproject 声明依赖，部分环境未装全』注释）及『system Python 意外启动导致收集期缺包』先例。manifest 已声明+已有预存分类 ⇒ 候选空间从『全仓代码缺陷』缩成单一未知量：哪个解释器/环境。

## Short path
- 解析问题：未知量=『该错误类是预存环境问题还是本轮缺陷、值不值得立项』
- search_records 与 search_files 各一次：找该错误类的既有分类记录与 manifest 声明；命中『预存、勿重复排查』memory 与依赖声明即停止检索
- 一次差分探针：同一批 import 检查分别在仓库 .venv 与默认 python3 执行，得到『venv 全 OK / 系统 python 缺』对照表
- 据此裁决：环境绑定、非代码缺陷、两侧同等受影响故不影响 A/B 对比结论 → 不立项，给出『用 .venv 复跑即可收口』的建议

## Stop conditions
- 差分探针已产出两个解释器的 OK/MISSING 对照，足以裁决环境 vs 代码，不再追加检索或探针
- 首波检索已命中该错误类的预存分类 memory 时，不再用变体关键词扫其余搜索后端

## Verification
- 裁决依据是本次实际执行的 import 探针输出（每个模块每个解释器的 OK/MISSING），不是沿用旧文档或记忆结论
- 核对 manifest（pyproject/uv.lock）确实声明了所缺依赖，排除『漏声明依赖』这一竞争解释

## Counterexamples
- 缺失模块未在 manifest 中声明 → 可能是真实的依赖声明缺陷，探针不能直接裁决为环境问题
- 两个解释器 import 都成功或都失败 → 环境绑定假设被证伪，错误另有原因（如版本不匹配），转根因流程
- 检索记录显示该失败是本轮新引入、无『干净 HEAD 同样失败』记录 → 不能复用预存结论，需 baseline 对照
- 用户诉求是让代码在无依赖环境也能跑（懒加载/依赖隔离改造）而非分类裁决 → 属实现任务，本方法只回答 go/no-go
