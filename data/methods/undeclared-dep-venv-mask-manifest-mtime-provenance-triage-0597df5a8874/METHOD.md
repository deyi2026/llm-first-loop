---
method_id: undeclared-dep-venv-mask-manifest-mtime-provenance-triage-0597df5a8874
name: undeclared-dep-venv-mask-manifest-mtime-provenance-triage
description: 全量门禁在合并上游提交后的候选分支上以成批 collection/import 错误退出、错误点名缺某依赖包时，不要被『当前共享 venv 里该包能 import』或『重跑变绿』迷惑：venv 是可变共享状态，可能是失败后他人手工补装出的假绿。以冻结依赖清单（pyproject/uv.lock/requirements）为权威做三点定性：清单是否声明该包、包 dist-info mtime 是否晚于门禁启动、失败文件由哪个提交引入（上个绿提交不存在→上游合并带入）。然后在声明层修复并锁版本，用 fresh 环境（uv sync --frozen 类）实测导入后重跑全量门禁、红数对账；一切以 job 终态 exit code 为准，不信状态笔记对结果的预设。
aliases: venv里包是好的怎么还报缺, 合并上游后测试起不来缺模块, 共享环境被别人pip装过包, fresh环境必挂本地能跑, 缺依赖归上游还是归我, 重跑门禁绿了但lock没锁
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89aa4eb4-d3e8-4612-9858-cce4b0fe5b6d:1684:e38efd480090de5b0cc5
evidence_refs: learning:learn:838248e887bb
created_at: 2026-10-26T01:18:27.912930+08:00
updated_at: 2026-10-26T01:18:27.912930+08:00
---
## Trigger
门禁/测试链 exit≠0，失败为同因成批的测试收集/导入错误且信息点名缺失依赖（如提示 pip install X）；多会话共享同一工作区/venv，且当前 venv 里该包又能正常导入；候选分支刚合并过上游新提交

## Discriminator
冻结依赖清单里 grep 不到该包 + 包 dist-info/安装产物 mtime 晚于门禁 job 启动时间 → venv『现在能用』是事后人工补装的假绿；git 显示失败文件在上一绿提交不存在、由合并进来的上游提交新增 → 缺声明的责任在上游引入者而非候选补丁，但修复应落在候选的声明层

## Short path
- 读当前 job 的终态回执取真实 exit code 与失败摘要，不信状态笔记/计划里的预期结果
- 把红聚类：N 个文件同一收集错误=单一根因，不逐文件修
- git 归属：失败文件在上一绿提交是否存在、由哪个提交引入（log/diff stat/父提交 path 检查）
- 清单权威：grep pyproject/uv.lock/requirements 确认包是否声明；未声明即 undeclared dependency
- 时间线：包 dist-info mtime 对比门禁启动时间，把『venv 现在有』定性为事后补装
- 声明层修复：pyproject+lock 声明并锁版本，fresh venv（--frozen 同步）实测导入
- 重跑全量门禁至 EXIT 0 并做红数对账；核对上游新移动是否触碰依赖文件（合并冲突面）

## Stop conditions
- 依赖已在清单声明且锁定版本，fresh 环境导入成功
- 全量门禁 EXIT 0 且红数与登记台账对账一致
- 上游后续提交不触碰依赖文件，合并冲突面确认为空

## Verification
- fresh venv 按 --frozen 同步后 import 该包成功
- 门禁 exit code=0、红数与棘轮台账一致
- 清单 grep、mtime 时间线、git 归属三条证据同向印证后再下结论

## Counterexamples
- 清单里其实已声明该包，失败源于同步不完整/锁文件陈旧 → 重同步声明环境即可，勿重复声明
- 缺依赖的代码是候选自己新增的 → 归属上游是错的，修复责任在己
- 单所有者的一次性 CI 环境（无并行写入者）→ 缺包即环境构建缺陷，无需 mtime 排查
- 错误点名的包在 venv 与清单均存在，失败另有根因（如路由注册副作用）→ 回到常规失败分诊，不套依赖归因
