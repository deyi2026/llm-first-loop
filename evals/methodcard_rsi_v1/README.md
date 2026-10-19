# 方法卡 RSI v1（变异器 + held-out + 预注册）

三件东西配套使用，缺一不可：

| 文件 | 作用 | 冻结 |
|---|---|---|
| `heldout_v1.jsonl` | 20 条行为题（5 类 × 4），内联输入，无仓库依赖 | `FREEZE.json` sha256 |
| `grade_holdout.py` | 纯机械判分（无 LLM 裁判）；`--verify-freeze` 防改题 | — |
| `build_heldout_v1.py` | 重新生成题库（会改变 hash，等于新版本） | — |
| `prereg_v1_cards.jsonl` | 30 张试验卡（seed 20261019，分层 6×5） | `PREREG-FREEZE.json` |
| `sample_prereg_cards.py` | 重新抽样（seed 固定，可复现） | — |
| `analyze_prereg.py` | 预注册判据 D1–D4 的实现 | — |
| `../../scripts/method_mutator.py` | 缺陷驱动的确定性变异器（frontmatter 只读） | — |

## 常用命令

```bash
# 1) 判分器自检（管路，不是题目可答性证明）
python3 evals/methodcard_rsi_v1/grade_holdout.py --selftest

# 2) 校验题库未被改动
python3 evals/methodcard_rsi_v1/grade_holdout.py --verify-freeze

# 3) 对一张卡只报缺陷（不改盘）
python3 scripts/method_mutator.py --check --card data/methods/<card>/METHOD.md

# 4) 产出候选（diff + 理由 + manifest），默认写 data/methods/_candidates/
python3 scripts/method_mutator.py --card data/methods/<card>/METHOD.md \
    --ops dup,vague,unlinked_ver --allow-todo --json

# 5) 判分一批 artifact（ans/H01.json … ans/H20.json）
python3 evals/methodcard_rsi_v1/grade_holdout.py --artifact-dir ans/ --strict

# 6) 预注册分析（30 对齐全才跑）
python3 evals/methodcard_rsi_v1/analyze_prereg.py --results results.jsonl --json
```

## 边界（别越界用）

- 变异器**只做结构修复**：删重复条目、补"验证挂停止条件"、给不可核措辞留判据槽位、补空段占位。不生成新事实、不改 frontmatter、不自动入卡。
- 产物一律 `review_required=true / status=candidate`；"能生成候选"不等于"可以上线"。
- 本目录不提供 L2（自动应用 + 自动回滚）的任何东西；那需要另一次预注册。
