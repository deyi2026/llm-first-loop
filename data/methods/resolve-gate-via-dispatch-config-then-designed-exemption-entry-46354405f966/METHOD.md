---
method_id: resolve-gate-via-dispatch-config-then-designed-exemption-entry-46354405f966
name: resolve-gate-via-dispatch-config-then-designed-exemption-entry
description: 确定性门禁（git hook/lint/CI check）拦截操作、用户要求豁免时：先查宿主系统的权威分发配置（如 git config --get core.hooksPath）一步定位真实执行入口，而非按门禁名称做全仓搜索或枚举默认安装位置；沿入口文件的显式引用边找到实现脚本；在实现内 grep 豁免关键词（allowlist/exempt/豁免）定位设计内豁免口，并确认其匹配语义与跳过范围（白名单命中通常跳过全部规则，不只是触发的那条）；登记前抽查被拦目标是否含会被连带放过的其他敏感模式；按文件内既有先例格式带理由登记，最后以门禁真实调用路径（staged 扫描+实际提交）复验。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1766:d5d09236a40666fbcde1
evidence_refs: learning:learn:2e52422a6e83
created_at: 2026-09-18T07:02:49.319574+00:00
updated_at: 2026-09-18T07:02:49.319574+00:00
---
## Trigger
确定性门禁（pre-commit hook、lint、CI check 等）拦截了用户想完成的操作，用户询问如何豁免/放行，且门禁名称或报错信息已知

## Discriminator
门禁由宿主系统按确定性配置分发调用——git 钩子的真实位置有且只有一个权威答案（core.hooksPath，未设置才回退默认目录）；且门禁实现源码通常自含设计内豁免入口（可 grep 豁免/allowlist 关键词命中）。这两点在动手时即成立，可直接把'全仓找实现+猜安装位置'缩成'一次配置查询+沿入口 provenance 读实现'。

## Short path
- 查宿主分发配置解析真实执行入口（git config --get core.hooksPath；返回空才看默认 .git/hooks）——未知量：门禁实际执行的是哪个文件
- 读钩子入口文件（如 pre-commit），沿其显式 exec/引用边找到实现脚本——未知量：拦截逻辑实现在哪
- 在实现脚本内 grep 豁免关键词（allowlist|exempt|豁免|whitelist），读命中处定义与调用点——未知量：是否存在设计内豁免口、匹配语义（子串/精确）与跳过范围
- 抽查被拦目标内容是否命中豁免会连带跳过的其他规则（密钥/私钥/大文件等）——未知量：登记豁免是否安全、是否与仓内既有豁免先例同类
- 按文件内既有条目格式+理由注释登记一条豁免；git add 后以门禁真实模式手动重跑（如 --staged），再执行真实提交让钩子原生再拦一次验证

## Stop conditions
- 已定位设计内豁免口并确认其跳过范围，且被拦目标经抽查不含其他敏感模式
- 豁免已登记，且门禁以真实调用路径（staged 扫描 + 实际提交）复验通过
- 实现内不存在设计内豁免口：停止，不绕过（不用 --no-verify / -f），向用户报告并提议最小显式修改

## Verification
- git add 后以门禁真实模式手动重跑（如 bash <实现脚本> --staged），核对通过输出中的目标文件数
- 执行真实提交，让 pre-commit 钩子原生再拦一次，确认二次放行且提交成功
- diff 核对新增豁免条目与文件内既有条目格式/注释先例一致，改动仅为登记行

## Counterexamples
- 门禁是第三方工具，豁免口在项目配置文件（如 ignore/excludes 配置）而非工具源码——应 grep 项目配置，不该改工具本身
- 被拦文件实际含真实密钥或私密内容——豁免本身是错误动作，应修内容或剔除文件
- 门禁不经宿主配置分发（手工脚本、平台侧服务调用），无 core.hooksPath 类权威入口——此时按名称/文档搜索才是合理首步
- 门禁在运行时动态生成或与仓库版本不一致——必须核对实际被调用的那份实现，而非仓内同名文件
