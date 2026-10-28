---
method_id: classify-named-sha-vs-fetched-main-then-partition-port-ef40148b4bf9
name: classify-named-sha-vs-fetched-main-then-partition-port
description: 用户以指定 SHA（『当前/生成是 X』）锚定合并推送并要求『不能倒退』时，先 fetch 权威远端 main，再做三向 ahead/behind + 祖先计数，把点名 SHA 的角色定死：严格祖先 ⇒ 生产 floor（必须保留在历史内）而非最新 tip；分叉领先 ⇒ 它是待并入贡献线。随后用 merge-base..main 的 diffstat 限定本批提交触碰的文件，把集成二分：未触碰的提交直接 cherry-pick；被触碰的文件读 main 现行版后手工移植语义、复用其既有结构（避免重复键、避免覆盖他人修复）。push 后用 ls-remote 验证旧 tip 与点名 SHA 都在新 main 的祖先链。杜绝在 tracking 指向镜像、权威 main 尚未 fetch 时就下倒退结论或对点名 SHA 做考古。
aliases: 不能倒退 推main前怎么确认不回退, 用户说的commit是最新的还是生产在跑的, 分支落后main 先fetch权威远端再比ahead behind, cherry-pick撞上main改过的yml怎么合, 同名配置键冲突 手工移植到main现行版
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:380:dbb653a24dc3ecdd7797
evidence_refs: learning:learn:d1b61baeab48
created_at: 2026-10-27T19:23:52.778105+08:00
updated_at: 2026-10-27T19:23:52.778105+08:00
---
## Trigger
用户点名一个 commit SHA 作为『当前/最新/正在跑的生成』，并提出合并到 main/生产、附『不能倒退』类硬约束；且工作区多 remote、当前分支 tracking 指向非权威或镜像 ref、权威远端 main 本地尚不存在（unknown revision）。

## Discriminator
初始一次 git 状态/remotes 输出已同时暴露三事实：权威远端身份（URL 指正式仓库）、分支 tracking 指向本地镜像路径、权威 main 本地 unknown revision。这三点 ⇒ 一切『倒退与否』判定与点名 SHA 的角色推断在 fetch 权威 main 之前无效；点名 SHA 领先本地分支 ≠ 它是最新（它可能只是权威 main 的祖先/生产 floor）。

## Short path
- 从首个状态输出识别权威远端，并发现权威 main 未 fetch → 立即 fetch 权威 main（未知量：『不倒退』的参照系是什么）
- 三向计数：我的分支↔权威 main、点名 SHA↔权威 main、分支↔点名 SHA（未知量：SHA 的角色——tip / 严格祖先（生产 floor）/ 分叉贡献线）
- SHA 为严格祖先 ⇒ 它是必须保留的 floor（生产在跑），真正目标是权威 main；『只并到 SHA』本身就是对 main 的倒退
- 对 merge-base..权威 main 的 diffstat 限定在本批提交触碰的文件（未知量：哪些提交可干净移植、哪个文件必须手工合）
- 基于权威 main 建集成分支：未触碰提交直接 cherry-pick；被触碰文件先读 main 现行版，再手工移植语义并复用其既有结构（如已有 concurrency 块），不机械重放旧版
- push 后用 ls-remote 验证：旧 tip 是新 tip 祖先、behind=0、点名 SHA 仍在历史链中

## Stop conditions
- 权威 main 新 tip 已包含旧 tip 与点名 SHA（对旧 tip ahead>0、behind=0），且仓库门禁通过
- 移植文件机械解析校验通过（无重复顶层键），本批语义全部落在 main 线上，无 SHA 考古遗留支线

## Verification
- git ls-remote 权威远端：旧 tip 与点名 SHA 均可被新 main SHA rev-list 到（均为其祖先）
- 双向 rev-list --count：old_tip..new_main>0 且 new_main..old_tip=0
- 对移植后的配置文件做 YAML/JSON 解析级校验，确认顶层键唯一、未与 main 侧既有块重复

## Counterexamples
- 点名 SHA 真的领先一切（未进 main 的 hotfix/分叉线）：SHA 是待并入的贡献而非 floor，目标是『main+SHA』双向合流，本卡『只盯 main』的分区不成立
- 单 remote 且分支 tracking 即真 main：fetch-pin 判别事实不触发，直接比较即可，无需三向角色分类
- 远端推进完全没碰我的文件：整批干净 cherry-pick 即可，手工移植分支空转
- 冲突是语义不兼容而非结构碰撞（新逻辑根本改写了我的功能前提）：复用既有结构的移植不够，需按新语义重设计
