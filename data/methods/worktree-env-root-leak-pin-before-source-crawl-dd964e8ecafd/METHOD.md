---
method_id: worktree-env-root-leak-pin-before-source-crawl-dd964e8ecafd
name: worktree-env-root-leak-pin-before-source-crawl
description: 在 git worktree/次级 checkout 中运行测试或工具，若行为暗示读到了树内不存在的配置（未知新字段、版本漂移、结果与树内文件矛盾），先用一条命令对比『进程可见的 root 类 env 变量』与『checkout 本地配置文件』：本地无配置却读到配置，说明解析被 shell env 或向上目录搜索劫持到主仓；调用时把根变量显式钉到 checkout 根再复跑即可确认。本集据此定位 LFL_RUNTIME_ROOT 指主仓导致 worktree 测试读到新 runtime.toml 字段，钉根后 24 passed，省去对 resolver 源码的多段顺序阅读。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:535:2e4d7642fbd066a1e888
evidence_refs: learning:learn:3a8352690220
created_at: 2026-10-17T06:34:46.976645+08:00
updated_at: 2026-10-17T06:34:46.976645+08:00
---
## Trigger
在 git worktree 或任何次级 checkout 内执行测试/工具时，出现『行为暗示读到了该 checkout 树中不存在的配置』的症状（未知新字段、配置版本漂移、结果与树内文件矛盾），且正准备深入顺序阅读配置解析源码排查。

## Discriminator
当时已可观察的事实：checkout 本地不存在自己的配置文件（如 runtime.toml 为 NONE），但运行行为证明配置确实被读取——这一矛盾说明配置必然来自 checkout 之外；再配合一条 env|grep 发现 root/workspace 类变量值为指向主仓或发布目录的绝对路径，即可把多种候选原因缩成『外部根劫持』单一假设。该判别只需失败症状与目录事实，无需先读完解析器源码。

## Short path
- 步骤1：在 checkout 内确认症状，并检查本地配置文件是否存在（一条 ls/test）
- 步骤2：列出值指向 checkout 之外的 root/workspace 类 env 变量（一条 env|grep）
- 步骤3：本地无配置 + env 指向外部 → 成立『配置泄漏自主仓』假设，停止顺序通读解析源码
- 步骤4：（可选）单次定位读根解析函数（如 _default_runtime_root），仅确认 env 优先级，不做全文浏览
- 步骤5：调用测试时显式钉 env 根到 checkout 根（如 LFL_RUNTIME_ROOT=$PWD）并复跑同一命令；通过即停

## Stop conditions
- 钉根后同一测试命令通过，且与解析器声明的优先级（env > 本地文件 > 向上搜索）一致，归因成立即停止排查
- 确认 env 指向外部根是部署设计意图（双根共享部署）时停止钉根，改走部署或测试期望侧修复
- 钉根后仍失败 → 排除环境泄漏，转入常规代码级排查

## Verification
- 钉根前后各运行一次完全相同的测试命令，仅当钉根后通过才归因于 env 泄漏
- 对照根解析源码中的优先级声明，确认观察行为与之一致
- 确认 checkout 内确无该配置文件，排除把树内配置误判为外部来源

## Counterexamples
- 在主 checkout 运行：env 指向主仓根即正确配置，钉根反而破坏部署
- 钉根后测试依旧失败的真代码/测试 bug：环境检查无收益，应走常规排查
- 设计上要求所有 checkout 共享同一 runtime 根的双根部署：钉根会掩盖预期行为
- 工具只按 cwd 相对路径解析配置、无 env override 且不向上搜索：env 检查不适用
