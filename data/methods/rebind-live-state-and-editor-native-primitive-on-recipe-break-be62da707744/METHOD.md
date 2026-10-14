---
method_id: rebind-live-state-and-editor-native-primitive-on-recipe-break-be62da707744
name: rebind-live-state-and-editor-native-primitive-on-recipe-break
description: 重放已固化的浏览器自动化配方时，任一步骤在有状态富文本编辑器上失败（目标 tab 找不到 / 事件不生效 / 既有块格式被降级），先重读 live targets 列表确认当前 URL 状态并与配方假设对比——状态型应用会在 mutating 步骤后自动跳转（如草稿自动保存后 /write 变 /edit）；再对照先前经验卡『当前状态接受哪种输入原语』切换原语，而不是枚举更多操作变体（块类型按钮、段首 Backspace、Ctrl+Z）。插入类内容应锚定在真实输入新建的独立空块内、以编辑器接受的原语交付（paste File / insertText），不在既有格式块上重建选区；图片必须以 File 对象投递，data URI 内嵌只会得到占位图。本集正是 /write 粘贴后自动跳转导致找页失败、/edit 三轮块操作弯路，改空块锚定后一次通过。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:6198b7b1-67ec-407c-8e94-f9f028f1f197:1:0aec9a402c0813c13c40
evidence_refs: learning:learn:717243527ab5
created_at: 2026-10-13T20:56:18.523968+08:00
updated_at: 2026-10-13T20:56:18.523968+08:00
---
## Trigger
重放先前已验证/固化的自动化配方于有状态富文本编辑器（存在 URL/模式跳转、内部编辑器模型不接受程序化选区），且某步开始失败：目标页找不到了、合成事件不登记、内容或块格式未按预期变化。

## Discriminator
两条当时已知的事实：（1）流程早期已读过的经验卡明确写明目标存在多个页面状态、且各状态接受的输入原语不同（如合成 paste 在状态 A 可用，状态 B 只认 insertText/真实按钮）；（2）CDP targets 列表一次只读调用即可给出当前真实 URL/title，能立即判定配方假设的状态是否已漂移。失败发生时这两条都已在手，却先被用来枚举更多操作变体。

## Short path
- 配方步骤失败时，先重读 targets 列表，把当前 URL/title 与配方假设状态对比；漂移则立即重绑目标，后续步骤按新状态的约束执行，而不是按旧 URL 继续找页
- 判定失败属于状态漂移还是原语不匹配：若当前尝试的原语不在该状态已知接受集合内，立即换成已验证原语（真实键入 / paste / 按钮点击），不再重试同族变体
- 插入类操作不在既有格式块上重建选区：在目标位置块末真实点击→真实 Enter 造独立空块→在空块内以接受的原语交付内容；图片用 File 对象 paste，不随 HTML 内嵌 data URI
- 每个 mutating 步骤后重新确认目标未再漂移；发布前跑编辑器门禁（标题/标题级数/图片 loaded/声明），发布后公网拉取复核，差异回写配方与经验卡

## Stop conditions
- 编辑器门禁全部通过且发布按钮可用、或公网 URL 渲染出预期标记，即停止探索不再追加确认
- 对当前状态做完每原语类一次的最小诊断探测后仍无已知接受原语：停止枚举变体，记录新经验卡后收手
- 内容已用长度/grep/sha 与源稿核对一致即停止修补

## Verification
- 每个 mutating 步骤后重读 targets 确认 URL/title 与预期一致，不一致先重绑再继续
- 粘贴/插入结果用长度、grep 关键串或 sha256 对源稿复核，编辑器字数口径不等不代表内容缺失
- 发布后公网 fetch/render 校验标题、标题级数与图片数，占位文字泄漏即视为失败

## Counterexamples
- 目标是稳定 URL 的静态表单/页面：无状态跳转，配方可沿用初始句柄，逐步状态重检纯属开销
- 编辑器接受程序化 DOM 修改（如普通 textarea 或无内部块模型的 contenteditable）：原地编辑有效，空块锚定不必要
- 先前经验卡未记载该状态的接受原语：无法直接『换已知原语』，必须先做最小诊断探测再决定
- 任务目的是修改既有内容而非插入新内容：空块追加不适用，应改用该状态已验证的替换原语（选区+insertText）
