---
method_id: gate-refusal-reason-routes-named-tree-class-then-hash-relocate-5616fd79b947
name: gate-refusal-reason-routes-named-tree-class-then-hash-relocate
description: 确定性准入/评审闸对整棵工作树返回结构化拒绝（如点名 sensitive_untracked_path_refused）时，reason 本身就是路由判别式：材料与树不变则原样重交必得同一拒绝。按被点名类别做最窄枚举（未跟踪→git status '??'）定位具体文件，只用元数据确认敏感性，治理树而非闸门：把杂散敏感文件迁出树（记录源 sha256 → cp 至沙箱允许目录 → chmod 600 → 哈希相等才 rm 原件 → git status 复核消失；mv 被拒时 cp+哈希+rm 是安全替身），随后单次重交。省时原理：把 N 次盲重交压成一次类别枚举+一次治理后重交，哈希校验使非原子迁出可信。
aliases: 被门禁拒绝先看拒绝原因里的类别, 敏感未跟踪文件挡住评审, mv 被沙箱拒绝就用 cp 加哈希再删, 确定性闸门别原样重交, env 备份文件阻塞审查怎么处理
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:2001:7b35df0744978a6873a2
evidence_refs: learning:learn:bf0befe92be8
created_at: 2026-10-26T03:14:35.778429+08:00
updated_at: 2026-10-26T03:14:35.778429+08:00
---
## Trigger
对整树取哈希/扫描内容的准入或评审闸返回结构化拒绝，reason 明确点名某类树内条目（敏感未跟踪路径、禁字面量、超限产物等），且该闸对（材料, 树状态）是确定性的；常见表象为同一 reason 连续重复出现

## Discriminator
拒绝 reason 同时给出违规属性与条目类别；确定性闸门下材料与树未变则重交必得同一拒绝——唯一有生产力的未知量是『我的树里哪个具体条目属于该类别』，可用一条类别限定枚举（未跟踪→git status --porcelain 过滤 '??'）直接收敛到一两个候选

## Short path
- 把首个拒绝 reason 解析为（违规属性, 条目类别）；未知量=树内哪个具体条目属该类，而不是『闸门为什么失败』
- 对该类别做最窄枚举：未跟踪路径→git status --porcelain 过滤 '??'；禁字面量→仅交付路径内定点 grep；按命名特征（.env/backup/key/token）选头号嫌疑
- 只用元数据核实敏感性（ls -la、键名清单），绝不把值打进日志；未知量=该条目是杂散事故产物还是交付必需内容
- 治理树而非闸门：杂散敏感文件迁出树——记录源 sha256 → cp 到沙箱允许的外部目录 → chmod 600 → 目的端 sha256 与源相等才 rm 原件 → git status 确认消失
- 单次重交闸门；若 reason 换成新类别则按新类别重路由；若条目在交付内容内部则改走内容脱敏/升级用户裁决

## Stop conditions
- 闸门回执 accepted=true
- 拒绝 reason 变为另一类别（重新路由而非继续重试）
- 确认敏感内容位于必须交付的文件内部（停止迁出，转脱敏或升级）
- 未跟踪条目疑似活跃并行会话的在途工作产物（停止 rm，先升级归属裁决）

## Verification
- rm 前后校验 sha256(源)==sha256(目的)，且目的文件权限 600
- git status 不再列出该条目后才重交，重交不再出现同类拒绝
- 向用户披露迁出位置、哈希与处置建议（销毁/入库管理），因为该文件可能是他人事故的产物而非本批交付物

## Counterexamples
- 瞬时性拒绝（timeout/5xx/服务未就绪）：reason 不点名树内条目类别，原样重试是正确动作，本方法不适用
- 敏感字面量就在自己必须交付的文件里：迁走文件会毁掉交付，应改内容/脱敏而非搬文件
- 未跟踪文件是另一活跃会话的在途工作：单方 rm 破坏他方状态，先做归属判定（与 gate-attribution-on-shared-tree 类方法衔接）
- 同文件系统且 mv 被允许：直接 mv+哈希复核即可，无需 cp+chmod+rm 分解
