---
method_id: verify-cited-provenance-directly-before-broad-discovery-cf251ae62c83
name: verify-cited-provenance-directly-before-broad-discovery
description: 审查/核实一份含具体引用的技术分析时，引用清单本身就是权威定位表：记录ID→日志、函数/配置名→源码、行数与比例断言→审计文件。应先对每个引用在canonical位置直接读取并用脚本重算被引数字，再读实现验证语义断言；不要先做文件名/关键词宽搜索——宽搜索只会命中eval副本、测试、env备份等噪声。搜索仅用于定位唯一unknown（如canonical路径），一次定位后即转入直接测量。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:128:c92debcce0c4c71f8fd3
evidence_refs: learning:learn:7170b9bd7149
created_at: 2026-09-30T08:57:07.456666+08:00
updated_at: 2026-09-30T08:57:07.456666+08:00
---
## Trigger
任务是对一份上游分析/报告做事实审查，且被审文本已包含具体可核引用：精确记录ID、文件/函数/配置名、可重算的数字断言及其声称口径。

## Discriminator
任务起点时被审文本已给出每条待核事实的精确指针（记录ID、符号名、数量断言），宽搜索不产生新信息；唯一可能的unknown只是canonical artifact的路径，一次定向查找即可消除。

## Short path
- 从被审文本提取引用清单：记录ID、文件/函数/配置名、每条数字断言及口径
- 对每条引用直接定位canonical来源（数据日志、src实现、git历史）；路径类unknown只做一次定向查找
- 用脚本对权威文件重算被引统计（总数/分子/分母/条件率），与被引数值逐项对照
- 读实现代码验证语义断言（窗口、过滤顺序、分母单位），落到具体行号
- 对分析中悬置的机制问题读调用方/实现补齐，汇总差异表后停止

## Stop conditions
- 每条被引事实都已有当前权威来源的实测值，或被显式标记为无法定位
- 重算值与被引值一致，或偏差已列入结论表
- 无剩余待核引用；不再为额外确认发起宽搜索

## Verification
- 关键统计由本地脚本对canonical文件重算，不依赖搜索命中片段或转述
- 每个语义断言对应到具体代码行或记录ID，可独立审计
- 无法核验的转述被显式标注为不可核，不与已核事实混同

## Counterexamples
- 被审文本无具体引用、只有模糊断言：必须先自行定位证据，宽发现阶段合理
- 引用指向外部/不可达系统或路径已失效：先做一次定位或澄清，不能直接下结论
- 开放探索任务（无引用清单），目标是发现未知问题而非核对已知断言
- 审查目标是分析的说服力或写作质量而非事实真伪：无需逐条重算
