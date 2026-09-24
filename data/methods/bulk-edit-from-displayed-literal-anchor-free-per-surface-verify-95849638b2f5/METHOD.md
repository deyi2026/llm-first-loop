---
method_id: bulk-edit-from-displayed-literal-anchor-free-per-surface-verify-95849638b2f5
name: bulk-edit-from-displayed-literal-anchor-free-per-surface-verify
description: 批量替换多文件中的同一字符串（版本面 bump、配置面等）时，先用同一字面量 grep 列出各目标表面的完整行，再从已显示的字面行派生替换模式：禁用凭记忆假设的行首锚（目标 token 前常有其他字段），旧值多处出现时加上下文保唯一。编辑后用新值字面量重查，要求每个预期表面恰好出现——sed 对不匹配静默 exit 0，缺失表面=未替换而非成功。本集 `^**Version**` 锚定模式在 README（Version 居行中、前有 License 段）零匹配但命令成功，靠后检才发现并多花一轮修正。反模式：凭记忆写锚定正则、把 exit 0 当替换成功、只验证部分表面。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:777:80852e4f93dc769ea908
evidence_refs: learning:learn:de072dcfd2ad
created_at: 2026-09-24T10:37:17.319552+00:00
updated_at: 2026-09-24T10:37:17.319552+00:00
---
## Trigger
需要一次编辑多个文件中的同一目标字符串（版本号/配置标识/URL），且预检 grep 或上一步工具输出已经显示过各目标行的完整内容；或所用编辑工具（sed/replace）对不匹配静默成功、不报错。

## Discriminator
预检输出中目标 token 的行内位置与精确字面形式：若 token 不在行首（如 `> **License**: … ｜ **Version**: 0.6.25 ｜ …`），任何 `^` 行锚模式必然零匹配且 sed 仍 exit 0；且各表面格式互异（`version = "x"`、`SERVICE_VERSION = "x"`、`**Version**: x`），单一通配模式无法覆盖全部表面。

## Short path
- 用同一字面量预检 grep，收集所有预期表面的 文件:行号:完整行 内容，确认表面清单与各自格式
- 逐表面从显示的字面行派生替换模式：去掉行锚、取足够长的无锚子串；旧值在同文件多次出现时附加上下文使其唯一
- 应用编辑后，用新值字面量重跑同一 grep：每个预期表面必须恰好出现一次
- 缺失任一表面则判定为静默未替换，回到预检字面行修正模式重试，而不是换工具或放宽为全文件盲替换
- 跑守卫测试（如版本一致性测试）作行为级确认，再提交/tag

## Stop conditions
- 新值字面量 grep 覆盖全部预期表面且无多余命中
- 守卫测试通过，diff 中被修改文件数等于预检表面数

## Verification
- 后检 grep 新值：预期表面集合逐一出现，缺失即失败
- 状态/diff 显示的改动文件数与预检表面数一致
- 守卫测试（版本面一致性）为绿
- 不以编辑命令 exit 0 作为替换成功的证据

## Counterexamples
- 旧版本号在同一文件多处出现（如 CHANGELOG 历史条目）：无锚全局替换会改写历史记录，必须限定上下文或只编辑指定行
- 版本面由专用工具（bump2version、npm version 等）托管：手动 sed 本身是反模式，应调用工具
- 目标串位于生成产物文件中，重新构建即被覆盖：应编辑源头而非产物
- 单一表面且已有强守卫测试覆盖时：预检/后检可合并为一步，无需全套流程
