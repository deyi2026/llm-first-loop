---
name: preflight-check
description: 投稿桌拒预检 linter——把 LaTeX 源码对照会议 machine-readable 档案做确定性检查：模板/页边距篡改、页限风险、匿名泄漏、必备节缺失（NeurIPS checklist、ICML impact statement 等）、摘要长度、关键词格式，每个发现带 file:line；stdlib 脚本，只建议不提交。触发：能不能投了、desk reject、submission check、投稿前检查、格式合规、页数够不够、NeurIPS/ICML/CHI/CVPR/LNCS 投稿。
license: MIT
metadata:
  vendored-from: ShaishavMaisuria/research-paper-lifecycle-skills@f9a0ed8
  adapted-for: llm-first-loop（2026-10-10）
---

# Preflight Check

> **LFL 本地化说明（2026-10-10）**：源自 ShaishavMaisuria/research-paper-lifecycle-skills@f9a0ed8f0f1770fb0321c5b022d55ed34c939927（MIT，LICENSE 随附）。scripts/ 纯 stdlib；本机端到端实测：自建迷你 venue 档案 + 带泄漏 tex，2 ERROR + 4 WARN 全部命中并附 file:line。注意：venue 档案上游不附带（SKILL.md 引用的 venues/schema.yml 上游未发布，属上游文档缺口）——按 scripts/venue_profile.py 文档串的 YAML 子集编写，实测可用字段：name/year/documentclass/columns/page_limit/blind/tracks[name,required_sections]。

Run a deterministic desk-reject lint over a LaTeX submission before the
authors hit "submit". Venues explicitly desk-reject — without review — for
page-limit violations, template tampering, anonymization leaks, and missing
mandatory sections. Every one of those is machine-checkable from the source.
This skill catches them while there is still time to fix them.

## When to use

- "Is my paper ready to submit to NeurIPS / SIGSPATIAL / CHI / ...?"
- "Check my paper for desk-reject risks" / "run a preflight"
- "Did I anonymize this properly?" / "double-blind check"
- "Am I over the page limit?" / "is my template compliant?"
- Right after `tailor-to-venue`, and always before any actual submission.

## Inputs

1. The main `.tex` file of the submission (the one with `\documentclass`).
   `\input`/`\include` files are followed automatically.
2. A venue profile: `venues/conferences/<venue>-<year>.yml` (schema in
   `venues/schema.yml`). If the venue has no profile yet, create one first
   with `parse-cfp` (or copy the nearest family file and fill it in).
3. Optional but strongly recommended: a compiled `.log` or `.pdf` next to the
   `.tex` (same basename) so the page-count risk check can run.

## Process

1. **Resolve the venue profile.** Find the matching file under
   `venues/conferences/`. Confirm the year matches the target deadline cycle.
   Ask the user which track they are submitting to — page limits differ per
   track (e.g. SIGSPATIAL Research = 10 pages excl. references, Demo = 4
   incl.). Sanity-check the merged profile with:
   `python3 scripts/venue_profile.py venues/conferences/<venue>.yml --track <name>`

2. **Re-verify critical facts against the live CFP — mandatory.** Profiles
   are a starting point, never ground truth; a stale page limit causes the
   exact desk reject this skill exists to prevent. Fetch the profile's
   `cfp_url` and confirm: page limit + what it excludes, blind level,
   template invocation, required sections, and the deadline. If anything
   differs, update the profile YAML first and say so in the report.

3. **Run the full preflight:**

   ```
   python3 scripts/run_preflight.py paper.tex \
       --venue venues/conferences/<venue>-<year>.yml --track "<track>"
   ```

   Or run checkers individually when the user asks about one dimension:

   | Script | Checks | Run |
   |---|---|---|
   | `scripts/check_template.py` | documentclass + options vs profile, year-versioned .sty (NeurIPS/ICML/ICLR), geometry/savetrees/fullpage, `\setlength` on layout dims, `\linespread`<1, negative `\vspace` patterns, column count, page-limit risk from `.log`/`.pdf` | `python3 scripts/check_template.py paper.tex --venue <yml> --track <t>` |
   | `scripts/check_anonymization.py` | `\author`/`\affiliation`/`\email`/`\orcid`/`\thanks` content, acknowledgments sections, funding/grant lines, identifying links (GitHub, personal pages) vs anonymized mirrors, first-person self-citations, hyperref `pdfauthor` | `python3 scripts/check_anonymization.py paper.tex --venue <yml>` |
   | `scripts/check_sections.py` | every `format.required_sections` token: NeurIPS checklist, ICML impact statement, AI-use acknowledgement (ICDE), COI declaration, CCS concepts + `\keywords`, plus title/abstract/bibliography presence | `python3 scripts/check_sections.py paper.tex --venue <yml>` |
   | `scripts/check_abstract.py` | abstract word count vs venue bounds (or the 150–250 norm), single-paragraph rule, citations/URLs in abstract, keywords format (ACM/IEEE Index Terms/LNCS 3–6) | `python3 scripts/check_abstract.py paper.tex --venue <yml>` |

   Useful flags on every script: `--json` (machine-readable), `--strict`
   (warnings also fail), `--track <substring>`, `--venues-dir <dir>` (when the
   profile lives outside this repo), `--no-inputs`. Anonymization adds
   `--force` to scan even at single-blind venues.

