---
method_id: gate-cap-rejection-read-assembly-then-split-at-measured-boundary-e4fad2a53218
name: gate-cap-rejection-read-assembly-then-split-at-measured-boundary
description: 审查/准入门以确定性容量错误（如 review_artifact_exceeds_cap；历史码 review_artifact_exceeds_192kb 已随上限升到 2.5M 字符而废止）拒绝操作、而非给出内容判定时，把门自身的材料组装代码当作下一事实源：用拒绝字符串 grep 活树实现，回答三个未知量——材料字节如何冻结（committed/uncommitted/untracked 各自计入）、范围终点是否固定（本集终点=repo HEAD，即刻排除『换 refspec 推中间 SHA』这类不改变冻结范围的假解）、树内注释是否写明超限的官方补救（拆分/多部分）。随后按逐单元字节测量选拆分边界，用移动真实终点的方式分批过门，并验证各段 base 链式衔接使审查并集==完整原 delta、无覆盖缺口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:347:9927bf11cacb583873db
evidence_refs: learning:learn:f1935049ba6d
created_at: 2026-10-21T15:47:44.239077+08:00
updated_at: 2026-10-21T15:47:44.239077+08:00
---
## Trigger
自动审查/准入/CI 类门以确定性容量上限错误拒绝操作（错误 reason 点名具体上限或 artifact 尺寸），且被拒材料是门从仓库状态机器组装冻结的（diff+工作区改动+untracked 内容），不是用户可直接裁剪的自撰内容

## Discriminator
拒绝 reason 字符串可 grep 钉到门实现中的上限常量与材料组装函数（本集 192KB 常量旁注释即写明超限作用域『确定性地要求拆分或多部分审查』）；组装代码当时即可见 delta 公式为 git diff base..HEAD——终点固定为 repo HEAD，这条事实在动手前就排除掉一切不移动 HEAD 的缩小技巧

## Short path
- 收到容量拒绝后，第一步用错误字符串 grep 活树门实现（勿扫 .releases/ 等快照镜像），钉住上限常量与材料组装函数
- 读组装函数：确认 delta 终点（是否固定为 repo HEAD）、字节构成项（committed/uncommitted/untracked 各限额），并查相邻注释是否写明超限的设计内补救
- 按逐单元（逐 commit）diff 字节测量选拆分边界：每段低于上限且留余量（余量覆盖段内新增 untracked 体量），同时核对边界 checkout 是否会碰脏文件
- 用移动真实范围终点执行拆分（stash 噪音改动→checkout 边界 commit→过门推送），拒绝不改变门冻结范围的 refspec 类技巧
- 逐段验证冻结 base 链式衔接（后段 push_remote_base==前段终点，链首==原远端 base），确认审查并集==完整原 delta 无缺口；全部落地后恢复工作区（stash pop、HEAD 回最终 commit）

## Stop conditions
- 各段材料均被受理且 PASS、对应推送落地
- 段间 base 链与并集覆盖已验证等于完整原 delta 后停止，不再为同一 delta 增开新审查段
- 门实现无树内补救且拆分会破坏门的原子审查语义时，停止自助绕行，转缺陷上报/人工通道

## Verification
- 每段回执的 base 行（push_remote_base）==前一段终点 commit，且链首==操作前远端 base
- git diff <原base>..<最终HEAD> 的文件数/字节与各段已审查 delta 之并集一致，无未审查缺口
- 最终远端 ls-remote 与本地一致；整备过的 stash/脏文件按承诺恢复

## Counterexamples
- 门给的是内容判定（REVISE 或带 finding 的 PASS）——那是内容问题，读 findings 改代码，与材料组装无关
- 被限材料是用户自己撰写、可自行收缩的产物——直接裁剪自己的工件，不必读门代码设计拆分
- 拆分会破坏门的原子语义且树内无设计补救（如安全审查要求整变更一次过审）——上报调上限或走人工通道，勿自造覆盖缺口
- 上限属传输/分页类限制且存在更窄查询（分页、路径过滤）——先收缩检索范围，不重构操作本身
