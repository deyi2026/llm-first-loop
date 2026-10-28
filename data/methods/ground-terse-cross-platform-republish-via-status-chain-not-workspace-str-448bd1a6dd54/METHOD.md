---
method_id: ground-terse-cross-platform-republish-via-status-chain-not-workspace-str-448bd1a6dd54
name: ground-terse-cross-platform-republish-via-status-chain-not-workspace-streams
description: 多平台内容流水线中，某期稿件刚在 A 平台收口、用户以「XX也发」式极简指令要求同稿发 B 平台且无活动 goal 时，不要用 workspace 级事件流、evidence 全量列表或通配符文件枚举重建上下文——其命中被无关并行会话噪音 dominated。指代与做法可由流水线自身记录链一次钉死：按固定命名取最新期 STATUS（冻结稿件+SHA、当日各平台已核状态、防重复投稿），沿其交叉引用读同日 B 平台兄弟班次 STATUS（当日真实管线与补救路径），search_records hydrate 平台 verified 教训转为 preflight 断言，复用同日脚本执行；公网回读验收、落 STATUS/回执即停。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:ad51c21d-d323-4f1d-a93b-24ede269bdcf:344:3d72bc4e7954ceef89d9
evidence_refs: learning:learn:f7b9dbea51ee
created_at: 2026-10-20T15:19:53.989522+08:00
updated_at: 2026-10-20T15:19:53.989522+08:00
---
## Trigger
多平台内容流水线中，本会话/同日班次刚完成某期稿件在 A 平台发布并收口，用户随后以极简指令（如「知乎也发」）要求同稿发到 B 平台；get_goal 显示无活动目标，需重建『发哪份稿、B 平台怎么发』两个未知量

## Discriminator
指令中的『也』指向流水线当日刚收口的期次；工作区存在固定命名（STATUS-<日期>-<期号>）的最新 STATUS，其自身给出：冻结稿件文件名+SHA、『当日已核状态』表（直接判定 B 平台是否已有副本、防重复投稿）、对同日兄弟班次的交叉引用；加上 search_records 中平台 verified 教训。这四个窄来源足以钉死全部未知量——而 workspace 级事件流/通配枚举的回执 dominated 于并行会话的无关活动（如另一会话的 pytest、早晨截图），继续沿该宽分支不缩小任何未知量

## Short path
- search_files 固定模式 STATUS-<今日>*（或 STATUS-* 取最新）并通读最新期；未知量①：发哪份稿（冻结文件+SHA）、B 平台是否已有副本（有→按重复投稿规则停并报告）
- 沿该 STATUS 的交叉引用/当日状态表读同日 B 平台兄弟班次 STATUS；未知量②：B 平台当日真实发布管线（转换校验、插图、闸门、事后补救入口）
- search_records 按 B 平台+发布动作 hydrate verified 教训（如无发表前设置层、话题标签断言、图片刷新丢失须回读），转成 preflight/事后断言清单；未知量③：已知坑
- 定位并复用兄弟班次日期前缀脚本执行发布，preflight 断言逐项通过
- 公网/登录态回读验收（字数对齐、图数、小节结构、数值 token、话题、声明），追加 STATUS、落回执后停止，不再做额外发现

## Stop conditions
- 稿件身份已由最新 STATUS 冻结，且其当日状态表证明 B 平台无既有副本（否则停止执行并报告）
- 公网回读验收通过且 STATUS 追加与回执已落盘

## Verification
- 发布页与冻结稿逐字对齐、图数/小节/数值 token 命中、话题与创作声明可见
- 执行前以最新 STATUS 当日表+回执确认目标平台无重复投稿
- 所 hydrate 教训卡 verification_state=verified（preferably 同日验证）；未验证卡只作待证假设

## Counterexamples
- 指令指代非流水线期次的 ad-hoc 内容：无 STATUS 记录链，窄检索前提不成立，应先向用户澄清指代
- 目标平台当日无兄弟班次先例（首次发布）：『怎么做』一跳不存在，退化为教训卡+受控探测，适度探测不算绕远
- 最新 STATUS 落盘早于用户所指事件或用户意指旧稿：直接取最新期会拿错稿，须以标题/回执核对指代再动手
- 无并行会话的小工作区：全量枚举成本与窄检索近似，方法收益消失（无害但不再更短）
