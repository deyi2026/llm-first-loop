---
method_id: gate-boundary-fresh-status-and-residual-triage-under-concurrent-writers-5d18784881c0
name: gate-boundary-fresh-status-and-residual-triage-under-concurrent-writers
description: 在存在并行写入者的工作区执行'掩码→入库→publish'等需干净树的任务时，首轮 status 清单会随中间动作（编辑、远端核查）变陈旧：直接按它批量 git add 会漏掉中途落盘的新产物，导致追加提交轮次乃至发布不完整。方法：首轮 status 只当计划输入；在每个状态改变边界（staging 前、publish 前）重读 status -uall，对新增残余按类分流——同计划类并入当次提交；计划外交付物须同时满足仓库惯例（同类已跟踪兄弟+.gitignore 豁免面）、写入者已停（mtime 稳定+无活跃进程）、敏感/密钥扫描零命中才入库；敏感中间产物留本地。与'终局断言前重读权威记录'不同：本方法作用于操作边界而非输出断言，且含残余项分类裁决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:1952:7716a280ee01853e50d4
evidence_refs: learning:learn:541856aebf98
created_at: 2026-10-14T20:03:41.752041+08:00
updated_at: 2026-10-14T20:03:41.752041+08:00
---
## Trigger
多写入者工作区（首轮 status 已见其他会话当日产出的未跟踪记录，即写入者活跃的直接证据）中，执行以干净树为前置的批量状态变更链：git add/commit/push、部署 publish 门禁。

## Discriminator
用作 add 执行清单的 status 快照与实际 staging 之间隔了编辑/核查等中间动作，且首轮清单本身已证明当日有并行产出者——快照年龄与活跃写入者并存即按陈旧处理，不需要额外猜测。

## Short path
- 首轮 status -uall 仅建立计划与发现面，不作为稍后 add 的执行清单
- 每次 staging 边界前重跑 status -uall，与上一清单 diff，新增项显式列出
- 同计划类新增（同目录记录类）→ 并入当次提交
- 计划外交付物 → 依次核：仓库惯例（同类已跟踪兄弟/.gitignore 豁免）、写入者停笔（mtime 稳定+无活跃写入进程）、敏感/密钥扫描零命中；三者齐备才入库
- publish 前最后一次 status 必须为空（或仅剩已裁决留本地项），且 publish 绑定的 git_head 即最终 commit

## Stop conditions
- 最终 status -uall 为空且 publish 成功推进 desired generation
- 残余项经惯例核实属仓库不跟踪类 → 记为观察项并停止，不强提
- 新增项属敏感中间产物 → 显式裁决留本地并记录理由后停止

## Verification
- 每次 add 前后 status 对比，确认无清单外新增被遗漏
- 最终 commit 后 porcelain 为空，publish 回执的 git_head 等于该 commit
- 计划外入库项留档三证据：惯例依据（跟踪兄弟/ignore 规则）、mtime 稳定时长、敏感扫描结果

## Counterexamples
- 单写入者工作区，或清单与 add 在同一命令链内即时取得 → 无陈旧风险，不必额外重读
- 新增项是含密钥的扫描中间产物 → 不得按同目录类自动并入，应留本地
- 文件仍被活跃写入（mtime 持续变化/进程在写）→ 不入库防半成品；超过稳定窗口仍不稳则交用户裁决而非无限等待
