---
name: fit-page-limit
description: 篇幅达标规划——论文超页限或篇幅不足时，逐节量化"长度去哪了"，给出优先级方案：压缩/移附录哪些低价值节、补实哪些薄弱节，同时保护贡献、结果与引用；不删证据、不为凑页注水。触发：超页限、页数超了、压缩论文、该删哪里、trim、over the page limit、too long、too short、fit the limit。
license: MIT
metadata:
  vendored-from: ShaishavMaisuria/research-paper-lifecycle-skills@f9a0ed8
  adapted-for: llm-first-loop（2026-10-10）
---

# Fit Page Limit

> **LFL 本地化说明（2026-10-10）**：源自 ShaishavMaisuria/research-paper-lifecycle-skills@f9a0ed8f0f1770fb0321c5b022d55ed34c939927（MIT，LICENSE 随附）。scripts/section_budget.py 纯 stdlib，本机已实测（真实 tex 输入，逐节词数/页数估算，输出自带 "Estimate only" 提示）。

Two sides of the same problem: a paper that is **over** the limit and needs
careful cuts, or a paper that is **under** and needs useful substance rather
than filler. This skill maps the draft section by section, then gives the author
a prioritized plan for whichever direction they need.

It coordinates with [`polish-prose`](../polish-prose/SKILL.md) for sentence-level
tightening, [`refactor-structure`](../refactor-structure/SKILL.md) for larger
reorganization, [`polish-tables-figures`](../polish-tables-figures/SKILL.md) for
visual layout, and [`preflight-check`](../preflight-check/SKILL.md) when the
page limit comes from a venue rule. Run it after the draft is roughly complete.

## When to use

- The draft is over the limit and the author needs to know where the bulk is.
- The draft is under the target length and the author wants to use space well.
- The author asks for a length map: "where is all my length going?"

## Inputs

- The `.tex` source.
- The real compiled page count, if available, to calibrate the estimate.
- The target: a venue page limit or a length the author names.
- The venue CFP or profile, if the target comes from a venue.

## Process

1. **Map the length.** Run the analyzer from this skill directory; do not
   eyeball where the pages went.

   ```bash
   python3 scripts/section_budget.py paper.tex --target-pages 10 --current-pages 11
   ```

   It reports per-section words, percentage of the paper, estimated pages, and
   the over/under gap. `--current-pages` calibrates words per page to the
   author's actual compile. Use `--json` for machine-readable output.

2. **Confirm what counts.** Re-verify the venue's limit and exclusions against
   the live CFP before relying on appendix moves or excluded sections. A stale
   page limit can desk-reject the paper.

3. **Pick the right branch.** Use
   [references/resize-tactics.md](references/resize-tactics.md) to turn the
   map into a value-aware resize plan.

### If over: compress value-aware, never blind

Rank sections by **compressibility x low impact**, and cut there first:

- **Redundancy**: the same point repeated in the intro, method, and conclusion.
- **Over-long related work**: condense paragraph-per-paper prose into clusters
  that state only the delta that matters.
- **Verbose method/setup**: tighten with `polish-prose`; cut walkthroughs a
  figure already shows.
- **Move, do not delete**: push proofs, extra results, or implementation detail
  to an appendix only when the venue excludes it.
- **Figures/tables**: resize, merge subfigures, or drop a redundant baseline
  column with `polish-tables-figures`.

Protect contributions, headline results, and every citation. Present estimated
savings per cut and let the author approve before editing. Never delete a
result, claim, or reference to hit a number.

### If under: expand with substance

A short, complete paper can be fine; say so. If there is real room to strengthen
it, suggest substance: a missing ablation, deeper error analysis, limitations
or threats to validity, clearer motivation, a worked example, or a related-work
gap. Flag suggestions that would merely pad. Hand drafting to the writing
skills.

## Output

A length map and prioritized resize plan:

- **Over**: ranked cut list, estimated savings, and protected material.
- **Under**: substantive additions ranked by value.

Write durable outputs to the user's local `paper-workspace/writing/` directory
when a workspace exists. The skill recommends and explains; the author decides
and edits.

## Guardrails

- Never delete results, claims, or citations to fit.
- Never pad to fill.
- Page numbers are estimates; tell the author to compile and check the real
  count.
- Re-verify venue limits and exclusions against the live CFP before advising
  appendix moves.
- Copilot, not pilot: propose the plan; the author approves and edits.

## Memory

Uses the shared `.paper-memory/` convention documented by
[`paper-profile`](../paper-profile/references/paper-memory-convention.md).

- **At start:** read `lessons.md` for recurring overspend patterns, such as
  "related work always runs long".
- **At end:** append `date - fit-page-limit - over/under - where the length went
  - what was cut/added` after deduping.
- Create `.paper-memory/` on demand in the user's paper directory. It is local
  only and should usually be ignored by git.
