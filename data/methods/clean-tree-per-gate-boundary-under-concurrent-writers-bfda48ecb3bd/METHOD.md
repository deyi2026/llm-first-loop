---
method_id: clean-tree-per-gate-boundary-under-concurrent-writers-bfda48ecb3bd
name: clean-tree-per-gate-boundary-under-concurrent-writers
description: 多关卡发布链（准入冻结/发布快照/hash 绑定）中每个关卡都断言仓库工作树状态。已知己方工具副产物（如上一轮测试/门禁的 reports/ 扰动）必须在第一个状态断言关卡之前机械还原，而不是推迟到链路末端的『发布前』；每次被拒按回执点名路径还原并紧贴重试，压缩活动写者再污染窗口；脏路径先做写者归属判定，非己方（运行服务/并行 agent 流）改动不 revert，等其自行提交或协调。本集实证：污染已知仍拖到准入被拒才还原（多一轮整链重跑），随后服务持续写日志造成二次漂移，publish 再被并行流文件拒一次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:964:055552215af67fbac0ce
evidence_refs: learning:learn:e8f38969e6d6
created_at: 2026-10-17T01:23:27.370164+08:00
updated_at: 2026-10-17T01:23:27.370164+08:00
---
## Trigger
流水线含两个及以上以工作树干净为前提的关卡（准入/冻结/快照/publish 绑定），且进入首个关卡前 git status 已可见己方副产物扰动，或环境中存在运行中服务、并行 agent 流等并发写者。

## Discriminator
进入首个关卡前已同时成立三个已知事实：(a) git status 列出的具体脏路径及其来源（本集为中段观察到的 reports/ 扰动）；(b) 已验证经验或关卡语义表明这些扰动不还原无法通过状态断言；(c) 链路中在『发布』之前还存在更早的冻结/准入关卡。三者齐备即可判定：还原时机以第一个关卡为准，而非链路末端。

## Short path
- 启动关卡链前 git status，对每个脏路径判定写者归属：己方副产物 / 运行服务 / 并行流
- 己方已知副产物立即机械还原——不等『发布前』，因为最早的快照/冻结关卡就会被拒
- 关卡被拒：仅按回执点名的路径还原，还原动作紧贴重试执行，最小化并发写者再污染窗口
- 重试间出现新写入且归属为持续写者（如服务 usage 日志）：改为『每次重试前即时还原该路径』或争取关卡忽略，不再假定一次还原长期有效
- 非己方脏路径不 revert：归属并行流则等其提交或显式协调，重验 git status 后再走关卡
- 发布回执核对 generation/commit/产物 hash 与本地一致后，退出清理循环进入切代验证

## Stop conditions
- 全部关卡 PASS，且 publish 绑定的 commit 与构建产物 hash 与本地 HEAD、产物标识逐一一致
- git status 干净，或剩余脏项均已归属到明确写者并有『忽略/等待』的显式决策

## Verification
- 每次关卡尝试前重新 git status 并与上一次 diff：新增写入必须能归属到已知写者，否则先归属再重试
- 关卡/发布回执中的绑定 hash 与本地 HEAD、构建产物标识比对一致
- 每次还原后立即确认目标路径回到干净状态，不依赖记忆中的树状态

## Counterexamples
- 单人静态仓库、仅单个关卡、无并发写者：开始前一次清理即可，逐关重验只是开销
- 脏路径是刚完成的关卡自身合规产物且审计要求保留：应提交或让下游关卡白名单，还原是错误动作
- 阻塞紧急发布的外来文件归属已停滞的并行流：机械还原与无限等待都错，应升级协调接管而非二选一
