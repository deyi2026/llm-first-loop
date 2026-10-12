---
method_id: bound-verification-output-to-survive-truncation-5879c1e4cca7
name: bound-verification-output-to-survive-truncation
description: 当一次验证只为回答一个小而离散的未知量（如『干净树上这6个具名测试是否通过』），而命令原始输出很长时，先塑造命令使关键事实能扛住输出截断：精确选择条目、tail 汇总行、显式 echo 退出码，并对 stash/pop 等状态改动加守护回显。若截断已发生且实验廉价、确定、近似幂等，直接带界重跑一次，胜过依次枚举 evidence hydration / evidence search 等恢复路径。本集一个二元事实消耗了 5 次动作（截断的复合命令→hydrate→search_evidence→grep 重试→tail 重试），带界单次运行即可闭合。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:662:b39be267a3b1d303de43
evidence_refs: learning:learn:2976cec6de01
created_at: 2026-09-18T13:44:55.570436+00:00
updated_at: 2026-09-18T13:44:55.570436+00:00
---
## Trigger
需要用一个命令验证离散事实（测试是否全过、退出码、汇总行、守护标记），且可预见原始输出很长（此前同命令已产出多屏输出、含大量警告前导或进度条），或工具回执已显示输出被截断

## Discriminator
跑之前已经可见的事实：上一轮 pytest 输出同时暴露了（a）所需答案只占输出末尾一两行（short test summary / 最终计数 / 退出码），（b）完整输出很长（warnings 前导+进度条），（c）6 个失败测试的具名清单已知、可精确选择。这三点在运行前就足以推出：不限输出的全量复合命令必然把答案截在界外，而『选择+tail+echo 退出码』可把输出压到几行内。

## Short path
- 明确本次验证的唯一未知量（干净树上这6个具名测试是否通过），不捆绑其他子目标到同一命令
- 把输出压到只含答案：pytest 用具名/-k 选择加 -q，管道 tail 汇总行，或显式 echo 退出码；stash/pop 包裹时加 POP_OK 类守护回显
- 一次运行读出二元答案（退出码0/1 即够），不做第二次同源确认
- 据答案立即决策（该 WIP 不随 publish 上线：存补丁、还原工作树），进入下一未知量
- 交付前对树状态做一次终检（HEAD+零 diff），然后发出零 $ 符号、绝对路径的最终命令

## Stop conditions
- 关键事实（退出码/汇总行/守护标记）已在本次输出中完整可见，即停止验证并决策
- 实验昂贵、非确定或有外部副作用（长构建、变更外部状态）时，不再重跑，改走证据恢复或分页读取
- 同一未知量已由权威来源回答后，不再重复确认

## Verification
- 确认答案行来自本次运行的完整输出，而非截断片段或事后猜测
- 状态改动型验证（stash/pop）结束后确认工作树恢复原状：守护标记回显 + git status 零改动
- 最终交付物（命令）在目标 shell 语义下可原样粘贴执行：无会被 UI 渲染吞掉的符号、路径绝对

## Counterexamples
- 静态只读查询且结果已完整返回（如结构化 JSON 回执）：直接使用，无需重塑命令或预防截断
- 截断发生在所需内容中部而非尾部（如长 diff 的中段）：tail 汇总无效，应改用带 range 的分页读取
- 昂贵或非幂等实验（长构建、触网、变更外部状态）：截断后不应盲目重跑，证据恢复/日志检索才是正解
- 输出本身很短且无截断风险：加管道和守护回显反而增加命令复杂度与新的出错面
