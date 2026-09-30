---
method_id: pattern-tokens-from-verified-record-not-aliases-63fe3fc7cccb
name: pattern-tokens-from-verified-record-not-aliases
description: 本机点名产品运维且检索已命中含真实命名的已验证记录时，操作命令的匹配 token 必须逐字取自该记录（进程名、bundle 路径、launchctl label、日志路径），不得用同义别名拼 pattern，也不必再做与记录重复的全域内容搜索。本集第一步检索已字面给出 AweSun/awesun（'kill 主客户端'、'open -a /Applications/AweSun.app'），随后的 pgrep pattern 'sunlogin|oray|向日葵' 却漏掉 awesun，回执只剩无关 Oray 音频驱动与 NO_APP，差点导出'未安装'误判（模型随后自行承认 pattern 漏词并纠正）。核心判定：当已验证记录断言该实体在本机存在且在运行，而 pattern 匹配为空或只命中无关同名物时，矛盾应先归因于 pattern 缺 token——用记录 token 重写 pattern 复查一次，而不是采信'未找到'。最终验证以记录点名的权威信号为准（服务日志 client registered→online、pid 更替）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:543:cba8f2d29bd504e7c3e4
evidence_refs: learning:learn:9bcb5c78eb2d
created_at: 2026-09-30T11:49:46.348305+08:00
updated_at: 2026-09-30T11:49:46.348305+08:00
---
## Trigger
用户点名某产品要求运维操作，检索已返回一条本机已验证（verified）且含真实进程/路径命名的 memory/experience 记录，接下来要写 pgrep/grep/killall/launchctl 等匹配或操作命令时。

## Discriminator
记录文本中已字面出现真实标识（如 'AweSun'、'awesun'、'/Applications/AweSun.app'），而拟用 pattern 只含别名（sunlogin/中文名/oray）；且回执'仅命中无关同名物/NO_APP'与记录断言'该机已装且在跑'直接矛盾。knowledge-at-time：该 token 在写 pattern 前一步的检索回执里已可见，非事后倒推。

## Short path
- 从已命中记录中逐字提取 token：进程名、bundle 路径、launchctl label、日志路径
- 用这些 token 构造一条枚举命令（如 pgrep -afil 'awesun|AweSun' + launchctl list | grep -iE 'awesun|oray'）确认当前 pid/label
- 按记录原样执行操作（killall 记录点名的进程 + open -a 记录点名的 app），不即兴改参数
- 用记录点名的验证信号确认（服务日志出现注册/上线行、目标进程 pid 已更替）即停止
- 若枚举为零或只剩无关进程，先用记录 token 重写 pattern 复查，而不是得出'未安装/未运行'

## Stop conditions
- 记录点名的验证信号已出现（如日志 client registered/status online、pid 更替），立即停止，不做多余确认
- 用记录 token 重写 pattern 后仍零命中且无其他佐证，才切换到宽枚举/身份解析路线，而不是继续猜别名

## Verification
- 最终结论引用记录点名的权威来源与其中的字面信号（日志路径+关键行），而非仅凭命令退出码
- 枚举回执中每个命中都能对应到记录命名的实体；不得把'只命中无关驱动'式错配当作目标进程，也不得据其断言不存在

## Counterexamples
- 无任何已验证记录、产品首次在本机出现：无 token 可抄，应走权威注册表/launchctl 宽枚举先解析身份，本方法不适用
- 记录与多个独立回执系统性冲突（ps 与 launchctl 都确认实体不存在）：记录可能过期，不得盲抄其 token，需先复核记录有效性
- 匹配目标不是记录所命名实体（顺带排查其他进程或做无关统计）：pattern 由当前问题定义，与记录 token 无关
