## 动机
（这个改动解决什么问题）

## 改动内容
- （列出主要改动点）

## 测试
- [ ] 新增/更新测试（列出测试文件与用例）
- [ ] 本地三件套门禁全绿：`pytest -m "not real_llm"` + `ruff` + `pyright`
- [ ] 行为影响说明（默认行为是否变化；零回归优先）

## A.5 架构提交声明
- [ ] 本 PR 新增/更新且仅新增/更新一个 `docs/governance/submissions/*.json` manifest。
- [ ] manifest 的 `components[].paths` 精确覆盖本 PR 的全部 changed paths；每个 path 只归属一个 component。
- [ ] 每个 component 显式声明 `control_machinery=true|false`；`true` 时引用完整 G1-G4 declaration。
- [ ] 已人工/模型审查 declaration 的**内容是否成立**。CI 只检查结构 presence / changed-path coverage，不判断 G1-G4 语义质量，也不从源码猜 control 分类。

本地复现（提交前 staged diff）：

```bash
python scripts/check_architecture_submission.py --staged
```

## 行为影响
- 默认行为：不变 / 变化（说明）
- 新配置项：（如有，列出名称与默认值）
- 公开面影响：文档/CHANGELOG 是否同步更新

## 备注
（相关 issue、截图、注意事项）
