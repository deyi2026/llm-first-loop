---
method_id: redaction-form-from-tracked-precedent-before-first-edit-ff73d2cb2ac7
name: redaction-form-from-tracked-precedent-before-first-edit
description: 入库/外发前要把资产里的私有字面量（真实用户名、绝对 home 路径、内部主机名）脱敏成占位写法时，替换形态不由直觉或转义习惯决定，也不『先编辑再对答案』：判定字面量不可保留所用的那份 tracked 权威语料（对字面量 0 命中）同时就是『该写成什么形态』的答案源——对同一语料再 grep 一次模式家族（如 /Users/）即可读出既有占位形态（<user>/<name>/...），选定语义等价者后才发起第一次原子编辑；Markdown 卡片先例用裸尖括号，不做 HTML 转义。语料无先例时自选可读占位并明示『无先例决策』，不硬造转义形态。
aliases: 入库前真实路径换成什么占位符, 脱敏写法照老卡先例来, 占位符别自己发明 别用HTML转义, 改敏感串之前先grep库里既有写法, 用户名占位写 <user> 还是 &lt;user&gt;
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:11:1600c46ec063230f1529
evidence_refs: learning:learn:f245f2c2be9b
created_at: 2026-11-05T15:04:53.756772+08:00
updated_at: 2026-11-05T15:04:53.756772+08:00
---
## Trigger
提交/外发前的敏感串扫描命中私有字面量（真实用户名、绝对路径、内部主机名等），需要替换为占位形态，且仓库内存在同构 tracked 资产可作惯例权威；第一次替换编辑尚未发生

## Discriminator
0 命中扫描已把 tracked 语料加载为几秒内可再查的权威：同一语料对该模式家族（去掉私有段，如 /Users/）的一次 grep 直接给出既有占位形态；在拿到该形态前发起编辑就是在发明新形态（本集先写成 &lt;user&gt; 转义，随后被迫补查先例＋复读＋二次编辑才回到 <user>）

## Short path
- 敏感串家族扫描（如 grep home 前缀）定位命中文件与行；未知量：哪些条目要改
- 对 tracked 权威语料 grep 同一字面量：0 命中＝不可保留；未知量：替换成什么形态
- 对同一语料 grep 模式家族（如 /Users/），读出既有占位形态清单，逐字选语义等价者；未知量：目标文本
- 一次原子编辑替换为 precedent 形态，复读/diff 校验无转义残留
- 回到入库闸：dry-run 核对清单 → 执行 flush → --check rc=0、敏感串复查 0 命中

## Stop conditions
- 新文本与 tracked 先例占位形态同形、复读一致，且将入库集敏感串复查 0 命中
- 语料对该模式家族零先例：自选明确可读的占位并在交付说明中标注为无先例决策后停止，不再反复改写

## Verification
- grep tracked 语料确认所选占位形态先例计数>0（而非只验证字面量消失）
- 对将入库全集重跑敏感串扫描为 0 命中
- 编辑回执 diff 只含预期一处替换，无 &lt; 之类转义残留

## Counterexamples
- tracked 语料对该模式家族零先例（全新内容类型）→ precedent grep 无法裁决，硬套会制造伪惯例；应自选占位并记录决策
- 字面量位于会被执行的代码/配置或必须转义的格式（HTML/XML 正文）内 → 形态服从目标格式与语义安全，不服从卡片先例
- 字面量是密钥/令牌类秘密 → 目标是彻底移除与轮换，占位形态只是次要可读性问题，本方法不适用
