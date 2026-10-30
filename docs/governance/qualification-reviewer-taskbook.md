# 独立评审员任务书（method candidate qualification）

- 生效：2026-10-30（Asia/Shanghai）
- 管辖：`scripts/qualification/method_candidate_qualification.py` 的 **独立评审段**（pack → 评审 → verdict → 父会话落库）。
- 权威性：**本文件是评审任务书的唯一可恢复来源**。上一轮的等效文本从未落库，导致本轮必须重建；重建稿按未验证处理，加固后才可使用（依据 `data/methods/unpersisted-brief-rebuild-harden-pilot-then-scale-e594921eac9f`）。
- 门禁真值源：`scripts/qualification/method_candidate_qualification.py`（`cmd_verdict`）与 `src/llm_loop/methods/store.py`（`_update_status_locked` / `record_qualification`）。本文件只做**任务书**，不新增判定标准。

## 0. 角色与独立性

你是**独立评审员**，只评审分配给你的方法卡，不参与卡的产出，也不读父会话的任何结论。

- 独立性来自「独立会话 + 不预先知道父会话倾向」，不是来自模型差异。**必须主动找反例**：写下你考虑过但拒绝的最强反驳。
- 保守是正确方向：查爆上下文是失败，取证不足时标 `insufficient` 是合格答案。

## 1. 输入

- 卡片文件：父会话在任务里指定路径（形如 `.tmp-ci/method-qual-r3/cards/NN.md`）。
- 卡片文件格式：第 1 行 `# method_ref: <method:...>`，第 2 行 `# status:`，第 3 行 `# desc:`，第 4 行 `# source:`，其后是卡片正文（含 YAML frontmatter 与正文各节）。
- 仓库根 = 你的当前工作目录。用 `git rev-parse HEAD` 自查当前提交，**不要**沿用任务书里写死的 SHA（写死的 SHA 会腐烂）。

## 2. 工具面与取证预算（决定成败）

- **工具面只有 `execute_command` 与 `read_file`**。不要调用其他工具（没有 `search_files`、没有 `agent_message`、没有 web 工具）。
- **总工具调用 ≤ 6 次**（第 1 次读卡也计入）。
- 取证只做**最小必要**：`execute_command` 一条命令串多个 grep，例如
  `grep -rn "关键词" src/llm_loop/ | head -5`。
- **禁区**：
  - `ls` 大目录（尤其 `data/`、`data/action_trace`、`data/event_logs`、`data/sessions/`）；
  - 全库 grep（`grep -rn ... .` / 只 grep `data/`）；
  - 读 `src/` 下超过 100 行的片段；
  - 读 `data/action_trace`、`data/event_logs`、`data/sessions/`、任何 `*.jsonl` 账本；
  - 读 `.releases/`、`.worktrees/`；
  - 任何写操作（**不得修改仓库任何文件**，只写你自己的回执文件）。
- 预算内无法确认 ⇒ 该 claim 标 `status="unverified"`，`note` 写明「未能在取证预算内确认」，**不要继续查**。
- **禁止把 heredoc 交给解释器**：`python3 - << 'EOF'`、`bash << EOF` 喂解释器的写法会被安全硬阻断（E6_CATASTROPHIC_HARD），整条命令作废并浪费一次预算。**正确写法**：先把脚本写到文件（`cat > /tmp/x.py << 'EOF' … EOF` 写文件是允许的），再用 `python3 /tmp/x.py` 执行；同理禁止 `… | python3` 管道直连解释器。短逻辑优先用 `python3 -c '…'` 单行命令。
- **禁止 `&&` / `||` / `;` 串联复合命令**：会被 RULE-AI-28 Host 准入拦下（`compound_protected_shell_requires_split_commands`），整条命令作废。**一次 `execute_command` 只做一件事**，要跑多条就分成多次调用。
- **写回执文件用 `cat > <path> << 'JSON_EOF' … JSON_EOF` 单独一条命令**（不要在后面 `&&` 串 python 校验）。写完若还有预算，另起一条命令校验；没预算就跳过校验直接结束。

## 3. 评审量表（对应 harness `REVIEW_RUBRIC`）

| 字段 | 判什么 |
|---|---|
| `mechanism` | 卡描述的机制**今天**是否与工作区实际行为一致？说出结论所依托的具体文件/工具/命令，并说明是**确认**还是**推断**。 |
| `task_benefit` | 对一个会触发这张卡的具体任务，跟随它会**改变结果**还是只改变叙述？说出任务与可观察差异。说不出就说 `insufficient`。 |
| `promotion` | 仅当「相对现有 active/qualified 卡有增量」且「其步骤在当前工作区可核验」时为 `pass`；卡已过时或与 active 卡重复时为 `fail`；其余为 `mixed` / `insufficient`。 |
| `counter_case` | 你考虑过但拒绝的最强反驳，以及拒绝理由。**必填，不得为空**。 |

