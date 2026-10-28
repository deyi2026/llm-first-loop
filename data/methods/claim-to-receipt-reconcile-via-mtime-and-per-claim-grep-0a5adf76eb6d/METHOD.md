---
method_id: claim-to-receipt-reconcile-via-mtime-and-per-claim-grep-0a5adf76eb6d
name: claim-to-receipt-reconcile-via-mtime-and-per-claim-grep
description: 当用户追问『文件在哪/真的改了吗』，或自己准备复述此前对本地产物的完成声明（已改N处、大小/行数、已渲染）而这些声明当时没有工具回执时，先把每条声明转成磁盘可核谓词再开口：stat 看 mtime（早于声称操作时间窗即一次证伪『刚改完』），再 grep 逐条核对具体改动标记；路径未知时从 cwd 有界定位而非猜绝对路径。只报告有回执的事实，未核数字一律标未验证并问是否实做。
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:ae5b131c-d837-4549-8a3b-9f8d7168745d:109:90a816bddb00a025b21b
evidence_refs: learning:learn:b0870895990e
created_at: 2026-10-17T17:20:47.796639+08:00
updated_at: 2026-10-17T17:20:47.796639+08:00
---
## Trigger
被用户追问产物位置或完成状态（『文件呢？』『改完了吗』），或即将复述此前关于本地文件的状态声明（已改动/已保存/尺寸行数/已渲染验证）而该声明无当次工具回执支撑；或发现自己正要引用一个会话中从未记录过的文件路径

## Discriminator
一次 ls -l/stat 暴露的 mtime 是最便宜的裁决事实：文件最后修改时间早于声称的操作时间窗，则全部『刚改完/刚保存』声明即刻证伪，无需先做内容核对。路径侧判别：会话中从未出现该绝对路径的任何记录（如 /workspace/... 属凭空猜测）→ 应从 pwd/cwd 解析。内容侧：每条具体声明（某属性值、某元素、某尺寸）都可机械转成 grep 谓词，miss 即为假。注意 mtime 只能证伪不能证实：mtime 新鲜不代表具体改动已落盘，仍需逐条 grep

## Short path
- 遇追问先核再答：pwd + 当前目录列表解析产物位置，禁止凭空猜绝对路径
- 有界定位：find . -maxdepth N -name <pattern> 一次查找，避免全树 find 超时后重试
- 对命中文件 stat：size/行数/mtime —— mtime 早于声称时间窗即判定『改动未落盘』，先推翻再细查
- 把每条声称的改动写成 grep 谓词逐条核对：命中=已落盘，miss=未落盘
- 输出『声明 vs 回执』对照表，只报已核事实；剩余工作明确标『未做』并询问用户是否现在实做，不再输出任何无回执的数字

## Stop conditions
- 每一条先前声明都已被机械回执裁决为真或假，且回复中不再含新增的未核数字
- mtime 落在声称时间窗内且全部 grep 命中 → 声明为真，停止核查直接回答
- 产物路径已由本次回执确认且无状态争议 → 停止验证，避免过度核查

## Verification
- 回复中每个关于磁盘状态的具体数字（大小/行数/改动处数）都能指向一条当次工具回执
- mtime 与声称的操作时间窗做过显式比对；每条改动标记的 grep 有真实命中或 miss 输出
- 无回执支撑的表述已显式标注『未验证/未做』，而非默认其为真

## Counterexamples
- 路径已在会话中有记录且刚被回执确认 → 不必整套重核，直接回答路径即可，过度核查反而烧调用
- 产物位于远端/网络文件系统或由构建流程再生成 → 本地 mtime 不可作为裁决依据，只能依赖内容 grep 或源头记录
- 声明的对象是临时态（内存中对象、渲染后即弃的帧）→ 无磁盘回执可核，应改用运行时验证而非 mtime/grep
- mtime 新鲜但可能被无关写入刷新 → 不能仅凭 mtime 宣称『改动已落盘』，必须逐条 grep 确认
