---
method_id: probe-write-tools-by-declared-side-effect-class-with-preplanned-undo-db902be86715
name: probe-write-tools-by-declared-side-effect-class-with-preplanned-undo
description: 只读约束下要证明工具『本会话可实际调用』时，先用 schema/工具目录给每个目标标注副作用画像：纯读、带只读 action、写但文档化先验拒绝、纯写无校验保证。『用非法参数预期确定性拒绝』的探测只在契约文档化『拒绝先于落状态』时安全；纯写工具应改用同族零副作用成员的真实成功回执证明通道连通+注册面证明存在。若任务要求直接证明，把探测+终态回收预规划成原子对（最小参数、调前备好 undo、披露账本残留）。本集 lane_open 用假 goal_id 探测被真实登记 lane，被迫追加 lane_close 回收并披露，正是未读副作用画像的代价。
aliases: 只读诊断怎么验证写工具能调, 预期失败的探测把状态真写进去了, 假goal_id探测被真实登记, 探测写工具先看会不会落账, 写侧工具配好回收再调用, 工具可调用性三态区分
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:0:ce42fa0ce27a41017c2c
evidence_refs: learning:learn:5f4021f9dd73
created_at: 2026-11-07T12:46:52.954559+08:00
updated_at: 2026-11-07T12:46:52.954559+08:00
---
## Trigger
只读/最小副作用诊断任务要求逐项确认一批工具『本会话可实际调用』（三态区分：代码存在/已注册/实调），且目标集合含状态创建型（写侧）工具，仅凭注册面不足以满足用户的证明要求

## Discriminator
探测设计前已可见：工具目录/schema 已逐条标注副作用画像——同族存在『纯函数，零副作用』（lane_gate_check）、『零写副作用』（lane_queue_status）成员或只读 action（review_admission 的 action=status 查询），而写入口的描述只声明『登记/创建』，未文档化任何输入存在性校验或『拒绝先于落状态』保证。只有契约写明带 reason_code 的先验拒绝门禁的工具，非法参数预期失败探测才无副作用风险。

## Short path
- 批量取注册面证据（get_tool_schema/目录搜索）时，同步给每个目标工具标注副作用类别：纯读 / 带只读 action / 写但文档化先验拒绝 / 纯写无校验保证
- 纯读与带只读 action 的工具直接实调；确定性业务层拒绝（如 qualification DENIED）即为通道连通证据
- 纯写无校验保证的工具：不发起预期失败实调，改用同族零副作用成员的真实成功回执证明通道连通，注册面证明存在，报告中标注『未实调原因=只读约束』
- 仅当任务明确要求直接证明写工具时：调前把探测+回收规划为原子对——选可立即终态化的最小参数、备好 undo（如 close→abandoned 的 reason）与披露句，再发起
- 按三态逐项汇报，未实测路径显式列出；一旦确证某关键工具不可调用即停止并报告阻断层与修复入口

## Stop conditions
- 每个目标工具均取得『已注册 + 连通证明或合理推定』，且探测未留下未回收的状态变化
- 任一关键工具确证不可调用：停止，不绕过，报告准确阻断层与应修复的配置入口
- 回收回执与误登记回执同 id/version 对账完成，报告已披露账本残留

## Verification
- 探测后用零副作用审计面（写路径审计已写条目、账本状态、lane 队列）确认无未收敛变化，或有终态化记录可对账
- 确认每个『可调用』结论都绑定真实回执：注册证据（schema 回执）与连通证据（实调回执或同族成员成功回执）分开引用，未实测路径如实标注

## Counterexamples
- 工具 schema 明确文档化先验拒绝（如『门禁：无有效 verify_ref 一律拒绝，reason_code=verify_required』）——非法参数预期失败探测安全且常是最廉价证明，不应绕道同族只读成员
- 同族不存在任何零副作用成员、且用户明确要求直接证明——必须实调，方法退化为『预规划探测+undo 原子对』而非『不调』
- 会话本身无只读约束——直接正常调用即可，分类探测纯属多余
