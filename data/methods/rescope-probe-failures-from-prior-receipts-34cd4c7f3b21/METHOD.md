---
method_id: rescope-probe-failures-from-prior-receipts-34cd4c7f3b21
name: rescope-probe-failures-from-prior-receipts
description: 在多远程/多候选端口的镜像式 checkout 环境中，探测失败若属于“作用域内解析不到”类错误（如 gh 的 GraphQL could-not-resolve、TCP 连接拒绝），应先从先前权威回执中已有的标识符（状态快照里的 live pid、一步可查的真实 remote）推导出正确作用域，再带作用域重试；而不是枚举其他仓库的日志/PR 列表、假设服务故障或滋生额外假设。附带两条时序纪律：远端合并后必须重新 fetch 再本地 merge；网络探测必须带超时。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1807:1657a9bd0f393a03c3f4
evidence_refs: learning:learn:c013c4b2bece
created_at: 2026-09-19T08:17:23.307133+00:00
updated_at: 2026-09-19T08:17:23.307133+00:00
---
## Trigger
环境存在多个 git remote 或多个候选端口（镜像/双仓 checkout），对远程对象（PR/issue）或本地服务的探测返回“资源在当前作用域不存在”类错误，而初始状态快照或一步可得的事实（remote 列表、live pid）已包含可定位真实作用域的权威标识符。

## Discriminator
错误类别是“作用域内解析失败”而非瞬时失败（could-not-resolve / 连接拒绝 rc=7，区别于超时/5xx/鉴权失败），且先前回执（部署状态快照）已给出 live pid、或 `git remote -v` 一步可确认真实 remote——这两点把“很多种可能坏了”缩成“探测解析到了错误作用域，带正确作用域重发一次”。

## Short path
- 读初始状态快照，缓存权威标识：各服务 live pid、live/desired git_head、stable 收据代数，明确唯一残留未知量。
- 所有 gh 查询前先 `git remote -v` 确认真实 remote 并显式 `-R`；若遇 could-not-resolve 即判作用域错配，换作用域直接重试，不枚举其他（legacy）仓库的 log/PR 列表，也不滋生 squash-SHA 重写类额外假设。
- 服务健康检查：用快照中的 pid 做 `lsof -p <pid>` 取真实监听端口，再 curl 该端口（必带 --max-time）；401/404 响应即证明进程存活，不做默认端口猜测。
- 机制类疑问（收据为何停在旧代）直接读对应源码段确认写回语义；一旦确认“中断不落收据、下次成功受控重启自愈”即停止追查。
- 远端合并成功后，比较本地 fetch 时间与 mergedAt；fetch 早于合并则先重新 fetch 再本地 merge，并用 PR 文件内容级 diff=0 验证结果完整进入，最后跑聚焦测试（双方都动过的文件）。

## Stop conditions
- live pid/head 已由权威回执确认且与 desired 一致，且所有远程事实均来自正确 `-R` 作用域的回执。
- PR 状态/CI/合并结果、本地 main 收敛、聚焦测试全部基于重新 fetch 后的数据，无旧引用残留。

## Verification
- gh 回执对应仓库与 `git remote -v` 的真实 remote 一致，不再出现 GraphQL resolve 失败。
- curl 目标端口来自已知 pid 的 lsof 输出，而非默认端口猜测。
- 本地 merge 前的 fetch 晚于远端 mergedAt；PR 变更文件对合并结果 diff=0。

## Counterexamples
- 单远程且 gh 默认仓库已正确配置时，无 `-R` 调用本身正确，先查 remote 属多余仪式。
- 错误是超时、鉴权失败或 5xx 时，应重试/换凭据而非改作用域。
- 先前回执不含目标服务 pid（服务从未被枚举）时，pid 定位法不适用，只能做全监听端口扫描。
- 纯本地 merge-推送流程（无远端侧合并）时，无 fetch 时序问题，重 fetch 步骤不适用。
