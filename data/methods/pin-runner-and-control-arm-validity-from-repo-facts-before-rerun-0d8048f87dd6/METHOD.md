---
method_id: pin-runner-and-control-arm-validity-from-repo-facts-before-rerun-0d8048f87dd6
name: pin-runner-and-control-arm-validity-from-repo-facts-before-rerun
description: 重跑仓库内旧实验脚本前，用仓库自证事实先钉死两类前置未知量，避免枚举式试错。(1) 执行方式：根目录锁文件(uv.lock/poetry.lock)+.env 即证明既定 runner 是包管理器 run（依赖随锁同步），裸 .venv python 可能缺传递依赖，PATH 无 runner 时用绝对路径，且先 no-API 干跑再花钱调用。(2) 实验有效性：git log HEAD 若已含被测修复提交，脚本内『复刻现行生产行为』的对照臂即过期，修复入生产后复刻臂=处理臂，直接重跑得到无效数据；须 diff 复刻函数与 HEAD 生产实现，处理臂改 import 生产实现、对照臂显式反转该变量，保住单变量归因。另：发现类工具 no-match 但先验强时，换机制（find 含隐藏/旁路目录）而非换宽 pattern 重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5e09cedf-9412-454e-b7a9-f0247530ef7c:115:942796a9ffa64fb2d540
evidence_refs: learning:learn:4f767b4af258
created_at: 2026-09-22T17:19:44.119143+00:00
updated_at: 2026-09-22T17:19:44.119143+00:00
---
## Trigger
用户要求修改（如换模型/参数）并重跑仓库中既有的实验或复测脚本，且脚本可能位于旁路目录、依赖仓库 venv 与 .env 凭据、内部复刻了『现行生产行为』作为对照臂

## Discriminator
第一次 pwd/git log/ls 就已暴露的两个事实：HEAD 提交历史包含被测修复提交（说明脚本里『现行行为』复刻臂已过期，双臂会塌缩成同一格式）；根目录存在 uv.lock 与 .env（说明既定执行方式是 uv run 而非裸 .venv python）。这两条在写任何代码前即可把『怎么执行』与『对照臂是否还有效』两个未知量各缩到唯一候选。

## Short path
- 先 pwd/git branch/git log + 根目录 ls：确定 HEAD 是否已含被测修复提交、收集工具链证据（uv.lock、.env 变量名），这两个事实决定后续所有路径
- 定位脚本：发现类工具 no-match 但上下文先验强（提交信息/会话提到过该实验）时，立即换机制用 find 含隐藏/旁路目录（如 .tmp-ci），不要换更宽 pattern 重试
- 读脚本，一次性列出：model= 调用点、凭据/base_url 注入方式、以及所有标注『现行行为』的复刻函数
- 把每个复刻函数与 HEAD 生产实现 diff：若过期，处理臂改为 import 生产实现（测真实路径），对照臂显式反转该单一变量（如去锚点）
- 模型切换三对齐（model 名/base_url/key 环境变量名），并查目标模型的 reasoning_control 语义（如 always_on_effort 下 thinking_mode=False 等于不发开关，无害）
- 用既定 runner 执行（uv run；which 不中则绝对路径）：先 no-API 干跑断言两臂 history 格式只差单一变量，再真实调用并落盘 JSON，逐条核对 refs 后停止

## Stop conditions
- 两臂 history 字符串在无 API 干跑中断言通过：仅目标变量不同，其余逐字一致
- 切换后首次真实调用成功返回（key/base_url 正确性随即被验证），结果落盘且解析 failures=0
- refs 与构造会话的真实消息 idx 逐条核对一致后即停止，不追加确认性调用

## Verification
- 干跑断言：处理臂 history 含锚点、对照臂不含，其余内容逐字一致（单变量归因成立）
- 结果 JSON 中调用成功率 4/4、解析 failures=0，refs 与真实 idx 对账全部命中
- 复刻函数 diff 结论用 read_file 快照与 HEAD 生产代码行号双重核对，而非凭注释或记忆

## Counterexamples
- 自包含 stdlib-only 脚本、无锁文件、shell 已激活正确 venv：不存在 runner 歧义，锁文件判别器不存在，预检纯属浪费，直接改 model 重跑即可
- 实验在未合入修复的独立分支上执行（HEAD 不含被测 fix）：『现行行为』复刻臂仍然准确，无需改写双臂，只做 runner/凭据对齐
- 脚本的两个臂均在内部独立定义、不声称复刻任何生产行为：对照臂过期校验无对象，方法退化为仅执行前置检查
