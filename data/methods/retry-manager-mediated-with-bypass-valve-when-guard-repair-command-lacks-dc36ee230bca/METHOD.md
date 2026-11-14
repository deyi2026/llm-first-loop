---
method_id: retry-manager-mediated-with-bypass-valve-when-guard-repair-command-lacks-dc36ee230bca
name: retry-manager-mediated-with-bypass-valve-when-guard-repair-command-lacks
description: 命令被项目预检守卫拦截、回执自述『修复命令+逃生阀』两条出路，而按修复命令直连 venv 解释器仍报缺工具模块时，把『工具由哪一层注入』当唯一未知量：dev/测试工具是包管理器 run 时注入、并非 venv 常驻依赖，直接改用管理器中介调用并挂上回执给出的逃生阀，跳过 venv 目录勘察与全局工具路径搜索；绕行后须核对实际环境与守卫声明一致，并把确切调用形式写进复现摩擦备注。
aliases: 预检拦截跑不了测试, uv run 被环境预检挡住, venv 里找不到 pytest, 跳过环境预检复现, 修复命令失败换逃生阀
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:40fa4095-d9ce-44af-a7ce-d4147d2e1907:2:1859704d2340ec9839e6
evidence_refs: learning:learn:4b47a88dc8d0
created_at: 2026-11-14T13:36:29.761037+08:00
updated_at: 2026-11-14T13:36:29.761037+08:00
---
## Trigger
仓库自带预检/守卫拦截常规命令（如包管理器 run 跑测试），回执同时自描述修复命令（直连项目 .venv 解释器）与逃生阀（环境变量跳过预检）；按修复命令执行后失败为该 venv 内没有此工具模块（No module named <tool>）

## Discriminator
拦截回执已点名期望解释器（项目 .venv、版本正确）且给出逃生阀，仓库由包管理器+锁文件管理；修复命令的缺模块失败 ⇒ 工具非 venv 常驻依赖、由管理器 run 时注入 ⇒ 回执菜单里剩下的唯一候选就是『管理器中介调用+逃生阀』

## Short path
- 按仓库常规入口一次尝试目标命令，拿到守卫拦截回执
- 把回执自述的选项菜单（修复命令/逃生阀）当作仅有候选：先执行修复命令，同时记住另一条
- 修复命令失败为 venv 缺工具模块 → 判定工具由管理器注入 → 改用管理器中介+锁定形式并挂逃生阀（如 <逃生阀变量>=1 <管理器> run --frozen <目标>）
- 得到确定性结果（pass/fail 均为终态）后，核对实际环境与守卫声明一致，并把该调用形式写进复现备注

## Stop conditions
- 管理器中介+逃生阀形式产出确定性结果，目标命令已真正执行
- 修复命令第一跳即成功（venv 已装工具），无需绕行
- 守卫拦截出于安全/合规而非环境选择 → 停止绕行、修根因

## Verification
- 重跑输出是目标命令的真实结果而非又一次预检拦截文本
- 绕过守卫后确认实际解释器/依赖集与拦截回执声明的期望环境一致（借锁文件/frozen flag 钉住），否则结果不可信
- 复现备注记录确切的环境变量名与管理器 flag 组合

## Counterexamples
- pip/venv 项目中工具已装入 venv：修复命令直接成功，套用反而多余
- 守卫目的是安全隔离（禁网/沙盒/合规审计）而非解释器选择：跳阀等于绕过保护本身，禁止套用
- 管理器中介调用仍选中错误解释器且测试结果环境敏感：单靠逃生阀不够，必须先让管理器选中期望环境
