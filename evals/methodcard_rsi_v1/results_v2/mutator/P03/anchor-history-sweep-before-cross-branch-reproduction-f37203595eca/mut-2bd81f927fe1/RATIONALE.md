# 变异理由 — anchor-history-sweep-before-cross-branch-reproduction-f37203595eca

mutator 0.1.0；检出缺陷 1 项，采纳算子 1 条。

## 逐条

### unlinked_verification @ Stop conditions

- 缺陷：1 条验证条目未被任何 Stop condition 引用：根因结论须三证齐备：锚点在 F 全历史 0 命中、锚点现居位…
- 编辑：`append_bullet`
- 理由：验证条目没有任何停止条件引用它 = 验证与结案脱钩；补一条把验证结果绑到结案动作的规则。

## 未采纳

- 变异器只做结构修复，不生成新的事实断言、不引入新证据、不改 frontmatter。
- 需要语义改写时由人工或 LLM 变异器另开一轮，产物同样须过预注册评估。
