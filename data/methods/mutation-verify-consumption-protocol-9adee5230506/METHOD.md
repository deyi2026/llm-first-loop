---
method_id: mutation-verify-consumption-protocol-9adee5230506
name: mutation-verify-consumption-protocol
description: browser mutation 之后的验证消费纪律：diff-first、空 diff 的正确语义（区分"预期无变化"与"预期有变化"）、FR-6 哨兵字段消费规则、receipt≠效果。承接 DESIGN-20261007-browser-semantic-guard FR-5a。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:214:2fdd68f4342af1ca5489
freshness_refs: src/llm_loop/browser/perception.py,src/llm_loop/browser/method_card.py,docs/DESIGN-20261007-browser-semantic-guard.md
parent_ref: method:method-semantic-operation
created_at: 2026-10-07T09:01:57.493157+08:00
updated_at: 2026-10-07T09:01:57.493157+08:00
---
# Method: Mutation-verify consumption protocol (FR-5a)

## Trigger

A browser mutation (`browser_operate` click/set_text/select/scroll/navigate) just returned a mechanical ActionReceipt, and the task expects an observable effect on the page; or a snapshot/diff/hydrate result contains `value_text == "<redacted:sensitive>"`; or a diff between two snapshots comes back with `changed: []` and the task expected something to change.

## Discriminator

This card governs how verification evidence is consumed, not which mutation to run (that is `method-semantic-operation`). Apply it whenever the question is "did it work?" after a receipt, not "what should I do next?". The receipt proves the action was dispatched; only re-observation proves the world changed.

## Short path

1. Read the receipt. If it reports failure/dry-run, stop — no diff consumption is meaningful.
2. Consume the diff attached to (or hydratable from) the receipt before taking any new snapshot: the receipt's changed-object refs hydrate cheaply and answer most "did it take effect" questions.
3. Empty diff is evidence only for the expectation "nothing should change". If the task expects a visual/interactive effect, attribute-level diff emptiness is NOT completion — re-observe with a fresh snapshot (or vision evidence) covering the expected change.
4. Gate completion on objects, not scope: `wait object_state/object_text` on a grounding_ref beats page-ready/URL checks.
5. If any consumed `value_text` equals `<redacted:sensitive>` (FR-6 sentinel), treat the field as policy-excluded: never match/assert its concrete value, never treat it as empty, and do not count it as missing data.

当前性验证：`grep -n "SENSITIVE_VALUE_SENTINEL\|_redact_value_text" src/llm_loop/browser/perception.py` 应命中函数定义与 DOM/AX/sensor 三处调用；`grep -n "redacted:sensitive" src/llm_loop/browser/method_card.py` 应命中 compact 消费纪律；`python3 -m pytest tests/unit/test_browser_perception_sensitive_redaction.py -q` 应 7 passed。三者任一落空即本卡前提过期。

## Stop conditions

- Receipt failed or was a dry-run (stop, report the failure as-is).
- Diff non-empty and changed fields exactly match the expected effect (complete).
- Expected effect is visual/interactive and a fresh snapshot or vision evidence confirms it (complete).
- Expected effect is "no change" and diff is empty with `comparable: true`, same scope, complete completeness (complete — but record that this rests on attribute semantics, not pixels).

## Verification

- Every "it worked" claim in the final answer cites either a diff entry or a re-observed snapshot object, not just a receipt.
- For visual expectations, at least one re-observation after the mutation exists in the trace.
- No assertion anywhere relies on the concrete value of a redacted field.
- Post-conditions gated on `object_state`/`object_text`, not on scope-level URL/ready states, unless the effect is itself navigational.

## Counterexamples

- Treating an empty diff as "click had no effect, so the feature is broken" when the expectation was a visual change the diff cannot see.
- Treating an empty diff as success when the expectation was a semantic change (text/state) — emptiness there means the mutation likely did not apply; investigate instead of concluding.
- Asserting `value_text` of a password/token field matched or asserting it is empty: the sentinel is neither a value nor emptiness.
- Re-snapshotting from scratch every time, ignoring the receipt's diff (works, but pays a full capture round for information already in hand).
- Using page_ready/URL as the gate for a button-enabled or text-change expectation (scope state does not prove object state).