4. **Interpret severities for the user.**
   - `ERROR` — documented desk-reject grounds at this venue. Must fix.
   - `WARN` — judgment call (e.g. one negative `\vspace` is normal; eight is
     space compression). Walk through each with the user.
   - `INFO` — confirmations and pointers to manual checks. Do not pad the
     report with these; summarize.
   Exit codes: 0 = no errors, 1 = errors found (or warnings with `--strict`),
   2 = bad arguments/missing files.

5. **Do the manual checks the linter cannot do.** Source-level linting
   cannot see compiled-PDF metadata, where the references actually start,
   supplementary files, or submission-form fields (COI declarations at ICDE
   live in CMT, not the PDF). Work through
   [references/manual-checks.md](references/manual-checks.md) with the user.

6. **Fix and re-run until clean.** Quote each finding's `file:line`, propose
   the minimal edit, apply it if asked, and re-run the affected checker.
   For the reasoning behind each check (which venue desk-rejects for what,
   with sources), see
   [references/desk-reject-triggers.md](references/desk-reject-triggers.md).

## Output

A findings report (text or `--json`) per checker or combined via
`run_preflight.py`: severity, check id, `file:line`, message, summary counts,
and a verdict (`FAIL` if any ERROR, `PASS with warnings` if only WARNs, else
`PASS`). Present it to the user as a fix-list ordered by severity, then offer
to apply fixes one at a time.

## Worked example

A NeurIPS submission that still carries author identity and last year's style
file. Running the combined checker:

```
python3 scripts/run_preflight.py paper.tex \
    --venue venues/conferences/neurips-2026.yml
```

```
=============================================================================
PREFLIGHT REPORT  paper.tex
venue: neurips-2026   track: main
=============================================================================

-- template --------------------------------------------------------------
   [ERROR] template/style-file-year             paper.tex:1 — uses neurips_2025.sty; NeurIPS 2026 requires neurips_2026.sty
   [WARN ] template/negative-vspace             paper.tex:312 — negative \vspace before figure; isolated, likely fine

-- anonymization ---------------------------------------------------------
   [ERROR] anonymization/pdf-metadata           paper.tex:14 — \hypersetup{pdfauthor=...} leaks the author into PDF metadata
   [WARN ] anonymization/author-block           paper.tex:22 — \author populated; the .sty hides it at submission, but scrub the source
   [WARN ] anonymization/self-citation          paper.tex:88 — "our previous work [12]" — rewrite in third person

-- sections --------------------------------------------------------------
   [ERROR] sections/missing:neurips-checklist   paper.tex — no NeurIPS checklist found; a missing checklist is a desk reject

-- abstract --------------------------------------------------------------
   clean.

=============================================================================
VERDICT: FAIL — fix ERRORs before submitting   (3 error(s), 3 warning(s), 0 info)
Profiles can go stale: re-verify limits/policies at https://neurips.cc/Conferences/2026/CallForPapers
=============================================================================
```

How to present this: lead with the three ERRORs as a numbered fix-list
(`neurips_2026.sty`, drop the `pdfauthor` leak, add the checklist), each with
its `file:line` and the one-line edit; then walk the WARNs as judgment calls.
Re-verify the page limit and checklist requirement at the `cfp_url` before the
user relies on the verdict, then re-run the affected checker after each fix.

## Adapt to your discipline

Profiles can represent conferences, journals, and workshops in any field. Add
venue YAMLs with your community's rules — the checkers only read the profile,
so new disciplines need data, not code.

## Guardrails

- A clean preflight is necessary, not sufficient — never tell the user the
  paper "will not be desk-rejected"; say "no machine-checkable desk-reject
  triggers found".
- Always re-verify page limits/deadlines/policies against the live `cfp_url`
  before the user relies on them (step 2 is not optional).
- Never submit to any system on the user's behalf; stop at the report.
- Never paste large portions of the user's paper into the report — quote at
  most the flagged line.
- Citation problems are out of scope here: route them through
  `verify-citations`.

## Memory

This skill uses the shared `.paper-memory/` convention in the user's paper
directory, following [`paper-memory-convention.md`](../paper-profile/references/paper-memory-convention.md).

- **At start:** read `.paper-memory/lessons.md` (and `profile.yml` for venue
  tier / constraints). Skip re-flagging issues already recorded and acted on;
  lead with any `recurring` desk-reject habits this author has (e.g. "you tend
  to compress layout near the page limit").
- **At end:** append each finding worth remembering as one dated entry in the
  shared format `- [YYYY-MM-DD] (preflight-check | <scope>) issue ->
  recommendation` (use `reflect-and-improve`'s `reflect_log.py append`, which
  dedupes and dates). Tag a repeat-across-papers habit `recurring`, a one-off
  `this-paper`.
- Create `.paper-memory/` on demand if absent and offer to add it to the
  project `.gitignore`. It is local-only; never upload it or copy it into this
  repo.
