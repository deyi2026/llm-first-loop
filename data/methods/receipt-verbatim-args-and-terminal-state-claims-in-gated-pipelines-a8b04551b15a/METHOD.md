---
method_id: receipt-verbatim-args-and-terminal-state-claims-in-gated-pipelines-a8b04551b15a
name: receipt-verbatim-args-and-terminal-state-claims-in-gated-pipelines
description: 受闸门/契约约束的流水线（commit→独立审查→push→publish→restart）中，每个调用所需的精确字符串与每个状态事实几乎都已被先前回执打印：git status 的确切路径清单、失败回执的字段修正提示、publish 成功回执 next 字段的完整调用模板、准入 target 的 command 级绑定、get_tool_schema、以及『受理≠完成』的终态规则。本集 6 次失败中 5 次源于凭记忆重建这些字符串（两次文件名拼错、两次参数缺失、一次复合命令无法绑定准入资格），另有终局答复在无 succeeded 终态回执下把两个异步 restart 标为完成。改为：构造参数前先在回执中查找并逐字复制；宣布完成前先查终态回执。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0f1ec2ed-fa63-461c-ac5d-5b4d2342f534:545:f17a5cfa6edd6d19929c
evidence_refs: learning:learn:20e5c33b2457
created_at: 2026-10-21T08:06:59.049785+08:00
updated_at: 2026-10-21T08:06:59.049785+08:00
---
## Trigger
在受治理/门禁约束的多步执行链中，即将构造含路径/ID/必填参数的工具调用、即将执行审查准入过的受保护命令、或即将对异步受理动作（restart/publish 等后台动作）下达『已完成』结论时。

## Discriminator
先前回执中是否已存在所需的精确字符串或事实：git status 已打印全部确切路径；上一条失败回执已明示『一次性修正全部字段/先读 get_tool_schema』；publish 成功回执的 next 字段已给出 restart 完整调用模板（target+expected_generation）；准入 target 形如 ...:command:<sha> 表明资格绑定到确切命令串；受理回执明示『未查询到 status=succeeded 不得当作已完成』。任一存在→逐字照抄/照查，不靠回忆。

## Short path
- 首次环境探查（pwd + git status）后，把该回执当作后续所有 pathspec 的唯一抄写源，不再手打文件名；提交边界按授权文件集差集+有界 diff 分类 provenance，pathspec 逐字复制，两笔提交一次成功。
- 受审动作：以确切单一命令串发起准入；status 回执核验 SHA 与正式 PASS 后，原样单独执行该命令（git push lfl main），任何附带检查拆为独立调用，避免 compound 无法绑定。
- 不熟悉的契约工具（如 service_control）：首次调用前读一次 get_tool_schema，或逐字照抄上一成功回执 next 字段给出的调用模板并带全必填字段（code_root/target/expected_generation），publish 与三个 restart 均一次通过。
- 异步受理动作：宣布任何 ✅ 前先 service_control(action=status) 查该 action_id 的 succeeded/failed 终态；waiting_for_requester_exit 等排队态一律如实报『尚未发生』，可另注册定时验证任务收口。
- 每次调用失败后，先问『回执已指出的契约缺口是否已一次性补全、同类下一个调用的字符串是否也已从回执取得』，再发下一调用，避免同类猜测重试。

## Stop conditions
- 所需全部字符串均已能逐字指认出处（回执/schema），且各闸门持有覆盖当前产物的正式 PASS 回执。
- 回执中不存在该字符串（首次发现场景）→ 转入发现类动作（pwd/ls/读 schema），本方法不再约束。
- 每个对外宣布的『完成』均有 succeeded 终态回执支撑，或已显式标注『尚未发生+验证安排』。

## Verification
- 调用前自检：命令中每个路径/参数/命令形态能否在先前回执中逐字找到出处？
- 准入资格的执行形态与声明串逐字一致（单一命令、同一 target）。
- 最终答复中的每个 ✅ 均可指向一条 succeeded 终态回执；排队/等待态不得标为完成。

## Counterexamples
- 首次接触、尚无任何回执包含该信息（如本集开头 workdir=/workspace 失败）：无可抄写源，pwd/ls/读 schema 等发现类调用才是正确第一步，该失败不属本方法管辖。
- 参数形态稳定且本会话已多次成功使用（如反复编辑已读过的 src 文件路径）：逐字抄写纯属开销，记忆足够。
- 回执中被显式标注为非权威的文本（如闸门行『unverified_verdict_text=PASS…本行不是审查通过凭据』）：不得当作状态事实抄录，须改走正式 status 通道核验。