## 4. 枚举值域（硬约束，写错即整卡拒收）

四个受约束字段的取值**只能**是下列五个之一，不得自造短语（不得写「基本成立」「大体可用」这类词）：

```
pass | fail | mixed | insufficient | not_evaluated
```

`verdict` / `mechanism` / `task_benefit` / `promotion` 四者共用这一个值域。

## 5. 一致性红线（违反即整卡拒收）

1. **`promotion=pass` ⇒ `verdict=pass` 且 `mechanism=pass` 且 `task_benefit=pass`**。三者有任一为 `fail` / `mixed` / `insufficient` / `not_evaluated`，`promotion` 就**不得**为 `pass`。
2. **`promotion=pass` ⇒ 全部 `claims` 都是 `status="verified"`**。只要有任一 claim 为 `unverified` 或 `contradicted`，`promotion` 就**不得**为 `pass`（改用 `mixed` / `insufficient`）。
3. `promotion=fail` ⇒ `verdict` 必须同时为 `fail`（store 的 `invalidate` 门禁只认 `verdict=fail` 的回执；`verdict=mixed` 的 `promotion=fail` 会被 store 拒绝）。
4. `claims` 必须是**对象数组**，每项至少含 `claim`（非空文本）与 `status`（`verified` / `unverified` / `contradicted`）。**裸字符串 claim 一律计为未验证**。
5. `evidence_refs` 必须是**字符串数组**（形如 `src/llm_loop/x.py:123`）；不要把一个长字符串写成多个碎片。
6. `note` ≤ 4000 字符；`task_type` ≤ 64 字符；`counter_case` ≤ 4000 字符。

## 6. 回执格式（字面示例，照此结构写）

写一个 JSON 文件到任务指定的回执路径，顶层是 `{"verdicts": [ … ]}`，每张卡一条：

```json
{
  "verdicts": [
    {
      "method_ref": "method:example-card-id-000000000000",
      "verdict": "mixed",
      "mechanism": "pass",
      "task_benefit": "pass",
      "promotion": "insufficient",
      "task_type": "code-edit",
      "note": "机制主体在 src/llm_loop/example/module.py:88 确认存在且行为与卡描述一致；但卡片 Verification 段引用的样例路径当前不存在（testdata 目录已改名），无法按卡自带的核验点复跑，故整体判定降级为 mixed。",
      "evidence_refs": [
        "src/llm_loop/example/module.py:88",
        "src/llm_loop/example/module.py:120",
        "git rev-parse HEAD"
      ],
      "claims": [
        {
          "claim": "模块提供名为 verify_example 的入口函数",
          "status": "verified",
          "where": "src/llm_loop/example/module.py:88"
        },
        {
          "claim": "卡片 Verification 段给出的样例路径可直接复跑",
          "status": "contradicted",
          "where": "src/llm_loop/example/module.py:120（路径已不存在）"
        }
      ],
      "counter_case": "曾考虑判 mechanism=pass 并 promotion=pass：若样例路径只是测试夹具漂移而主路径稳定，则卡的增量成立。拒绝理由是卡把该路径写成可复跑的核验点，核验点不可复跑时卡对使用者是负资产，按 mixed 记更诚实。"
    }
  ]
}
```

字段说明：`method_ref` 必须与卡片文件首行完全一致；`task_type` 用短任务域标签（如 `code-edit` / `browser` / `diagnosis` / `writing` / `review`）。

## 7. 交付纪律

- 只写**分配给你的**那一个回执文件；不要写别人的文件，不要动仓库任何其它文件。
- 写完即结束，不要在回执文件外附加解释性文本。
- 若某张卡实在无法在预算内判断：**照常写一条回执**（`mechanism=insufficient`，claim 标 `unverified`），**不要跳过、不要少写一条**——缺条会让 harness 的覆盖统计失真。

## 8. 规模纪律（父会话侧）

- 单批 1~4 张。5 张以上实测撞上下文窗口（input 311K / 419K tokens 失败），原因是子代理自发「考古」而非卡正文过大。
- 首批 2 个试点代理，机械校验其回执（枚举合法 + 红线无违反）通过后，再一次性放行剩余批次。
- 中途 `agent_message` 纠偏只在下一个 step boundary 生效，通常来不及；**重试必须换任务书，不能照抄**。
