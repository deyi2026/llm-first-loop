---
title: monkeypatch 模块级常量做 A/B 量化时：引用别名污染 + 条件写反，双重失效会静默产出 0/0
scenario: 为量化某个架构改动的误报/漏报面，用 monkeypatch 替换模块级常量（如 validator._COMPLETION_MARKERS）做「现状 vs 候选方案」对照统计。需要测量「保留校验」数量的差异时。
root_cause: |
  两个独立的实现缺陷叠加，产出的结论形态是「0/0」而非异常，因而不会触发任何报错信号：
  
  1. **引用别名污染**：`old = V._COMPLETION_MARKERS` 取到的是同一个 list 对象的引用而非副本，随后 `V._COMPLETION_MARKERS[:] = filtered` 就地修改，等于把 `old` 这个"备份"一起改掉了。恢复语句 `V._COMPLETION_MARKERS[:] = old` 赋回的是已被污染的内容。跨样本循环时前一次迭代的污染会流入下一次，全局状态不再等于初始状态。
  
  2. **分支条件写反**：把「已剥离目标标记」的 markers 列表传入后，又用 `if "了" in markers` 决定是否走新的判定分支——目标标记早已被剥离，条件恒为假，新的判定路径一次都没执行。函数仍会经由下方其他豁免函数返回合法值，因此不抛异常，只是统计结果全部相同。
  
  两者叠加使输出退化为「现状 N 条 / 方案 M 条 / 差 0」，即两方案完全一致——而实际差异本应非零。这个结果形态本身（精确的 0）就是可疑信号：真实语料上的两种判定规则几乎不可能恰好给出完全一致的分类分布。
solution: |
  **不要 monkeypatch 常量，改写成无副作用的纯函数门。**
  
  把「完成标志门」从「读模块常量」重写为接受标记列表作为参数的闭包，让对照统计的输入完全显式：
  
  ```python
  OTHERS = [m for m in _COMPLETION_MARKERS if m != TARGET]
  def gate_current(t): return any(m in t.lower() for m in OTHERS) or (TARGET in t)
  def gate_candidate(t): return any(m in t.lower() for m in OTHERS) or CANDIDATE_RE.search(t)
  ```
  
  这样两条路径共享同一份基线常量，互不干扰，也不会污染全局状态。
  
  **配套的三条自检：**
  
  1. **对 0/0 差异主动报警**：当两方案差异恰好为 0 时，先怀疑实现，再怀疑语料。若真实语料上两种不同规则给出完全一致的分类分布，概率上近乎不可能，应当直接中断并逐行复查分支是否真的被执行。
  
  2. **断言分支可达**：写完判定后，加一条针对性断言强制新路径至少被命中一次（例如 `assert any(gate_candidate(t) for t in probe_samples)`），使「分支从未执行」在测试期就失败，而不是以 0/0 的形态静默流出。
  
  3. **变量名必须与语义逐字对应**：同一轮里出现过 `freed` 实际装着「仍保留校验」的样本。统计脚本里凡是用 `not (A or B or C)` 得到的集合，命名时要对照代码注释确认它到底是「被豁免」还是「未被豁免」——`not(...)` 的极性在长脚本里极易翻转。改为分别统计两个方向并各自打印，比用一个带极性的布尔量安全。
  
  **当前性验证动作**（复现本条结论，成本一条命令）：
  
  ```
  cd /Users/yyj/Project/llm-first-loop-mirror && PYTHONPATH=src .venv/bin/python -c "
  import sys; sys.path.insert(0,'src')
  import llm_loop.feedback.validator as V
  old=V._COMPLETION_MARKERS
  V._COMPLETION_MARKERS[:]=[m for m in old if m!='了']
  print('污染确认:', old is V._COMPLETION_MARKERS and '了' not in old, '| 备份被同步改写:', '了' not in old)
  "
  ```
  
  应打印 `污染确认: True | 备份被同步改写: True` —— 即 `old is V._COMPLETION_MARKERS` 成立且备份里「了」已消失，证明备份无效。反之若打印 False，说明该版本常量已是拷贝语义，本条经验不适用。
  
  **补充：变量名标反与引用污染会互相掩护。** 本次先发现 `freed` 命名与内容相反（531 实为「仍保留校验」而非「被豁免」），修正后又发现 monkeypatch 污染。若只修其一，仍会拿到看似合理的错误数字。因此对量化脚本的每个中间量都应能一句话说清「它装的是什么、按什么极性筛出来的」。
evidence: |
  本会话实测（2026-10-13，问题二提案 EVO-20261013-60fe9141 的量化环节）：
  
  第一次量化脚本输出「现状保留 0 | 方案C保留 0 | 差 0」。该 0/0 为假结论。根因两处：
  - `old = V._COMPLETION_MARKERS` 之后 `V._COMPLETION_MARKERS[:] = [...]` 就地修改同一 list 对象，备份被同步污染；
  - `if "了" in markers` 判断的 markers 已剥离「了」，恒为 False，新分支从未执行。
  
  改写为纯函数门（gate_current / gate_C，基线常量外提为 OTHERS）后重测，得到有区分度的结果：当代 cohort 583 条声明中 23 条（3.9%）转为可豁免；方案 C 在 12 条真阳性样本上漏报 3 条（改了/删掉了/保存到了，带补语不匹配动词表原形）；方案 D（词干×补语尾）漏报 1/12（目录删干净了）。
  
  另有变量极性错误：初次统计中 `freed = [d for d in pool if not (DV._is_ability_statement(d) or ...)]`，实际装的是「四项豁免均不成立 = 仍保留校验」的 531 条，而非命名为 freed 所暗示的「被豁免」；真实新豁免量为 52（分类口径）或 23（完成标志门口径）。
tags: [monkeypatch, 量化验证, 对照组设计, 静默失效, Python, 可变对象别名, boolean极性, A/B对照]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T22:11:20.066715+08:00"
updated_at: "2026-10-13T22:11:20.066715+08:00"
---