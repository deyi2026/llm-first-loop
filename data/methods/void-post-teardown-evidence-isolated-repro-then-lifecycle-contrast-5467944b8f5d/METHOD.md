---
method_id: void-post-teardown-evidence-isolated-repro-then-lifecycle-contrast-5467944b8f5d
name: void-post-teardown-evidence-isolated-repro-then-lifecycle-contrast
description: 裁决『平台不支持某能力』还是『我方工具层把能力弄坏』时，先做排序检查：若否定性证据是在工具层自身 teardown（超时被误归类、session drop、重连）之后取得的，且被测现象可能被断连销毁，该证据对归因无效。改用与嫌疑工具零共享生命周期的最小通道（自建 target + 最小协议客户端 + fire-and-forget）复现能力；成立则归因转工具层，再做单变量生命周期对照（超时不断连 / 断唯一连接 / 断两连接之一）钉死致命事件，最后以错误串 scoped grep 定位代码机制。why_shorter：一个排序判断直接作废一轮宽假设，把归因压成单变量对照路径，避免在已被仪器销毁的现场继续采证。
aliases: No dialog is showing 不一定是真没弹窗, 取证对象被自己工具弄坏了怎么排查, 平台不支持还是工具层背锅, 断连之后拿到的证据还能信吗, 最小 CDP 客户端隔离复现弹窗, 超时和断连哪个才致命
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:2337:ae5e428c2ec204e92e70
evidence_refs: learning:learn:34bf3344c40a
created_at: 2026-10-28T11:23:29.299287+08:00
updated_at: 2026-10-28T11:23:29.299287+08:00
---
## Trigger
需要裁决『平台/协议本身不支持』还是『我方工具层破坏了该能力』，且已有失败记录中工具层自身带生命周期信号（超时归类、session drop、重连），而随后的『直接验证』动作发生在这些 teardown 事件之后

## Discriminator
证据时间顺序：否定性证据是否取自工具层 teardown 之后。先前回执里已可见 mode=timeout 的降级错误、且回执文本写明取证是『事后直连』——若被测现象（同步模态、会话态资源）会被断连销毁，事后取证描述的是被仪器破坏后的世界，不能用于平台归因

## Short path
- 读先前失败记录并排序：teardown 事件（timeout→drop session）与『事后直连取证』谁先谁后；未知量：否定证据是否取自被破坏后的现场
- 判定证据无效后，建立零共享生命周期的最小通道：自建新 target、自写最小协议客户端、可能无响应的命令用 fire-and-forget，跑能力矩阵（前台/后台、有无 user activation）
- 隔离通道下能力成立 → 归因转向工具层；做单变量生命周期对照：超时但不断连 / 断掉唯一连接 / 两条连接断其一，钉死致命事件（是 drop 而非 timeout）
- 用错误字符串与 teardown 调用点做 scoped grep 定位代码机制（如异常分类表把 TimeoutError 当连接丢失后无条件 drop）；要求单一机制同时解释隔离矩阵与对照结果，再落修复规格

## Stop conditions
- 隔离矩阵全绿 + 对照实验钉死唯一致命事件 + 代码机制能同时解释两者，即停止实验、进入修复规格
- 隔离通道下能力同样失败 → 仪器破坏假设被证伪，转平台侧排查，不再扩工具层假设

## Verification
- 复跑对照：超时但保持连接后操作仍成功；断唯一连接精确复现原始症状（否定错误 + 永久阻塞）
- 按修复规格修改后，原失败 case 经原工具层复测通过

## Counterexamples
- 工具层回执干净、无任何 teardown/重连信号 → 不必先建隔离通道，直接排查任务/页面本身
- 现象不会被断连销毁（DOM 已写入、持久化副作用、文件产物）→ teardown 后取证仍有效，事后直查即可，隔离实验是多余成本
- 最小隔离通道下能力同样失败 → 平台假设复活，隔离只完成了一半归因，不能就此写工具层结论
