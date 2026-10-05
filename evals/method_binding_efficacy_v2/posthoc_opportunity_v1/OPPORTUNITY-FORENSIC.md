# Subject-Binding Efficacy v2 — Failure-of-Opportunity Forensic

Status: post-hoc exploratory, provider-free, does not reopen or modify the frozen v2 verdict.

## Result

The confirmatory v2 verdict remains `EFFICACY_NOT_QUALIFIED`. The new question here is why the qualified B challenge stratum produced zero C0 errors on both Strong and Weak.

Mechanical findings:

- selected B cases: 13
- realized C0 errors: Strong 0/13, Weak 0/13
- 11/13 tasks contain an explicit anti-trigger negation such as `没有 / 不存在 / 不需要 / 不是 / 尚未`
- the remaining 2/13 encode an explicit positive alternative path that makes SKIP immediately available
- 6/13 additionally contain exclusive-scope wording such as `只需要 / 只问 / 当前唯一目标 / 先...再...`
- therefore 13/13 B cases expose an easy SKIP channel in task text
- Strong and Weak C0 made zero tool calls in the scored set, so control solved the task directly from prompt + full Method card

This is a **failure of treatment opportunity**, not label invalidity. IQ-CTOR-v2 proved that the B labels were semantically valid; it did not prove that the control model would find them difficult. The old structural reachability gate incorrectly treated `certified H+ count` as a proxy for `available C0 error/headroom`.

## Protocol compression

The formal prompt itself says `请判断该 Method 是否适用于当前任务` and injects the complete Method card, including Trigger/Discriminator/Counterexamples. The subject-binding treatment, by contrast, is appended to the `save_experience` tool description and says to judge a hydrated Method against the current task's **claim subject**, not against result/output/fixture carriers.

This does not invalidate v2: the same explicit-classification protocol historically produced a real mb-024 C0→C1 correction. But it compresses difficulty and therefore should remain fixed in the immediate successor so that only challenge construction changes. If a properly calibrated hard pool still ceilings under C0, prompt/protocol assistance becomes the next isolated variable to study.

## Historical hard exemplar: mb-024

`mb-024` is the useful template because its task states only a positive goal: verify whether claimed code identifiers really exist and where they are defined. It does **not** say that the task is "not writing an allowlist artifact" or explicitly negate the trap Method's Trigger.

The trap Method is about mechanically extracting identifier names from authoritative definitions **before writing an enumerated artifact**. Both task and Method share identifiers, definitions, summaries, and authoritative sources, but their purposes differ.

Latest-wins historical outcome:

- C0: APPLY (wrong)
- C1: SKIP (correct)

That is the structure to reproduce: same domain/evidence/action vocabulary, different positive claim subject/purpose, no anti-trigger sentence that gives away SKIP.

## Root-cause classification

Primary: **challenge-construction leakage**.

Secondary: **protocol assistance/compression** (explicit applicability question + full card), not yet isolated as a causal failure.

Governance bug: **label validity was conflated with experimental headroom**.

Not supported by this evidence: Method-card quality failure, model capability ceiling, reverse-risk harm, subject-binding delivery failure, or cost failure.

## Successor rule

Do not immediately run another confirmatory matrix. First qualify difficulty on a disjoint development split, using C0 only. Tune/freeze abstract challenge families from dev behavior, then generate a fresh confirmatory holdout from those families. Never select confirmatory cases because their own C0 result was wrong.
